"""Conector para Remotive (API oficial curada de empleos 100% remotos)."""

import logging
import httpx
from bs4 import BeautifulSoup
from eros.hunter.filters import check_job_qualification
from eros.hunter.sources.base import BaseJobSource
from eros.models import JobOffer

logger = logging.getLogger(__name__)


class RemotiveSource(BaseJobSource):
    """Conector para Remotive (puestos de software 100% remotos internacionales)."""

    @property
    def name(self) -> str:
        return "remotive"

    async def fetch_jobs(self) -> list[JobOffer]:
        url = "https://remotive.com/api/remote-jobs?category=software-dev&limit=40"
        offers: list[JobOffer] = []

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; ErosAgent/1.0; +https://mateogs.tech)",
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(f"Remotive respondió con status {resp.status_code}")
                    return []

                payload = resp.json()
                items = payload.get("jobs", [])

                for item in items:
                    job_id_ext = str(item.get("id"))
                    title = item.get("title", "")
                    req_location = (item.get("candidate_required_location") or "Worldwide").strip()
                    loc_lower = req_location.lower()

                    # 1. Filtro estricto de ubicación de Remotive
                    # Descartar si es exclusivo de USA, Europa o Canadá
                    if any(bad in loc_lower for bad in ["usa only", "us only", "europe only", "uk only", "canada only", "germany only"]):
                        continue

                    # 2. Limpieza de descripción
                    desc_html = item.get("description", "")
                    clean_desc = BeautifulSoup(desc_html, "html.parser").get_text(separator="\n").strip()

                    tags = item.get("tags") or []
                    company = item.get("company_name", "Empresa Remota")
                    salary = item.get("salary") or None
                    job_url = item.get("url") or f"https://remotive.com/remote-jobs/software-dev/{job_id_ext}"
                    pub_date = item.get("publication_date")

                    # 3. Pasar por filtros heurísticos (seniority, stack, geo)
                    qual = check_job_qualification(
                        title=title,
                        description=clean_desc,
                        country=req_location,
                        tags=tags,
                    )
                    if not qual.qualified:
                        logger.debug(f"Remotive: vacante '{title}' descartada: {qual.reason}")
                        continue

                    job_offer = JobOffer(
                        id=self.generate_job_id(job_id_ext),
                        source=self.name,
                        external_id=job_id_ext,
                        title=title,
                        company=company,
                        url=job_url,
                        description=clean_desc[:3000],
                        tags=tags,
                        salary=salary,
                        country=req_location,
                        is_remote=True,
                        published_at=pub_date,
                    )
                    offers.append(job_offer)

                    if len(offers) >= 20:
                        break

            except Exception as e:
                logger.error(f"Error extrayendo ofertas de Remotive: {e}")

        logger.info(f"Remotive: {len(offers)} vacantes de alta calidad parseadas.")
        return offers
