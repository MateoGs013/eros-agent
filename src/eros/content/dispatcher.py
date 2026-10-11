import json
import logging
from datetime import datetime, timezone
from typing import Any
import httpx
from eros.config import get_settings
from eros.content.models import ContentPost, ContentPostStatus
from eros.content.storage import ContentStorage

logger = logging.getLogger(__name__)


class ContentDispatcher:
    """Distribuidor que despacha publicaciones aprobadas al webhook de n8n."""

    def __init__(self, storage: ContentStorage | None = None):
        self.storage = storage or ContentStorage()
        self.settings = get_settings()

    async def publish_post(self, post_id: str) -> dict[str, Any]:
        """Marca una publicación como aprobada y la envía a n8n si el webhook está configurado."""
        post = await self.storage.get_post(post_id)
        if not post:
            return {"ok": False, "error": f"Publicación {post_id} no encontrada"}

        webhook_url = self.settings.n8n_webhook_url.strip()
        now_iso = datetime.now(timezone.utc).isoformat()

        payload = {
            "event": "content.publish",
            "post_id": post.id,
            "title": post.title,
            "topic": post.topic,
            "pillar": post.pillar.value,
            "project_slug": post.project_slug,
            "hook": post.hook,
            "linkedin_text": post.linkedin_text,
            "first_comment": post.first_comment,
            "twitter_thread": post.twitter_thread,
            "devto_article": {
                "title": post.devto.title,
                "tags": post.devto.tags,
                "markdown_body": post.devto.markdown_body,
            },
            "carousel_url": f"https://eros.mateogs.tech/api/content/carousel/{post.id}/html",
            "carousel_print_url": f"https://eros.mateogs.tech/api/content/carousel/{post.id}/html?auto_print=1",
            "slides_count": len(post.carousel_slides),
            "approved_at": now_iso,
        }

        if not webhook_url:
            logger.info(f"N8N_WEBHOOK_URL no configurado. Marcando publicación {post_id} como APROBADA (modo local).")
            await self.storage.update_status(post_id, ContentPostStatus.APPROVED, n8n_response="Local approval: No N8N webhook configured")
            return {
                "ok": True,
                "status": "approved_local",
                "message": "Publicación aprobada en base de datos. Para despacho automático a LinkedIn/Twitter/Dev.to, configurá N8N_WEBHOOK_URL en .env.",
                "post": post,
            }

        logger.info(f"Despachando publicación {post_id} a n8n: {webhook_url}")
        async with httpx.AsyncClient(timeout=25.0) as client:
            try:
                resp = await client.post(webhook_url, json=payload)
                if resp.status_code in [200, 201, 202, 204]:
                    resp_text = resp.text[:300]
                    await self.storage.update_status(post_id, ContentPostStatus.PUBLISHED, n8n_response=resp_text)
                    return {
                        "ok": True,
                        "status": "published",
                        "n8n_status_code": resp.status_code,
                        "n8n_response": resp_text,
                    }
                else:
                    error_msg = f"n8n respondió con error HTTP {resp.status_code}: {resp.text[:200]}"
                    logger.error(error_msg)
                    return {"ok": False, "error": error_msg}
            except Exception as e:
                error_msg = f"Falla de conexión al despachar a n8n: {str(e)}"
                logger.error(error_msg)
                return {"ok": False, "error": error_msg}
