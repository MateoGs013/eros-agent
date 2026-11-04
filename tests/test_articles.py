"""Tests de los artículos para el portafolio: validación del texto y POST /api/articles/generate.

Ninguno sale a la red: la IA está simulada.
"""

import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from eros.config import get_settings
from eros.content.article import (
    ARTICLE_MAX_TOKENS,
    count_words,
    normalize_markdown,
    normalize_tags,
    parse_english_translation,
    parse_spanish_article,
)
from eros.content.models import ArticleVersion
from eros.integrations.llm import LLMOutputError, LLMUnavailableError
from eros.models import ProfileContext, ProjectSummary
from eros.radar.models import TrendItem, TrendSource, TrendStatus

API_KEY = "eros_articles_test_key_0123456789"
AUTH = {"Authorization": f"Bearer {API_KEY}"}

SENTENCE = (
    "Elegí renderizar cada página en el servidor para que la obra se lea completa con JavaScript apagado, "
    "y recién después sumé el movimiento encima sin tocar el contenido ni la navegación por teclado."
)


def filler(sentences: int) -> str:
    return " ".join([SENTENCE] * sentences)


def article_markdown(sentences: int = 30) -> str:
    """Un cuerpo válido: subtítulos, lista, cita, código (con etiquetas adentro) y un enlace https."""
    half = sentences // 2
    return "\n".join([
        f"Arranco por el problema. {filler(half)}",
        "",
        "## Por qué lo resolví en el servidor",
        "",
        filler(sentences - half),
        "",
        "### Lo que cambió",
        "",
        "- La página se arma con los datos de la base.",
        "1. Primero el contenido, después el movimiento.",
        "",
        "> Lo que tocás se transforma en la página.",
        "",
        "```vue",
        "<template>",
        "  <div class=\"obra\">{{ titulo }}</div>",
        "</template>",
        "| esto | no es una tabla del texto |",
        "```",
        "",
        "Tipé la respuesta como `Array<string>` y lo dejé en **producción**, *sin* sorpresas: [el sitio](https://mateogs.tech).",
    ])


