import json
import logging
from datetime import datetime, timezone
import aiosqlite
from eros.config import get_settings
from eros.content.models import (
    ContentPost,
    ContentPostStatus,
    ContentPillar,
    SlideItem,
    DevToArticle,
)

logger = logging.getLogger(__name__)


class ContentStorage:
    """Almacén SQLite asíncrono para publicaciones, carousels e historial de distribución."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(get_settings().db_file_path)

    async def init_db(self) -> None:
        """Crea la tabla de publicaciones de contenido si no existe."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA busy_timeout=5000;")
            await db.execute("PRAGMA synchronous=NORMAL;")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS content_posts (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    pillar TEXT NOT NULL,
                    project_slug TEXT,
                    hook TEXT NOT NULL,
                    linkedin_text TEXT NOT NULL,
                    first_comment TEXT NOT NULL,
                    twitter_thread TEXT NOT NULL,
                    devto_title TEXT NOT NULL,
                    devto_tags TEXT NOT NULL,
                    devto_markdown TEXT NOT NULL,
                    carousel_slides TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    n8n_published_at TEXT,
                    n8n_response TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_content_status ON content_posts(status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_content_created ON content_posts(created_at)")
            await db.commit()

    async def save_post(self, post: ContentPost) -> bool:
        """Inserta o actualiza una publicación."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT id FROM content_posts WHERE id = ?", (post.id,)) as cursor:
                exists = await cursor.fetchone() is not None

            twitter_json = json.dumps(post.twitter_thread)
            devto_tags_json = json.dumps(post.devto.tags)
            slides_json = json.dumps([s.model_dump() for s in post.carousel_slides])
            now_iso = datetime.now(timezone.utc).isoformat()

            if not exists:
                await db.execute("""
                    INSERT INTO content_posts (
                        id, title, topic, pillar, project_slug, hook,
                        linkedin_text, first_comment, twitter_thread,
                        devto_title, devto_tags, devto_markdown,
                        carousel_slides, status, n8n_published_at, n8n_response,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    post.id, post.title, post.topic, post.pillar.value, post.project_slug, post.hook,
                    post.linkedin_text, post.first_comment, twitter_json,
                    post.devto.title, devto_tags_json, post.devto.markdown_body,
                    slides_json, post.status.value, post.n8n_published_at, post.n8n_response,
                    post.created_at, now_iso
                ))
            else:
                await db.execute("""
                    UPDATE content_posts SET
                        title = ?, topic = ?, pillar = ?, project_slug = ?, hook = ?,
                        linkedin_text = ?, first_comment = ?, twitter_thread = ?,
                        devto_title = ?, devto_tags = ?, devto_markdown = ?,
                        carousel_slides = ?, status = ?, n8n_published_at = ?,
                        n8n_response = ?, updated_at = ?
                    WHERE id = ?
                """, (
                    post.title, post.topic, post.pillar.value, post.project_slug, post.hook,
                    post.linkedin_text, post.first_comment, twitter_json,
                    post.devto.title, devto_tags_json, post.devto.markdown_body,
                    slides_json, post.status.value, post.n8n_published_at,
                    post.n8n_response, now_iso, post.id
                ))
            await db.commit()
            return not exists

    async def get_post(self, post_id: str) -> ContentPost | None:
        """Obtiene una publicación por su ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM content_posts WHERE id = ?", (post_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                return self._row_to_post(row)

    async def list_posts(self, status: ContentPostStatus | None = None, limit: int = 50) -> list[ContentPost]:
        """Lista publicaciones filtradas opcionalmente por estado."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if status:
                query = "SELECT * FROM content_posts WHERE status = ? ORDER BY created_at DESC LIMIT ?"
                params = (status.value, limit)
            else:
                query = "SELECT * FROM content_posts ORDER BY created_at DESC LIMIT ?"
                params = (limit,)

            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_post(r) for r in rows]

    async def update_status(
        self,
        post_id: str,
        status: ContentPostStatus,
        n8n_response: str | None = None
    ) -> bool:
        """Actualiza el estado de una publicación y registra timestamp si fue publicada."""
        async with aiosqlite.connect(self.db_path) as db:
            now_iso = datetime.now(timezone.utc).isoformat()
            published_at = now_iso if status == ContentPostStatus.PUBLISHED else None

            if published_at:
                await db.execute("""
                    UPDATE content_posts SET
                        status = ?, n8n_published_at = ?, n8n_response = ?, updated_at = ?
                    WHERE id = ?
                """, (status.value, published_at, n8n_response, now_iso, post_id))
            else:
                await db.execute("""
                    UPDATE content_posts SET
                        status = ?, updated_at = ?
                    WHERE id = ?
                """, (status.value, now_iso, post_id))

            await db.commit()
            return True

    async def delete_post(self, post_id: str) -> bool:
        """Elimina una publicación."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM content_posts WHERE id = ?", (post_id,))
            await db.commit()
            return True

    def _row_to_post(self, row: aiosqlite.Row) -> ContentPost:
        """Mapea una fila de SQLite a la instancia de ContentPost."""
        try:
            twitter_thread = json.loads(row["twitter_thread"])
        except Exception:
            twitter_thread = []

        try:
            devto_tags = json.loads(row["devto_tags"])
        except Exception:
            devto_tags = []

        try:
            slides_raw = json.loads(row["carousel_slides"])
            carousel_slides = [SlideItem(**s) for s in slides_raw]
        except Exception:
            carousel_slides = []

        devto = DevToArticle(
            title=row["devto_title"],
            tags=devto_tags,
            markdown_body=row["devto_markdown"],
        )

        return ContentPost(
            id=row["id"],
            title=row["title"],
            topic=row["topic"],
            pillar=ContentPillar(row["pillar"]),
            project_slug=row["project_slug"],
            hook=row["hook"],
            linkedin_text=row["linkedin_text"],
            first_comment=row["first_comment"],
            twitter_thread=twitter_thread,
            devto=devto,
            carousel_slides=carousel_slides,
            status=ContentPostStatus(row["status"]),
            n8n_published_at=row["n8n_published_at"],
            n8n_response=row["n8n_response"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
