import os
import re
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
import httpx

from eros.api import app, content_storage, content_dispatcher
from eros.content.models import (
    ContentPost,
    ContentPostStatus,
    ContentPillar,
    SlideItem,
    DevToArticle,
)


class TestApiContentEndpoints(unittest.IsolatedAsyncioTestCase):
    """Auditoría de integración para los endpoints HTTP de contenido en FastAPI."""

    async def asyncSetUp(self):
        os.environ["EROS_API_KEY"] = "eros_dev_sec_7f9b8c2d1e0a4f5b6c7d8e9f0a1b2c3d"
        from eros.config import get_settings
        get_settings.cache_clear()
        self.emoji_pattern = re.compile(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]')
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_api_eros.db")
        content_storage.db_path = self.db_path
        await content_storage.init_db()

        self.post = ContentPost(
            id="post_test_api_1",
            title="Prueba de API Contenido",
            topic="Test Topic",
            pillar=ContentPillar.ARCHITECTURE,
            project_slug="portfolio",
            hook="Hook técnico sin rodeos.",
            linkedin_text="Post de LinkedIn técnico.\n\n• Punto A.\n• Punto B.\n\n#webdev",
            first_comment="Enlace al repo: https://mateogs.tech",
            twitter_thread=["1/2 Tweet uno.", "2/2 Tweet dos."],
            devto=DevToArticle(
                title="Prueba de API Contenido",
                tags=["webdev", "architecture"],
                markdown_body="# Contenido Devto",
            ),
            carousel_slides=[
                SlideItem(
                    index=1,
                    title="Slide Uno",
                    subtitle="Subtitulo Uno",
                    bullets=["Bullet 1", "Bullet 2"],
                    metric_badge="100%",
                    code_snippet=None,
                    footer="mateogs.tech",
                )
            ],
            status=ContentPostStatus.DRAFT,
        )
        await content_storage.save_post(self.post)

    async def asyncTearDown(self):
        self.tmp_dir.cleanup()
        os.environ.pop("EROS_API_KEY", None)
        from eros.config import get_settings
        get_settings.cache_clear()

    async def test_01_list_and_get_endpoints(self):
        """Verifica GET /api/content/posts y GET /api/content/posts/{id}."""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": f"Bearer {app.dependency_overrides.get('api_key', 'eros_dev_sec_7f9b8c2d1e0a4f5b6c7d8e9f0a1b2c3d')}"}
            
            # Listar posts
            res = await client.get("/api/content/posts", headers=headers)
            self.assertEqual(res.status_code, 200)
            data = res.json()
            self.assertGreaterEqual(data["count"], 1)

            # Obtener post específico
            res_single = await client.get("/api/content/posts/post_test_api_1", headers=headers)
            self.assertEqual(res_single.status_code, 200)
            post_data = res_single.json()["data"]
            self.assertEqual(post_data["id"], "post_test_api_1")

    async def test_02_carousel_html_render(self):
        """Verifica GET /api/content/carousel/{id}/html con auth y que no tenga emojis."""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            # Sin autenticacion debe retornar 401
            res_unauth = await client.get("/api/content/carousel/post_test_api_1/html")
            self.assertEqual(res_unauth.status_code, 401)

            # Con autenticacion valida debe retornar 200
            headers = {"Authorization": "Bearer eros_dev_sec_7f9b8c2d1e0a4f5b6c7d8e9f0a1b2c3d"}
            res = await client.get("/api/content/carousel/post_test_api_1/html", headers=headers)
            self.assertEqual(res.status_code, 200)
            html = res.text
            self.assertIn("Slide Uno", html)
            self.assertIn("<!DOCTYPE html>", html)

            # Assert ZERO emojis
            emojis = self.emoji_pattern.findall(html)
            self.assertEqual(len(emojis), 0, f"Se encontraron emojis en HTML del carrusel: {emojis}")

    async def test_03_status_update_and_publish(self):
        """Verifica PATCH /api/content/posts/{id}/status y POST /api/content/posts/{id}/publish."""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": "Bearer eros_dev_sec_7f9b8c2d1e0a4f5b6c7d8e9f0a1b2c3d"}

            # Actualizar status a rejected
            res_patch = await client.patch(
                "/api/content/posts/post_test_api_1/status",
                json={"status": "rejected"},
                headers=headers,
            )
            self.assertEqual(res_patch.status_code, 200)
            self.assertEqual(res_patch.json()["new_status"], "rejected")

            # Publicar (modo local sin webhook n8n configurado)
            with patch.object(content_dispatcher.settings, "n8n_webhook_url", ""):
                res_pub = await client.post(
                    "/api/content/posts/post_test_api_1/publish",
                    headers=headers,
                )
                self.assertEqual(res_pub.status_code, 200)
                self.assertTrue(res_pub.json()["ok"])
                self.assertEqual(res_pub.json()["status"], "approved_local")

    async def test_04_n8n_webhook_callback(self):
        """Verifica POST /api/webhooks/n8n/callback con y sin auth."""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {"post_id": "post_test_api_1", "status": "published", "details": {"ok": True}}

            # 1. Con secret inválido debe rechazar con 401
            res_bad = await client.post(
                "/api/webhooks/n8n/callback",
                json=payload,
                headers={"X-N8N-Secret": "invalid_secret"},
            )
            self.assertEqual(res_bad.status_code, 401)

            # 2. Con secret válido vía X-Eros-Key o X-N8N-Secret
            res_ok = await client.post(
                "/api/webhooks/n8n/callback",
                json=payload,
                headers={"X-Eros-Key": "eros_dev_sec_7f9b8c2d1e0a4f5b6c7d8e9f0a1b2c3d"},
            )
            self.assertEqual(res_ok.status_code, 200)
            self.assertTrue(res_ok.json()["ok"])


if __name__ == "__main__":
    unittest.main()
