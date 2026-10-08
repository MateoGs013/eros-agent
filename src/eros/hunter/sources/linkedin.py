import asyncio
import logging
import httpx
from bs4 import BeautifulSoup
from eros.hunter.filters import check_job_qualification
from eros.hunter.sources.base import BaseJobSource
from eros.models import JobOffer

logger = logging.getLogger(__name__)

# User-Agents realistas de escritorio para solicitudes públicas
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class LinkedInJobsSource(BaseJobSource):
    """Conector para vacantes públicas de LinkedIn enfocado en LATAM, Argentina y Remoto Internacional."""

    @property
    def name(self) -> str:
        return "linkedin"

    async def fetch_jobs(self) -> list[JobOffer]:
        queries = [
            # 1. Puestos remotos de Full Stack en LATAM (Prioridad principal)
            "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=Full+Stack+Developer&location=Latin+America&f_WT=2&f_TPR=r604800&start=0",
            # 2. Puestos remotos de Full Stack en Argentina
            "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=Full+Stack+Engineer&location=Argentina&f_WT=2&f_TPR=r604800&start=0",
            # 3. Puestos remotos de Full Stack TypeScript / Node / Web
            "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=Full+Stack+TypeScript+Node&location=Latin+America&f_WT=2&f_TPR=r604800&start=0",
            # 4. Frontend / UI Engineer con TypeScript (React / Vue)
            "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=Frontend+Developer+TypeScript&location=Latin+America&f_WT=2&f_TPR=r604800&start=0",
        ]

        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        offers: list[JobOffer] = []
        seen_ids: set[str] = set()

        async with httpx.AsyncClient(headers=headers, timeout=15.0, follow_redirects=True) as client:
            for idx, query_url in enumerate(queries):
                if idx > 0:
                    await asyncio.sleep(2.0)  # Pausa entre búsquedas para respetar rate-limit
                try:
                    resp = await client.get(query_url)
                    if resp.status_code == 429:
                        logger.warning(f"LinkedIn rate-limit (429) en consulta {idx+1}. Se omiten consultas siguientes en este ciclo.")
                        break
                    elif resp.status_code != 200:
                        logger.warning(f"LinkedIn guest search respondió con status {resp.status_code} para {query_url}")
                        continue

                    soup = BeautifulSoup(resp.text, "html.parser")
                    cards = soup.find_all("li")

                    for card in cards:
                        # Extraer URN y ID
                        card_div = card.find("div", class_="base-card")
                        if not card_div:
                            continue

                        raw_urn = card_div.get("data-entity-urn", "")
                        if not raw_urn or ":" not in raw_urn:
                            continue

                        job_id_ext = raw_urn.split(":")[-1].strip()
                        if not job_id_ext or job_id_ext in seen_ids:
                            continue

                        # Título
                        title_el = card.find("h3", class_="base-search-card__title")
                        title = title_el.get_text(strip=True) if title_el else ""
                        if not title:
                            continue

                        # Empresa
                        company_el = card.find("h4", class_="base-search-card__subtitle")
                        company = company_el.get_text(strip=True) if company_el else "Empresa Confidencial"

                        # Ubicación
                        loc_el = card.find("span", class_="job-search-card__location")
                        location = loc_el.get_text(strip=True) if loc_el else "Remoto"

                        # Fecha
                        time_el = card.find("time")
                        published_at = time_el.get("datetime") if time_el else None

                        # URL directa y limpia
                        clean_url = f"https://www.linkedin.com/jobs/view/{job_id_ext}"

                        # Intentar obtener la descripción completa desde la API pública de detalle
                        description = f"Puesto: {title}\nEmpresa: {company}\nUbicación: {location}\nModalidad: Remoto\nEnlace: {clean_url}"
                        try:
                            await asyncio.sleep(0.4)  # Cortesía para evitar 429
                            desc_url = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id_ext}"
                            d_resp = await client.get(desc_url)
                            if d_resp.status_code == 200:
                                d_soup = BeautifulSoup(d_resp.text, "html.parser")
                                desc_div = d_soup.find("div", class_="show-more-less-html__markup")
                                if desc_div:
                                    clean_text = desc_div.get_text(separator="\n", strip=True)
                                    if len(clean_text) > 50:
                                        description = clean_text
                        except Exception as e:
                            logger.debug(f"No se pudo descargar descripción extendida de LinkedIn {job_id_ext}: {e}")

                        # Pre-filtro riguroso de calificación (descarta US-only, Staff/Director, Polygraph, etc.)
                        qual = check_job_qualification(
                            title=title,
                            description=description,
                            country=location,
                            tags=["LinkedIn", "Remote"],
                        )
                        if not qual.qualified:
                            logger.debug(f"LinkedIn: '{title}' descartada: {qual.reason}")
                            continue

                        seen_ids.add(job_id_ext)

                        # Normalizar a JobOffer
                        offer = JobOffer(
                            id=self.generate_job_id(job_id_ext),
                            source=self.name,
                            external_id=job_id_ext,
                            title=title,
                            company=company,
                            url=clean_url,
                            description=description,
                            tags=["LinkedIn", "Remote"],
                            salary=None,
                            country=location,
                            is_remote=True,
                            published_at=published_at,
                        )
                        offers.append(offer)

                except Exception as e:
                    logger.warning(f"Error consultando vacantes en LinkedIn ({query_url}): {e}")

        logger.info(f"LinkedIn Jobs: se obtuvieron {len(offers)} ofertas calificadas para LATAM.")
        return offers
