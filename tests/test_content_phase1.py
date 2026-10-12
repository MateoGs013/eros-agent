import asyncio
import os
import re
import unittest
import tempfile
import json
from unittest.mock import AsyncMock, patch

from eros.content.models import (
    ContentPost,
    ContentPostStatus,
    ContentPillar,
    SlideItem,
    DevToArticle,
    ContentGenerateRequest,
)
from eros.content.storage import ContentStorage
from eros.content.carousel import CarouselRenderer
from eros.content.generator import ContentGenerator
from eros.content.dispatcher import ContentDispatcher


class TestPhase1ContentAudit(unittest.IsolatedAsyncioTestCase):
    """Auditoría exhaustiva de la Fase 1: Motor de Contenido de Eros."""

    def setUp(self):
        self.emoji_pattern = re.compile(r'[\U00010000-\U0010ffff]|[\u2600-\u27bf]')
        self.sample_slides = [
            SlideItem(
                index=1,
                title="Arquitectura de Alto Rendimiento",
                subtitle="Lecciones aprendidas en producción",
                bullets=["Latencia reducida a 45ms", "Cero re-renders innecesarios"],
                metric_badge="99/100 Lighthouse",
                code_snippet=None,
                footer="Mateo Sonzogni · mateogs.tech",
            ),
            SlideItem(
                index=2,
                title="El Cuello de Botella Inicial",
                subtitle="Trade-offs y problemas detectados",
                bullets=["Llamadas síncronas bloqueantes", "Payloads no comprimidos"],
                metric_badge=None,
                code_snippet="const bottleneck = await fetchAllSync();",
                footer="Problema en producción",
            ),
        ]
        self.sample_post = ContentPost(
            id="test_post_001",
            title="Optimización Extrema de Latencia Frontend",
            topic="Optimización de rendimiento",
            pillar=ContentPillar.PERFORMANCE_OPTIMIZATION,
            project_slug="portfolio",
            hook="Reducir latencia de 800ms a 45ms no requirió reescribir todo, sino entender el critical path.",
            linkedin_text="Reducir latencia de 800ms a 45ms no requirió reescribir todo.\n\n• Análisis de cascada de red.\n• Prefetching inteligente.\n\n#webdev #frontend #performance",
            first_comment="Pueden ver la arquitectura en vivo en https://mateogs.tech",
            twitter_thread=[
                "1/3 Reducir latencia en frontend: aquí los aprendizajes reales.",
                "2/3 El problema era la cascada de llamadas bloqueantes.",
                "3/3 Solución: prefetching selectivo y compresión Brotli.",
            ],
            devto=DevToArticle(
                title="Optimización Extrema de Latencia Frontend",
                tags=["webdev", "performance", "vue", "architecture"],
                markdown_body="# Optimización Extrema de Latencia Frontend\n\nDetalles técnicos...",
            ),
            carousel_slides=self.sample_slides,
            status=ContentPostStatus.DRAFT,
        )

    def test_01_models_integrity(self):
        """Valida que los modelos tipados serialicen y deserialicen fielmente."""
        post_dict = self.sample_post.model_dump()
        reconstructed = ContentPost.model_validate(post_dict)
        self.assertEqual(reconstructed.id, self.sample_post.id)
        self.assertEqual(len(reconstructed.carousel_slides), 2)
        self.assertEqual(reconstructed.pillar, ContentPillar.PERFORMANCE_OPTIMIZATION)
        self.assertEqual(reconstructed.status, ContentPostStatus.DRAFT)

    async def test_02_storage_crud(self):
        """Valida la persistencia SQLite completa: init, save, get, list, update_status y delete."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_db = tmp.name

        try:
            storage = ContentStorage(db_path=tmp_db)
            await storage.init_db()

            # 1. Guardar post inicial
            created = await storage.save_post(self.sample_post)
            self.assertTrue(created, "El post debería ser insertado como nuevo")

            # 2. Recuperar post
            fetched = await storage.get_post("test_post_001")
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched.title, self.sample_post.title)
            self.assertEqual(len(fetched.carousel_slides), 2)
            self.assertEqual(fetched.carousel_slides[0].metric_badge, "99/100 Lighthouse")
            self.assertEqual(fetched.carousel_slides[1].code_snippet, "const bottleneck = await fetchAllSync();")

            # 3. Listar posts
            all_posts = await storage.list_posts()
            self.assertEqual(len(all_posts), 1)

            draft_posts = await storage.list_posts(status=ContentPostStatus.DRAFT)
            self.assertEqual(len(draft_posts), 1)

            pub_posts = await storage.list_posts(status=ContentPostStatus.PUBLISHED)
            self.assertEqual(len(pub_posts), 0)

            # 4. Actualizar estado
            updated = await storage.update_status("test_post_001", ContentPostStatus.PUBLISHED, n8n_response="OK 200")
            self.assertTrue(updated)
            fetched_updated = await storage.get_post("test_post_001")
            self.assertEqual(fetched_updated.status, ContentPostStatus.PUBLISHED)
            self.assertIsNotNone(fetched_updated.n8n_published_at)
            self.assertEqual(fetched_updated.n8n_response, "OK 200")

            # 5. Eliminar post
            deleted = await storage.delete_post("test_post_001")
            self.assertTrue(deleted)
            self.assertIsNone(await storage.get_post("test_post_001"))
        finally:
            if os.path.exists(tmp_db):
                try:
                    os.remove(tmp_db)
                except Exception:
                    pass

    def test_03_carousel_renderer_html_and_zero_emojis(self):
        """Valida que el CarouselRenderer produzca HTML semántico válido y CERO emojis."""
        html_out = CarouselRenderer.render_html(self.sample_post, auto_print=False)

        # 1. Verificar estructura
        self.assertIn("<!DOCTYPE html>", html_out)
        self.assertIn("slide active", html_out)
        self.assertIn("Arquitectura de Alto Rendimiento", html_out)
        self.assertIn("99/100 Lighthouse", html_out)
        self.assertIn("const bottleneck = await fetchAllSync();", html_out)
        self.assertIn("DESLIZÁ PARA MÁS &rarr;", html_out)
        self.assertIn("<svg", html_out)

        # 2. Verificar ausencia total de emojis
        emojis_found = self.emoji_pattern.findall(html_out)
        self.assertEqual(
            len(emojis_found),
            0,
            f"El carrusel renderizado contiene emojis no permitidos: {emojis_found}"
        )

    def test_04_generator_parsing_and_zero_emojis(self):
        """Valida que el parser del ContentGenerator extraiga correctamente y no contenga emojis en defaults."""
        generator = ContentGenerator()

        # Respuesta simulada limpia de LLM
        mock_raw_json = json.dumps({
            "title": "Arquitectura Hexagonal en Node.js",
            "hook": "La arquitectura hexagonal desacopla tu dominio de la infraestructura.",
            "linkedin_post": "La arquitectura hexagonal desacopla tu dominio.\n\n• Puertos y adaptadores.\n• Dominio puro.\n\n#nodejs #architecture",
            "first_comment": "Detalles completos en https://mateogs.tech",
            "twitter_thread": ["1/2 Puertos y adaptadores en Node.js.", "2/2 Fin del hilo."],
            "devto_article": {
                "title": "Arquitectura Hexagonal en Node.js",
                "tags": ["nodejs", "architecture", "clean-code", "backend"],
                "markdown_body": "# Puertos y adaptadores\n\nImplementación...",
            },
            "carousel_slides": [
                {
                    "index": 1,
                    "title": "Slide 1",
                    "subtitle": "Sub 1",
                    "bullets": ["Punto 1"],
                    "metric_badge": "100%",
                    "code_snippet": None,
                    "footer": "mateogs.tech",
                }
            ],
        })

        post = generator._parse_response(
            mock_raw_json,
            topic="Arquitectura Hexagonal",
            pillar=ContentPillar.ARCHITECTURE,
            project_slug=None,
        )

        self.assertEqual(post.title, "Arquitectura Hexagonal en Node.js")
        self.assertEqual(len(post.carousel_slides), 1)

        # Verificar fallback cuando LLM devuelve JSON inválido
        fallback_post = generator._parse_response(
            "INVALID_JSON_RESPONSE",
            topic="Fallback Test",
            pillar=ContentPillar.ARCHITECTURE,
            project_slug=None,
        )
        self.assertIn("Fallback Test", fallback_post.title)
        
        # Verificar regla estricta de CERO EMOJIS en fallback
        fallback_json = json.dumps(fallback_post.model_dump())
        emojis_found = self.emoji_pattern.findall(fallback_json)
        self.assertEqual(
            len(emojis_found),
            0,
            f"El post de fallback contiene emojis: {emojis_found}"
        )

    async def test_05_dispatcher_local_and_remote(self):
        """Valida el dispatcher tanto en modo local (sin webhook) como despachando a n8n."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_db = tmp.name

        try:
            storage = ContentStorage(db_path=tmp_db)
            await storage.init_db()
            await storage.save_post(self.sample_post)

            dispatcher = ContentDispatcher(storage=storage)

            # Caso 1: Sin webhook configurado (aprobación local en base de datos)
            with patch.object(dispatcher.settings, "n8n_webhook_url", ""):
                res = await dispatcher.publish_post(self.sample_post.id)
                self.assertTrue(res["ok"])
                self.assertEqual(res["status"], "approved_local")
                saved = await storage.get_post(self.sample_post.id)
                self.assertEqual(saved.status, ContentPostStatus.APPROVED)

            # Caso 2: Con webhook simulado (HTTP 200 de n8n)
            mock_resp = AsyncMock()
            mock_resp.status_code = 200
            mock_resp.text = '{"workflow_id": "flow_123", "status": "executed"}'

            with patch.object(dispatcher.settings, "n8n_webhook_url", "https://flow.mateogs.tech/webhook/content"):
                with patch("httpx.AsyncClient.post", return_value=mock_resp):
                    res2 = await dispatcher.publish_post(self.sample_post.id)
                    self.assertTrue(res2["ok"])
                    self.assertEqual(res2["status"], "published")
                    saved2 = await storage.get_post(self.sample_post.id)
                    self.assertEqual(saved2.status, ContentPostStatus.PUBLISHED)
                    self.assertIn("flow_123", saved2.n8n_response)
        finally:
            if os.path.exists(tmp_db):
                try:
                    os.remove(tmp_db)
                except Exception:
                    pass


if __name__ == "__main__":
    unittest.main()
