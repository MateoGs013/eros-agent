import logging
import httpx
from bs4 import BeautifulSoup
from eros.hunter.sources.base import BaseJobSource
from eros.models import JobOffer

logger = logging.getLogger(__name__)


class HackerNewsHiringSource(BaseJobSource):
    """Conector para el hilo mensual 'Ask HN: Who is hiring?' (startups directas)."""

    @property
    def name(self) -> str:
        return "hackernews"

    async def fetch_jobs(self) -> list[JobOffer]:
        offers = []
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                # 1. Buscar el post más reciente de 'who is hiring'
                search_url = "https://hn.algolia.com/api/v1/search?tags=story,author_whoishiring&query=who%20is%20hiring&hitsPerPage=1"
                resp = await client.get(search_url)
                if resp.status_code != 200:
                    return []

                stories = resp.json().get("hits", [])
                if not stories:
                    return []

                latest_story_id = stories[0].get("objectID")
                story_title = stories[0].get("title", "Ask HN: Who is hiring?")

                # 2. Obtener comentarios del post
                comments_url = f"https://hn.algolia.com/api/v1/search?tags=comment,story_{latest_story_id}&hitsPerPage=40"
                c_resp = await client.get(comments_url)
                if c_resp.status_code != 200:
                    return []

                comments = c_resp.json().get("hits", [])

                for comment in comments:
                    c_id = comment.get("objectID")
                    raw_html = comment.get("comment_text", "")
                    if not raw_html:
                        continue

                    text = BeautifulSoup(raw_html, "html.parser").get_text(separator="\n").strip()
                    lines = [line.strip() for line in text.split("\n") if line.strip()]
                    if not lines:
                        continue

                    header = lines[0]
                    # Solo ofertas remotas
                    if "remote" not in header.lower() and "remote" not in text.lower():
                        continue

                    # Filtrar por relevancia técnica
                    text_lower = text.lower()
                    if not any(k in text_lower for k in ["frontend", "front-end", "fullstack", "full stack", "vue", "react", "typescript", "javascript", "web"]):
                        continue

                    # Extraer compañía y título aproximados del encabezado "Company | Role | Location | Remote"
                    parts = [p.strip() for p in header.split("|")]
                    company = parts[0] if len(parts) >= 1 else "Startup (Hacker News)"
                    role = parts[1] if len(parts) >= 2 else "Software Engineer"

                    hn_url = f"https://news.ycombinator.com/item?id={c_id}"

                    job_offer = JobOffer(
                        id=self.generate_job_id(str(c_id)),
                        source=self.name,
                        external_id=str(c_id),
                        title=f"{role} @ {company}",
                        company=company,
                        url=hn_url,
                        description=text[:3000],
                        tags=["remote", "startup", "hacker-news"],
                        salary=None,
                        country="Remoto",
                        is_remote=True,
                        published_at=comment.get("created_at")
                    )
                    offers.append(job_offer)

                    if len(offers) >= 15:
                        break

            except Exception as e:
                logger.error(f"Error procesando Hacker News Hiring: {e}")

        logger.info(f"Hacker News: {len(offers)} vacantes remotas encontradas.")
        return offers
