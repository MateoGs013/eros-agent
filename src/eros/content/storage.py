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
            for col in ("dispatched_channels TEXT", "dispatched_at TEXT", "published_channels TEXT"):
                try:
                    await db.execute(f"ALTER TABLE content_posts ADD COLUMN {col}")
                except Exception:
                    pass
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

    async def claim_dispatch(self, post_id: str, channels: list[str], force: bool = False) -> tuple[str, list[str]]:
        """Reserva de forma atómica los canales a despachar de una publicación.

        Devuelve ("claimed", canales despachados) o un motivo de rechazo: ("missing", []),
        ("rejected", []), ("published", canales ya publicados) o
        ("already_dispatched", canales despachados esperando confirmación).
        Una publicación ya publicada en un canal puede despacharse a otro canal.
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute(
                "SELECT status, dispatched_channels, published_channels FROM content_posts WHERE id = ?", (post_id,)
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                await db.rollback()
                return "missing", []
            status, raw_dispatched, raw_published = row
            if status == ContentPostStatus.REJECTED.value:
                await db.rollback()
                return "rejected", []
            published = self._load_channels(raw_published)
            if any(c in published for c in channels):
                await db.rollback()
                return "published", published
            already = self._load_channels(raw_dispatched)
            if any(c in already for c in channels) and not force:
                await db.rollback()
                return "already_dispatched", already
            merged = sorted(set(already) | set(channels))
            new_status = status if status == ContentPostStatus.PUBLISHED.value else ContentPostStatus.APPROVED.value
            now_iso = datetime.now(timezone.utc).isoformat()
            await db.execute("""
                UPDATE content_posts SET status = ?, dispatched_channels = ?, dispatched_at = ?, updated_at = ?
                WHERE id = ?
            """, (new_status, json.dumps(merged), now_iso, now_iso, post_id))
            await db.commit()
            return "claimed", merged

    async def release_dispatch(self, post_id: str, channels: list[str], n8n_response: str | None = None) -> None:
        """Libera canales despachados que n8n no publicó (los ya publicados no se tocan)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute(
                "SELECT dispatched_channels, published_channels FROM content_posts WHERE id = ?", (post_id,)
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                await db.rollback()
                return
            published = self._load_channels(row[1])
            remaining = [c for c in self._load_channels(row[0]) if c not in channels or c in published]
            now_iso = datetime.now(timezone.utc).isoformat()
            await db.execute("""
                UPDATE content_posts SET dispatched_channels = ?,
                    dispatched_at = CASE WHEN ? = '[]' THEN NULL ELSE dispatched_at END,
                    n8n_response = COALESCE(?, n8n_response), updated_at = ?
                WHERE id = ?
            """, (json.dumps(remaining), json.dumps(remaining), n8n_response, now_iso, post_id))
            await db.commit()

    async def confirm_published(self, post_id: str, channels: list[str] | None, n8n_response: str | None = None) -> ContentPostStatus | None:
        """Registra la confirmación de n8n para uno o más canales.

        La publicación pasa a PUBLISHED cuando todos los canales despachados están confirmados.
        channels=None confirma todos los despachados. Devuelve el estado resultante.
        """
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute(
                "SELECT status, dispatched_channels, published_channels FROM content_posts WHERE id = ?", (post_id,)
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                await db.rollback()
                return None
            status, raw_dispatched, raw_published = row
            dispatched = self._load_channels(raw_dispatched)
            confirmed = dispatched if channels is None else channels
            published = sorted(set(self._load_channels(raw_published)) | set(confirmed))
            # Sin canales despachados registrados (p. ej. despachada antes de este cambio), confirma igual
            all_done = set(dispatched) <= set(published)
            new_status = ContentPostStatus.PUBLISHED.value if all_done else status
            now_iso = datetime.now(timezone.utc).isoformat()
            await db.execute("""
                UPDATE content_posts SET status = ?, published_channels = ?,
                    n8n_published_at = CASE WHEN ? = 'published' THEN COALESCE(n8n_published_at, ?) ELSE n8n_published_at END,
                    n8n_response = COALESCE(?, n8n_response), updated_at = ?
                WHERE id = ?
            """, (new_status, json.dumps(published), new_status, now_iso, n8n_response, now_iso, post_id))
            await db.commit()
            return ContentPostStatus(new_status)

    async def set_n8n_response(self, post_id: str, n8n_response: str) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE content_posts SET n8n_response = ?, updated_at = ? WHERE id = ?",
                (n8n_response, datetime.now(timezone.utc).isoformat(), post_id),
            )
            await db.commit()

    @staticmethod
    def _load_channels(raw: str | None) -> list[str]:
        try:
            value = json.loads(raw) if raw else []
            return [str(c) for c in value] if isinstance(value, list) else []
        except Exception:
            return []

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
            dispatched_channels=self._load_channels(row["dispatched_channels"]) if "dispatched_channels" in row.keys() else [],
            dispatched_at=row["dispatched_at"] if "dispatched_at" in row.keys() else None,
            published_channels=self._load_channels(row["published_channels"]) if "published_channels" in row.keys() else [],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
