import asyncio
from datetime import datetime, timezone
import hashlib
import logging
from typing import Any
from .models import TrendItem, TrendSource, TrendStatus
from .sources import HackerNewsSource, DevToSource, GitHubTrendingSource
from .storage import RadarStorage

logger = logging.getLogger(__name__)

STACK_KEYWORDS_TIER1 = [
    "pgvector", "postgresql", "postgres", "rag", "agent", "agents",
    "fastapi", "vue", "nuxt", "prisma", "typescript", "python"
]
STACK_KEYWORDS_TIER2 = [
    "database", "docker", "api", "architecture", "performance", "sql",
    "system design", "open source", "llm", "vector", "tailwind", "redis"
]
STACK_KEYWORDS_TIER3 = [
    "frontend", "backend", "devops", "fullstack", "cache", "benchmark",
    "latency", "acid", "microservices", "vite"
]


class RadarEngine:
    """Motor de exploración y evaluación técnica de tendencias de ingeniería."""

    def __init__(self, storage: RadarStorage | None = None):
        self.storage = storage or RadarStorage()
        self.hn_source = HackerNewsSource()
        self.devto_source = DevToSource()
        self.github_source = GitHubTrendingSource()

    def calculate_relevance(self, title: str, summary: str, tags: list[str]) -> tuple[int, list[str]]:
        corpus = f"{title.lower()} {summary.lower()} {' '.join(tags).lower()}"
        score = 25
        matched_tags: list[str] = []

        for kw in STACK_KEYWORDS_TIER1:
            if kw in corpus:
                score += 25
                matched_tags.append(kw)

        for kw in STACK_KEYWORDS_TIER2:
            if kw in corpus:
                score += 15
                if kw not in matched_tags:
                    matched_tags.append(kw)

        for kw in STACK_KEYWORDS_TIER3:
            if kw in corpus:
                score += 10
                if kw not in matched_tags:
                    matched_tags.append(kw)

        final_score = max(20, min(98, score))
        return final_score, matched_tags[:6]

    def formulate_engineering_angle(self, title: str, matched_tags: list[str]) -> str:
        tags_set = set(matched_tags)
        if tags_set.intersection({"pgvector", "postgresql", "postgres", "database", "sql", "vector"}):
            return "Persistencia relacional y vectores densos en PostgreSQL 17: análisis de trade-offs frente a bases vectoriales aisladas y control de latencia en un solo nodo."
        if tags_set.intersection({"agent", "agents", "rag", "fastapi", "llm"}):
            return "Arquitectura de agentes autónomos satélites con FastAPI y streaming: determinismo en extracción estructurada y mitigación de fallos en producción."
        if tags_set.intersection({"vue", "nuxt", "frontend", "typescript", "performance", "vite"}):
            return "Frontend de alta precisión y densidad de datos: optimización de Core Web Vitals (Lighthouse 98+), renderizado híbrido y ergonomía sin bloating ornamental."
        if tags_set.intersection({"docker", "devops", "architecture", "system design"}):
            return "Trade-offs de infraestructura moderna: simplicidad operativa en VPS vs sobre-ingeniería de microservicios para proyectos en escala real."
        return f"Desglose crítico desde la perspectiva de desarrollo Full Stack: implicaciones prácticas, costos operativos y aplicabilidad en proyectos de ingeniería de software."

    async def scan(self, limit_per_source: int = 15) -> list[TrendItem]:
        """Escanea todas las fuentes en paralelo, evalúa relevancia y persiste novedades."""
        await self.storage.init_db()

        hn_task = self.hn_source.fetch(limit=limit_per_source)
        devto_task = self.devto_source.fetch(limit=limit_per_source)
        gh_task = self.github_source.fetch(limit=10)

        raw_results = await asyncio.gather(hn_task, devto_task, gh_task, return_exceptions=True)

        all_raw_items: list[dict[str, Any]] = []
        for res in raw_results:
            if isinstance(res, list):
                all_raw_items.extend(res)

        now_iso = datetime.now(timezone.utc).isoformat()
        discovered_trends: list[TrendItem] = []

        for item in all_raw_items:
            title = item.get("title", "").strip()
            url = item.get("url", "").strip()
            if not title or not url:
                continue

            raw_tags = item.get("tags") or []
            summary = item.get("summary", "")
            source = item.get("source", TrendSource.TECH_RSS)

            score, matched_tags = self.calculate_relevance(title, summary, raw_tags)
            angle = self.formulate_engineering_angle(title, matched_tags)
            all_tags = list(dict.fromkeys(matched_tags + [t.lower() for t in raw_tags]))[:6]

            item_id = item.get("id") or f"trend_{hashlib.md5(url.encode()).hexdigest()[:12]}"

            trend = TrendItem(
                id=item_id,
                title=title,
                url=url,
                source=source,
                summary=summary,
                relevance_score=score,
                engineering_angle=angle,
                tags=all_tags,
                detected_at=now_iso,
                status=TrendStatus.DISCOVERED,
            )

            await self.storage.save_trend(trend)
            discovered_trends.append(trend)

        discovered_trends.sort(key=lambda t: t.relevance_score, reverse=True)
        return discovered_trends
