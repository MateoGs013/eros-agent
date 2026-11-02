import logging
from datetime import datetime, timezone
from typing import Any
import httpx
from eros.config import get_settings
from eros.content.models import PUBLISH_CHANNELS, ContentPostStatus
from eros.content.storage import ContentStorage

logger = logging.getLogger(__name__)


class ContentDispatcher:
    """Distribuidor que despacha publicaciones aprobadas al webhook de contenido de n8n.

    - Respeta el canal pedido (all, linkedin, twitter): manda `channel` y solo el texto
      de los canales pedidos. Dev.to no tiene publicación automática y se rechaza.
    - No republica un canal ya publicado ni lo REJECTED, ni vuelve a despachar un canal
      que espera confirmación.
    - No marca PUBLISHED al despachar: el callback de n8n confirma cada canal y la
      publicación queda PUBLISHED cuando todos los despachados están confirmados.
    - Manda N8N_WEBHOOK_SECRET en el header X-N8N-Secret.
    """

    def __init__(self, storage: ContentStorage | None = None):
        self.storage = storage or ContentStorage()
        self.settings = get_settings()

    @staticmethod
    def channels_for(channel: str) -> list[str]:
        return ["linkedin", "twitter"] if channel == "all" else [channel]

    async def publish_post(self, post_id: str, channel: str = "all", force: bool = False) -> dict[str, Any]:
        """Despacha la publicación a n8n por el canal pedido (o la aprueba localmente sin n8n).

        Errores con `error_code`: not_found, invalid_channel, already_published, rejected,
        already_dispatched, dispatch_failed, dispatch_unknown.
        """
        channel = (channel or "all").strip().lower()
        if channel == "devto":
            return {"ok": False, "error_code": "invalid_channel",
                    "error": "Dev.to no tiene publicación automática: copiá el artículo desde la publicación."}
        if channel not in PUBLISH_CHANNELS:
            return {"ok": False, "error_code": "invalid_channel",
                    "error": f"Canal inválido: '{channel}'. Opciones: {', '.join(PUBLISH_CHANNELS)}."}

        post = await self.storage.get_post(post_id)
        if not post:
            return {"ok": False, "error_code": "not_found", "error": f"Publicación {post_id} no encontrada"}
        if any(c in post.published_channels for c in self.channels_for(channel)):
            return {"ok": False, "error_code": "already_published",
                    "error": f"Ya se publicó en {', '.join(post.published_channels)}; no se republica."}
        if post.status == ContentPostStatus.REJECTED:
            return {"ok": False, "error_code": "rejected", "error": "La publicación fue rechazada; no se publica."}

        webhook_url = self.settings.n8n_webhook_url.strip()
        if not webhook_url:
            if post.status == ContentPostStatus.PUBLISHED:
                return {"ok": False, "error_code": "already_published", "error": "La publicación ya fue publicada; no se republica."}
            logger.info(f"N8N_WEBHOOK_URL no configurado. Marcando publicación {post_id} como APROBADA (modo local).")
            await self.storage.update_status(post_id, ContentPostStatus.APPROVED, n8n_response="Local approval: No N8N webhook configured")
            return {
                "ok": True,
                "status": "approved_local",
                "channel": channel,
                "message": "Publicación aprobada en base de datos. Para despacho automático a LinkedIn/Twitter/Dev.to, configurá N8N_WEBHOOK_URL en .env.",
                "post": post,
            }

        channels = self.channels_for(channel)
        claim, dispatched = await self.storage.claim_dispatch(post_id, channels, force=force)
        if claim != "claimed":
            errors = {
                "missing": ("not_found", f"Publicación {post_id} no encontrada"),
                "published": ("already_published", f"Ya se publicó en {', '.join(dispatched)}; no se republica."),
                "rejected": ("rejected", "La publicación fue rechazada; no se publica."),
                "already_dispatched": (
                    "already_dispatched",
                    f"Ya se despachó a {', '.join(dispatched)} y se espera la confirmación de n8n. "
                    "Para reenviar igual, usá force=true.",
                ),
            }
            code, msg = errors[claim]
            return {"ok": False, "error_code": code, "error": msg, "dispatched_channels": dispatched}

        now_iso = datetime.now(timezone.utc).isoformat()
        base_url = self.settings.public_base_url.rstrip("/")
        include = set(channels)
        linkedin_text = post.linkedin_text if "linkedin" in include else ""
        payload = {
            "event": "content.publish",
            "post_id": post.id,
            "channel": channel,
            "channels": channels,
            "title": post.title,
            "topic": post.topic,
            "pillar": post.pillar.value,
            "project_slug": post.project_slug,
            "hook": post.hook,
            "linkedin_text": linkedin_text,
            # Alias que lee el workflow de n8n
            "linkedin_post": linkedin_text,
            "first_comment": post.first_comment if "linkedin" in include else "",
            "twitter_thread": post.twitter_thread if "twitter" in include else [],
            "devto_article": None,
            "carousel_url": f"{base_url}/api/content/carousel/{post.id}/html",
            "carousel_print_url": f"{base_url}/api/content/carousel/{post.id}/html?auto_print=1",
            "slides_count": len(post.carousel_slides),
            "approved_at": now_iso,
            "callback_url": f"{base_url}/api/webhooks/n8n/callback",
        }
        headers = {"Idempotency-Key": f"publish-{post.id}-{channel}"}
        if self.settings.n8n_webhook_secret:
            headers["X-N8N-Secret"] = self.settings.n8n_webhook_secret

        logger.info(f"Despachando publicación {post_id} a n8n (canal: {channel}).")
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(webhook_url, json=payload, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            await self.storage.release_dispatch(post_id, channels)
            error_msg = f"Falla de conexión al despachar a n8n: {e}"
            logger.error(error_msg)
            return {"ok": False, "error_code": "dispatch_failed", "error": error_msg}
        except httpx.HTTPError as e:
            error_msg = f"n8n no respondió a tiempo; no se sabe si recibió la publicación: {e}"
            logger.error(error_msg)
            return {"ok": False, "error_code": "dispatch_unknown", "error": error_msg, "dispatched_channels": dispatched}

        resp_text = resp.text[:300]
        if resp.status_code in (200, 201, 202, 204):
            await self.storage.set_n8n_response(post_id, resp_text)
            return {
                "ok": True,
                # Despachada: n8n la recibió. Pasa a "published" cuando n8n confirma por el callback.
                "status": "dispatched",
                "channel": channel,
                "dispatched_channels": dispatched,
                "dispatched_at": now_iso,
                "n8n_status_code": resp.status_code,
                "n8n_response": resp_text,
            }

        await self.storage.release_dispatch(post_id, channels, n8n_response=resp_text)
        error_msg = f"n8n respondió con error HTTP {resp.status_code}: {resp.text[:200]}"
        logger.error(error_msg)
        return {"ok": False, "error_code": "dispatch_failed", "error": error_msg}