def spanish_json(**overrides) -> str:
    data = {
        "topic": "SSR antes que el movimiento",
        "title": "Por qué el portafolio se renderiza en el servidor",
        "summary": "Cómo ordené el portafolio para que el contenido llegue primero y el movimiento después.",
        "tags": ["Nuxt", "#Postgres", "SSR", "nuxt"],
        "project_slug": "portafolio",
        "markdown": article_markdown(),
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def english_json(**overrides) -> str:
    data = {
        "title": "Why the portfolio renders on the server",
        "summary": "How I ordered the portfolio so content arrives first and motion second.",
        "markdown": article_markdown(),
    }
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def profile_with_project() -> ProfileContext:
    return ProfileContext(
        tech_stack=["Nuxt", "Vue", "PostgreSQL", "TypeScript"],
        projects=[
            ProjectSummary(slug="portafolio", title="Portafolio (mateogs.tech)", summary="Portafolio con Nuxt 4 y Postgres 17",
                           techs=["Nuxt", "PostgreSQL"], url="https://mateogs.tech"),
            ProjectSummary(slug="la-rucula", title="La Rúcula", summary="Sitio de un restaurante", techs=["Vue"]),
        ],
    )


# ──────────────────────────────────────────────────────────────────────────────
# Validación del artículo
# ──────────────────────────────────────────────────────────────────────────────

class TestArticleValidation(unittest.TestCase):
    def test_valid_article_is_normalized(self):
        draft = parse_spanish_article(spanish_json(), known_project_slugs=["portafolio", "la-rucula"])
        self.assertEqual(draft.tags, ["nuxt", "postgres", "ssr"])
        self.assertEqual(draft.project_slug, "portafolio")
        self.assertEqual(draft.topic, "SSR antes que el movimiento")
        self.assertIn("<template>", draft.version.markdown, "las etiquetas dentro de código se respetan")
        self.assertGreaterEqual(count_words(draft.version.markdown), 500)

    def test_unknown_project_slug_is_dropped_and_forced_one_wins(self):
        draft = parse_spanish_article(spanish_json(project_slug="inventado"), known_project_slugs=["portafolio"])
        self.assertIsNone(draft.project_slug)
        draft = parse_spanish_article(spanish_json(project_slug=None), forced_project_slug="la-rucula")
        self.assertEqual(draft.project_slug, "la-rucula")

    def test_table_is_rejected(self):
        md = article_markdown() + "\n\n| Antes | Después |\n|---|---|\n| lento | rápido |"
        with self.assertRaises(LLMOutputError) as ctx:
            parse_spanish_article(spanish_json(markdown=md))
        self.assertIn("tabla", str(ctx.exception))

    def test_emoji_is_rejected(self):
        with self.assertRaises(LLMOutputError) as ctx:
            parse_spanish_article(spanish_json(markdown=article_markdown() + "\n\nY quedó andando \U0001F680"))
        self.assertIn("emojis", str(ctx.exception))
        with self.assertRaises(LLMOutputError):
            parse_spanish_article(spanish_json(title="SSR primero ✨"))

    def test_html_images_and_bad_links_are_rejected(self):
        cases = {
            '<img src="https://x/y.png">': "HTML",
            "<div>suelto</div>": "HTML",
            "![captura](https://mateogs.tech/a.png)": "imagen",
            "[click](javascript:alert(1))": "enlace",
            "[obra](/projects/portafolio)": "enlace",
        }
        for snippet, expected in cases.items():
            with self.subTest(snippet=snippet):
                with self.assertRaises(LLMOutputError) as ctx:
                    parse_spanish_article(spanish_json(markdown=article_markdown() + "\n\n" + snippet))
                self.assertIn(expected, str(ctx.exception))
                self.assertTrue(str(ctx.exception).startswith("El artículo no respeta el formato del portafolio"))

    def test_too_short_is_rejected(self):
        with self.assertRaises(LLMOutputError) as ctx:
            parse_spanish_article(spanish_json(markdown=article_markdown(sentences=8)))
        self.assertIn("palabras", str(ctx.exception))
        self.assertTrue(str(ctx.exception).startswith("El artículo vino incompleto"))

    def test_leading_h1_is_stripped_and_headings_capped(self):
        md = "# Por qué el portafolio se renderiza en el servidor\n\n" + article_markdown() + "\n\n# Otro H1\n\n#### Muy hondo"
        draft = parse_spanish_article(spanish_json(markdown=md))
        lines = draft.version.markdown.split("\n")
        self.assertTrue(lines[0].startswith("Arranco por el problema"))
        self.assertIn("## Otro H1", lines)
        self.assertIn("### Muy hondo", lines)
        self.assertFalse(any(line.startswith("# ") for line in lines))
        self.assertEqual(normalize_markdown("```\n# comentario de shell\n```"), "```\n# comentario de shell\n```")

    def test_truncated_output_is_an_error(self):
        truncated = spanish_json()[:400]
        with self.assertRaises(LLMOutputError) as ctx:
            parse_spanish_article(truncated)
        self.assertTrue(str(ctx.exception).startswith("El artículo vino incompleto"))

        unclosed = article_markdown() + "\n\n```ts\nconst cortado = true"
        with self.assertRaises(LLMOutputError) as ctx:
            parse_spanish_article(spanish_json(markdown=unclosed))
        self.assertIn("sin cerrar", str(ctx.exception))

    def test_missing_fields_tags_and_limits(self):
        with self.assertRaises(LLMOutputError) as ctx:
            parse_spanish_article(spanish_json(summary=""))
        self.assertIn("summary", str(ctx.exception))
        with self.assertRaises(LLMOutputError) as ctx:
            parse_spanish_article(spanish_json(tags=[]))
        self.assertIn("tags", str(ctx.exception))
        with self.assertRaises(LLMOutputError) as ctx:
            parse_spanish_article(spanish_json(title="T" * 161))
        self.assertIn("160", str(ctx.exception))
        with self.assertRaises(LLMOutputError):
            parse_spanish_article(spanish_json(summary="R" * 401))

    def test_tags_are_short_lowercase_and_at_most_six(self):
        tags = normalize_tags(["Vue 3", "Node.js", "una etiqueta larguísima que no entra", "", "a", "b", "c", "d", "e"])
        self.assertEqual(tags, ["vue-3", "node.js", "a", "b", "c", "d"])
        self.assertEqual(normalize_tags("nuxt, postgres"), ["nuxt", "postgres"])

    def test_translation_must_keep_length(self):
        spanish = parse_spanish_article(spanish_json()).version
        english = parse_english_translation(english_json(), spanish)
        self.assertEqual(english.title, "Why the portfolio renders on the server")
        with self.assertRaises(LLMOutputError) as ctx:
            parse_english_translation(english_json(markdown=article_markdown(sentences=6)), spanish)
        self.assertTrue(str(ctx.exception).startswith("La traducción al inglés vino incompleta"))
        with self.assertRaises(LLMOutputError):
            parse_english_translation(english_json(markdown=article_markdown() + "\n\n| a | b |"), spanish)


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/articles/generate
# ──────────────────────────────────────────────────────────────────────────────

class TestArticlesApi(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from eros.api import engine as api_engine, radar_storage

        os.environ["EROS_API_KEY"] = API_KEY
        get_settings.cache_clear()
        await api_engine.storage.init_db()
        await api_engine.storage.save_profile_cache(profile_with_project())
        await radar_storage.init_db()

    async def _wait(self, client: httpx.AsyncClient, status_url: str) -> dict:
        for _ in range(100):
            task = (await client.get(status_url, headers=AUTH)).json()
            if task["status"] != "running":
                return task
            await asyncio.sleep(0.02)
        self.fail("La tarea del artículo no terminó")

    async def test_generate_returns_202_and_result_matches_contract(self):
        from eros.api import app, article_generator

        async def slow_write(**kwargs):
            await asyncio.sleep(0.1)
            return spanish_json() if "JSON" in kwargs["prompt"] and "Translate" not in kwargs["prompt"] else english_json()

        llm = AsyncMock(side_effect=slow_write)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            with patch.object(article_generator.llm, "generate", llm):
                r1 = await client.post("/api/articles/generate", json={
                    "topic": "SSR antes que el movimiento",
                    "avoid_titles": ["Mi primer artículo sobre Nuxt"],
                }, headers=AUTH)
                r2 = await client.post("/api/articles/generate", headers=AUTH)
                self.assertEqual(r1.status_code, 202, r1.text)
                self.assertEqual(r2.status_code, 202, r2.text)
                self.assertEqual(r1.json()["kind"], "article")
                self.assertEqual(r1.json()["task_id"], r2.json()["task_id"])
                self.assertFalse(r1.json()["already_running"])
                self.assertTrue(r2.json()["already_running"])
                task = await self._wait(client, r1.json()["status_url"])

        self.assertEqual(task["status"], "done", task)
        result = task["result"]
        self.assertEqual(set(result), {"topic", "project_slug", "trend_id", "tags", "es", "en", "model"})
        self.assertEqual(set(result["es"]), {"title", "summary", "markdown"})
        self.assertEqual(set(result["en"]), {"title", "summary", "markdown"})
        self.assertEqual(result["topic"], "SSR antes que el movimiento")
        self.assertEqual(result["project_slug"], "portafolio")
        self.assertIsNone(result["trend_id"])
        self.assertEqual(result["tags"], ["nuxt", "postgres", "ssr"])
        self.assertEqual(result["en"]["title"], "Why the portfolio renders on the server")
        self.assertEqual(result["model"], get_settings().gemini_model)

        self.assertEqual(llm.call_count, 2)
        es_call, en_call = llm.call_args_list
        self.assertEqual(es_call.kwargs["max_tokens"], ARTICLE_MAX_TOKENS)
        self.assertEqual(es_call.kwargs["timeout"], 150.0)
        self.assertTrue(es_call.kwargs["json_mode"])
        self.assertIn("NUNCA inventes", es_call.kwargs["system_prompt"])
        self.assertIn("Mi primer artículo sobre Nuxt", es_call.kwargs["prompt"])
        self.assertIn("La Rúcula", es_call.kwargs["prompt"])
        self.assertIn("Por qué el portafolio se renderiza en el servidor", en_call.kwargs["prompt"])

    async def test_trend_id_is_folded_into_prompt_and_marked_generated(self):
        from eros.api import app, article_generator, radar_storage

        await radar_storage.save_trend(TrendItem(
            id="t-article", title="Postgres 18", url="https://hn.example/pg18", source=TrendSource.HACKER_NEWS,
            summary="Novedades de Postgres 18", relevance_score=90, engineering_angle="I/O asincrónico en la base",
            detected_at="2026-11-01",
        ))
        llm = AsyncMock(side_effect=[spanish_json(project_slug="la-rucula"), english_json()])
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            with patch.object(article_generator.llm, "generate", llm):
                r = await client.post("/api/articles/generate", json={
                    "trend_id": "t-article", "angle": "Qué cambia para un portafolio chico",
                }, headers=AUTH)
                self.assertEqual(r.status_code, 202, r.text)
                task = await self._wait(client, r.json()["status_url"])

        self.assertEqual(task["status"], "done", task)
        self.assertEqual(task["result"]["trend_id"], "t-article")
        self.assertEqual(task["result"]["project_slug"], "la-rucula")
        prompt = llm.call_args_list[0].kwargs["prompt"]
        for expected in ("https://hn.example/pg18", "Novedades de Postgres 18", "I/O asincrónico en la base",
                         "Qué cambia para un portafolio chico"):
            self.assertIn(expected, prompt)
        self.assertEqual((await radar_storage.get_trend("t-article")).status, TrendStatus.GENERATED)

    async def test_failures_leave_clear_errors(self):
        from eros.api import app, article_generator, radar_storage

        await radar_storage.save_trend(TrendItem(
            id="t-fail", title="Bun 2", url="https://hn.example/bun", source=TrendSource.HACKER_NEWS,
            summary="s", relevance_score=70, engineering_angle="a", detected_at="2026-11-01",
        ))
        cases = [
            (AsyncMock(side_effect=LLMUnavailableError("No hay GEMINI_API_KEY ni ANTHROPIC_API_KEY configuradas.")),
             {"trend_id": "t-fail"}, "llm_unavailable", "Gemini no está disponible: "),
            (AsyncMock(return_value=spanish_json()[:300]), {}, "llm_output_invalid", "El artículo vino incompleto: "),
            (AsyncMock(side_effect=LLMOutputError("La respuesta de Gemini (gemini-x) se cortó por largo.")), {},
             "llm_output_invalid", "El artículo vino incompleto: la respuesta de Gemini"),
            (AsyncMock(side_effect=[spanish_json(), english_json(markdown="Muy corto.")]), {},
             "llm_output_invalid", "La traducción al inglés vino incompleta: "),
            (AsyncMock(), {"trend_id": "no-existe"}, "trend_not_found", "La tendencia «no-existe»"),
        ]
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            for llm, body, code, message in cases:
                with self.subTest(code=code, message=message), patch.object(article_generator.llm, "generate", llm):
                    r = await client.post("/api/articles/generate", json=body, headers=AUTH)
                    self.assertEqual(r.status_code, 202, r.text)
                    task = await self._wait(client, r.json()["status_url"])
                    self.assertEqual(task["status"], "failed", task)
                    self.assertEqual(task["error_code"], code)
                    self.assertTrue(task["error"].startswith(message), task["error"])
        self.assertEqual((await radar_storage.get_trend("t-fail")).status, TrendStatus.DISCOVERED)

    async def test_unknown_project_fails_after_one_sync(self):
        from eros.api import app, article_generator, engine as api_engine

        llm = AsyncMock()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            with patch.object(article_generator.llm, "generate", llm), \
                 patch.object(api_engine, "sync_profile", AsyncMock(return_value=profile_with_project())) as sync:
                r = await client.post("/api/articles/generate", json={"project_slug": "no-existe"}, headers=AUTH)
                task = await self._wait(client, r.json()["status_url"])
        sync.assert_awaited_once()
        llm.assert_not_called()
        self.assertEqual(task["status"], "failed")
        self.assertEqual(task["error_code"], "project_not_found")

    async def test_body_limits_and_auth(self):
        from eros.api import app

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            no_auth = await client.post("/api/articles/generate", json={})
            long_topic = await client.post("/api/articles/generate", json={"topic": "x" * 301}, headers=AUTH)
            long_angle = await client.post("/api/articles/generate", json={"angle": "x" * 1001}, headers=AUTH)
            many = await client.post("/api/articles/generate", json={"avoid_titles": ["t"] * 301}, headers=AUTH)
            long_title = await client.post("/api/articles/generate", json={"avoid_titles": ["t" * 201]}, headers=AUTH)
        self.assertEqual(no_auth.status_code, 401)
        for r in (long_topic, long_angle, many, long_title):
            self.assertEqual(r.status_code, 422, r.text)


if __name__ == "__main__":
    unittest.main()
