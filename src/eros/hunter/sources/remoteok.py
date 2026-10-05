import logging
import httpx
from bs4 import BeautifulSoup
from eros.hunter.sources.base import BaseJobSource
from eros.models import JobOffer

logger = logging.getLogger(__name__)


class RemoteOKSource(BaseJobSource):
    """Conector para RemoteOK (ofertas remotas internacionales en USD)."""

    @property
    def name(self) -> str:
        return "remoteok"

    async def fetch_jobs(self) -> list[JobOffer]:
        url = "https://remoteok.com/api?tag=dev"
        offers = []

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ErosAgent/1.0",
            "Accept": "application/json"
        }

        async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
            try:
                resp = await client.get(url)
                if resp.status_code != 200:
                    logger.warning(f"RemoteOK respondió con status {resp.status_code}")
                    return []

                items = resp.json()
                # El primer elemento suele ser legal notice
                if items and isinstance(items, list) and not isinstance(items[0], dict):
                    items = items[1:]

                for item in items:
                    if not isinstance(item, dict):
                        continue

                    # Ignorar banner o elementos no vacante
                    if "position" not in item:
                        continue

                    job_id_ext = str(item.get("id"))
                    title = item.get("position", "")
                    tags = item.get("tags", [])

                    # Filtrar por foco de frontend / fullstack / web / javascript / typescript
                    tags_lower = [t.lower() for t in tags]
                    title_lower = title.lower()

                    relevant_keywords = ["frontend", "front-end", "fullstack", "full stack", "vue", "react", "typescript", "javascript", "web", "node"]
                    is_relevant = any(k in title_lower for k in relevant_keywords) or any(k in tags_lower for k in relevant_keywords)
                    
                    if not is_relevant:
                        continue

                    # Descripción
                    desc_html = item.get("description", "")
                    clean_desc = BeautifulSoup(desc_html, "html.parser").get_text(separator="\n").strip()

                    # Salario
                    sal_min = item.get("salary_min")
                    sal_max = item.get("salary_max")
                    salary_str = None
                    if sal_min and sal_max:
                        salary_str = f"USD {sal_min:,} - {sal_max:,}/yr"
                    elif sal_min:
                        salary_str = f"USD {sal_min:,}+/yr"

                    public_url = item.get("url") or f"https://remoteok.com/remote-jobs/{job_id_ext}"

                    job_offer = JobOffer(
                        id=self.generate_job_id(job_id_ext),
                        source=self.name,
                        external_id=job_id_ext,
                        title=title,
                        company=item.get("company", "Empresa Remota"),
                        url=public_url,
                        description=clean_desc[:3000],
                        tags=tags,
                        salary=salary_str,
                        country=item.get("location") or "Worldwide / Remoto",
                        is_remote=True,
                        published_at=item.get("date")
                    )
                    offers.append(job_offer)

                    if len(offers) >= 20:  # Límite por corrida para no saturar
                        break

            except Exception as e:
                logger.error(f"Error extrayendo ofertas de RemoteOK: {e}")

        logger.info(f"RemoteOK: {len(offers)} vacantes filtradas y parseadas.")
        return offers
