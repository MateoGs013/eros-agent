import logging
import httpx
from bs4 import BeautifulSoup
from eros.hunter.filters import check_job_qualification
from eros.hunter.sources.base import BaseJobSource
from eros.models import JobOffer

logger = logging.getLogger(__name__)


class GetOnBoardSource(BaseJobSource):
    """Conector para Get on Board (puestos tech en LATAM y remoto)."""

    @property
    def name(self) -> str:
        return "getonboard"

    async def fetch_jobs(self) -> list[JobOffer]:
        url = "https://www.getonbrd.com/api/v0/categories/programming/jobs?per_page=30"
        offers = []

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; ErosJobHunter/1.0; +https://mateogs.tech)",
            "Accept": "application/json"
        }

        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(f"Get on Board respondió con status {resp.status_code}")
                    return []

                payload = resp.json()
                items = payload.get("data", [])

                for item in items:
                    attrs = item.get("attributes", {})
                    job_id_ext = str(item.get("id"))
                    title = attrs.get("title", "")
                    
                    # Limpiar descripción HTML
                    desc_html = attrs.get("description", "")
                    clean_desc = BeautifulSoup(desc_html, "html.parser").get_text(separator="\n").strip()

                    # Tags / Tecnologías
                    tags_raw = attrs.get("tags", {}).get("data", [])
                    tags = [t.get("attributes", {}).get("name") for t in tags_raw if t.get("attributes", {}).get("name")]

                    country = attrs.get("country") or "LATAM / Remoto"

                    # Pre-filtro de calificación
                    qual = check_job_qualification(
                        title=title,
                        description=clean_desc,
                        country=country,
                        tags=tags,
                    )
                    if not qual.qualified:
                        continue

                    # Compañía
                    company_data = attrs.get("company", {}).get("data", {})
                    company_name = company_data.get("attributes", {}).get("name", "Empresa Confidencial")

                    # Salario
                    min_sal = attrs.get("min_salary")
                    max_sal = attrs.get("max_salary")
                    currency = attrs.get("currency", "USD")
                    salary_str = None
                    if min_sal and max_sal:
                        salary_str = f"{currency} {min_sal} - {max_sal}"
                    elif min_sal:
                        salary_str = f"{currency} {min_sal}+"

                    # Enlace
                    links = item.get("links", {})
                    public_url = links.get("public_url") or f"https://www.getonbrd.com/jobs/{job_id_ext}"

                    job_offer = JobOffer(
                        id=self.generate_job_id(job_id_ext),
                        source=self.name,
                        external_id=job_id_ext,
                        title=title,
                        company=company_name,
                        url=public_url,
                        description=clean_desc[:3000],
                        tags=tags,
                        salary=salary_str,
                        country=country,
                        is_remote=bool(attrs.get("remote", True)),
                        published_at=str(attrs.get("published_at")) if attrs.get("published_at") else None
                    )
                    offers.append(job_offer)

            except Exception as e:
                logger.error(f"Error extrayendo ofertas de Get on Board: {e}")

        logger.info(f"Get on Board: {len(offers)} vacantes filtradas y parseadas.")
        return offers
