"""Conector para We Work Remotely (RSS Feeds oficiales de puestos Frontend y Fullstack)."""

import logging
import xml.etree.ElementTree as ET
import httpx
from bs4 import BeautifulSoup
from eros.hunter.filters import check_job_qualification
from eros.hunter.sources.base import BaseJobSource
from eros.models import JobOffer

logger = logging.getLogger(__name__)


class WeWorkRemotelySource(BaseJobSource):
    """Conector para We Work Remotely (puestos remotos globales de alta reputación)."""

    @property
    def name(self) -> str:
        return "weworkremotely"

    async def fetch_jobs(self) -> list[JobOffer]:
        feeds = [
            "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss",
            "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
        ]
        offers: list[JobOffer] = []
        seen_links: set[str] = set()

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ErosAgent/1.0",
            "Accept": "application/rss+xml,application/xml,text/xml",
        }

        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            for feed_url in feeds:
                try:
                    resp = await client.get(feed_url)
                    if resp.status_code != 200:
                        logger.warning(f"WeWorkRemotely respondió con status {resp.status_code} para {feed_url}")
                        continue

                    root = ET.fromstring(resp.content)
                    channel = root.find("channel")
                    if channel is None:
                        continue

                    items = channel.findall("item")

                    for item in items:
                        link_el = item.find("link")
                        link = (link_el.text or "").strip() if link_el is not None else ""
                        if not link or link in seen_links:
                            continue

                        seen_links.add(link)

                        # Título y Empresa suelen venir en formato "Company: Title"
                        title_el = item.find("title")
                        raw_title = (title_el.text or "").strip() if title_el is not None else ""
                        if ":" in raw_title:
                            company_part, title_part = raw_title.split(":", 1)
                            company = company_part.strip()
                            title = title_part.strip()
                        else:
                            company = "Empresa Remota"
                            title = raw_title

                        # Región geográfica especificada por WWR
                        region_el = item.find("region")
                        region = (region_el.text or "").strip() if region_el is not None else "Anywhere in the World"
                        region_lower = region.lower()

                        # Descartar exclusiones estrictas de EE.UU. o Europa en la región
                        if any(bad in region_lower for bad in ["usa only", "us only", "europe only", "uk only", "canada only"]):
                            continue

                        # Descripción
                        desc_el = item.find("description")
                        raw_desc = desc_el.text or "" if desc_el is not None else ""
                        clean_desc = BeautifulSoup(raw_desc, "html.parser").get_text(separator="\n").strip()

                        # Fecha
                        pub_el = item.find("pubDate")
                        published_at = pub_el.text.strip() if pub_el is not None and pub_el.text else None

                        # Identificador externo
                        job_id_ext = link.rstrip("/").split("/")[-1]

                        # Calificación heurística
                        qual = check_job_qualification(
                            title=title,
                            description=clean_desc,
                            country=region,
                            tags=["remote", "weworkremotely"],
                        )
                        if not qual.qualified:
                            logger.debug(f"WWR: vacante '{title}' descartada: {qual.reason}")
                            continue

                        job_offer = JobOffer(
                            id=self.generate_job_id(job_id_ext),
                            source=self.name,
                            external_id=job_id_ext,
                            title=title,
                            company=company,
                            url=link,
                            description=clean_desc[:3000],
                            tags=["remote", "weworkremotely"],
                            salary=None,
                            country=region,
                            is_remote=True,
                            published_at=published_at,
                        )
                        offers.append(job_offer)

                        if len(offers) >= 15:
                            break

                except Exception as e:
                    logger.error(f"Error procesando feed de We Work Remotely ({feed_url}): {e}")

        logger.info(f"We Work Remotely: {len(offers)} vacantes seleccionadas.")
        return offers
