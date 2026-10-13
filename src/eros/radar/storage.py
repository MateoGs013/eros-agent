import json
import logging
from datetime import datetime, timezone
import aiosqlite
from eros.config import get_settings
from .models import TrendItem, TrendSource, TrendStatus

logger = logging.getLogger(__name__)


class RadarStorage:
    """Almacén SQLite asíncrono para tendencias capturadas por TrendRadar."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(get_settings().db_file_path)

    async def init_db(self) -> None:
        """Crea la tabla de tendencias si no existe."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS trends (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL,
                    source TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    relevance_score INTEGER NOT NULL,
                    engineering_angle TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    detected_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'DISCOVERED',
                    post_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_trends_status ON trends(status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_trends_score ON trends(relevance_score)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_trends_detected ON trends(detected_at)")
            await db.commit()

    async def save_trend(self, trend: TrendItem) -> bool:
        """Inserta o actualiza una tendencia."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT id FROM trends WHERE id = ?", (trend.id,)) as cursor:
                exists = await cursor.fetchone() is not None

            tags_json = json.dumps(trend.tags)
            now_iso = datetime.now(timezone.utc).isoformat()

            if not exists:
                await db.execute("""
                    INSERT INTO trends (
                        id, title, url, source, summary,
                        relevance_score, engineering_angle, tags, detected_at,
                        status, post_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    trend.id, trend.title, trend.url, trend.source.value, trend.summary,
                    trend.relevance_score, trend.engineering_angle, tags_json, trend.detected_at,
                    trend.status.value, trend.post_id, now_iso, now_iso
                ))
            else:
                await db.execute("""
                    UPDATE trends SET
                        title = ?, url = ?, source = ?, summary = ?,
                        relevance_score = ?, engineering_angle = ?, tags = ?,
                        status = ?, post_id = ?, updated_at = ?
                    WHERE id = ?
                """, (
                    trend.title, trend.url, trend.source.value, trend.summary,
                    trend.relevance_score, trend.engineering_angle, tags_json,
                    trend.status.value, trend.post_id, now_iso, trend.id
                ))
            await db.commit()
            return True

    async def get_trends(
        self,
        status: TrendStatus | None = None,
        min_score: int | None = None,
        limit: int = 50,
    ) -> list[TrendItem]:
        """Obtiene las tendencias filtradas y ordenadas por puntuación y fecha."""
        query = "SELECT * FROM trends WHERE 1=1"
        params: list[object] = []

        if status:
            query += " AND status = ?"
            params.append(status.value)
        if min_score is not None:
            query += " AND relevance_score >= ?"
            params.append(min_score)

        query += " ORDER BY relevance_score DESC, detected_at DESC LIMIT ?"
        params.append(limit)

        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                results: list[TrendItem] = []
                for row in rows:
                    try:
                        tags = json.loads(row["tags"]) if row["tags"] else []
                    except Exception:
                        tags = []
                    results.append(TrendItem(
                        id=row["id"],
                        title=row["title"],
                        url=row["url"],
                        source=TrendSource(row["source"]),
                        summary=row["summary"],
                        relevance_score=row["relevance_score"],
                        engineering_angle=row["engineering_angle"],
                        tags=tags,
                        detected_at=row["detected_at"],
                        status=TrendStatus(row["status"]),
                        post_id=row["post_id"],
                    ))
                return results

    async def get_trend(self, id: str) -> TrendItem | None:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM trends WHERE id = ?", (id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                try:
                    tags = json.loads(row["tags"]) if row["tags"] else []
                except Exception:
                    tags = []
                return TrendItem(
                    id=row["id"],
                    title=row["title"],
                    url=row["url"],
                    source=TrendSource(row["source"]),
                    summary=row["summary"],
                    relevance_score=row["relevance_score"],
                    engineering_angle=row["engineering_angle"],
                    tags=tags,
                    detected_at=row["detected_at"],
                    status=TrendStatus(row["status"]),
                    post_id=row["post_id"],
                )

    async def update_status(self, id: str, status: TrendStatus, post_id: str | None = None) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            now_iso = datetime.now(timezone.utc).isoformat()
            if post_id is not None:
                await db.execute(
                    "UPDATE trends SET status = ?, post_id = ?, updated_at = ? WHERE id = ?",
                    (status.value, post_id, now_iso, id)
                )
            else:
                await db.execute(
                    "UPDATE trends SET status = ?, updated_at = ? WHERE id = ?",
                    (status.value, now_iso, id)
                )
            await db.commit()
            return True
