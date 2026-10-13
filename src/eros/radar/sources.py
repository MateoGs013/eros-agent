import asyncio
import logging
from typing import Any
import httpx
from .models import TrendSource

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": "Eros-TrendRadar/1.0 (+https://mateogs.tech)",
    "Accept": "application/json",
}


class HackerNewsSource:
    """Extrae las historias más relevantes de Hacker News vía API oficial de Firebase."""

    async def fetch(self, limit: int = 15) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=10.0, headers=DEFAULT_HEADERS) as client:
                res = await client.get("https://hacker-news.firebaseio.com/v0/topstories.json")
                if res.status_code != 200:
                    return results
                story_ids = res.json()[:limit]

                async def get_story(sid: int) -> dict[str, Any] | None:
                    try:
                        r = await client.get(f"https://hacker-news.firebaseio.com/v0/item/{sid}.json")
                        if r.status_code == 200:
                            data = r.json()
                            if data and data.get("type") == "story" and data.get("title"):
                                return {
                                    "id": f"hn_{data['id']}",
                                    "title": data.get("title", ""),
                                    "url": data.get("url") or f"https://news.ycombinator.com/item?id={sid}",
                                    "source": TrendSource.HACKER_NEWS,
                                    "summary": f"Historia destacada en Hacker News con {data.get('score', 0)} puntos y {data.get('descendants', 0)} comentarios.",
                                    "tags": ["hackernews", "tech", "discussion"],
                                }
                    except Exception:
                        return None
                    return None

                tasks = [get_story(sid) for sid in story_ids]
                items = await asyncio.gather(*tasks)
                results = [item for item in items if item is not None]
        except Exception as e:
            logger.warning(f"Error al consultar Hacker News: {e}")
        return results


class DevToSource:
    """Extrae los artículos técnicos con mayor interacción de Dev.to."""

    async def fetch(self, limit: int = 15) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=10.0, headers=DEFAULT_HEADERS) as client:
                res = await client.get(f"https://dev.to/api/articles?top=1&per_page={limit}")
                if res.status_code != 200:
                    return results
                data = res.json()
                for item in data:
                    title = item.get("title")
                    url = item.get("url")
                    if title and url:
                        tags = item.get("tag_list") or []
                        results.append({
                            "id": f"devto_{item.get('id')}",
                            "title": title,
                            "url": url,
                            "source": TrendSource.DEVTO,
                            "summary": item.get("description") or f"Publicación técnica destacada en Dev.to por {item.get('user', {}).get('name', 'autor')}.",
                            "tags": [t.lower() for t in tags if isinstance(t, str)],
                        })
        except Exception as e:
            logger.warning(f"Error al consultar Dev.to: {e}")
        return results


class GitHubTrendingSource:
    """Extrae repositorios y proyectos con alto crecimiento reciente en GitHub."""

    async def fetch(self, limit: int = 10) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=12.0, headers=DEFAULT_HEADERS) as client:
                query = "topic:artificial-intelligence+topic:database+stars:>200"
                url = f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc&per_page={limit}"
                res = await client.get(url)
                if res.status_code == 200:
                    data = res.json()
                    for item in data.get("items", []):
                        name = item.get("full_name")
                        repo_url = item.get("html_url")
                        if name and repo_url:
                            topics = item.get("topics") or []
                            results.append({
                                "id": f"gh_{item.get('id')}",
                                "title": f"{name}: {item.get('description') or 'Proyecto open source'}",
                                "url": repo_url,
                                "source": TrendSource.GITHUB,
                                "summary": f"Repositorio con {item.get('stargazers_count', 0)} estrellas. Lenguaje principal: {item.get('language') or 'Políglota'}.",
                                "tags": [t.lower() for t in topics[:5]] + [str(item.get("language") or "").lower()],
                            })
        except Exception as e:
            logger.warning(f"Error al consultar GitHub: {e}")
        return results
