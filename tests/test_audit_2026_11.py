"""Tests de los arreglos de la auditoría del 2-nov-2026 (docs/auditoria-eros.md del portfolio).

Cubren: correos nunca adivinados, envío idempotente, escaneo que no borra historial,
modo sin IA que no inventa, Radar → artículo y escaneo asincrónico. La publicación en
LinkedIn/X se quitó: los tests de canales se reemplazaron por los de rutas que ya no existen.
Ninguno sale a la red: todo lo externo está simulado.
"""

import asyncio
import json
import logging
import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from eros.config import Settings, get_settings
from eros.db.storage import JobStorage
from eros.hunter.cv_generator import CVGenerator
from eros.hunter.dispatcher import JobApplicationDispatcher
from eros.hunter.engine import HunterEngine, ScanInProgressError
from eros.hunter.normalize import job_dedup_key
from eros.integrations.llm import LLMClient, LLMOutputError, LLMUnavailableError
from eros.models import JobOffer, JobStatus, MatchResult, ProfileContext
from eros.radar.models import TrendItem, TrendSource, TrendStatus
from eros.radar.storage import RadarStorage
from portfolio_cv import portfolio_cv

API_KEY = "eros_audit_test_key_0123456789"
AUTH = {"Authorization": f"Bearer {API_KEY}"}


def qualified_job(job_id: str, source: str = "remotive", company: str = "Acme", title: str = "Full Stack Developer", **kw) -> JobOffer:
    return JobOffer(
        id=job_id,
        source=source,
        external_id=job_id,
        title=title,
        company=company,
        url=f"https://{source}.example/jobs/{job_id}",
        description="Remote role. Vue 3, TypeScript, Node.js and PostgreSQL. LATAM welcome.",
        country="Remote",
        tags=["vue", "typescript"],
        **kw,
    )


class FakeSource:
    def __init__(self, name: str, jobs: list[JobOffer], delay: float = 0.0):
        self.name = name
        self._jobs = jobs
        self._delay = delay

    async def fetch_jobs(self) -> list[JobOffer]:
        if self._delay:
            await asyncio.sleep(self._delay)
        return [j.model_copy() for j in self._jobs]


class _TempDbCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "audit.db")
        self.storage = JobStorage(db_path=self.db_path)
        await self.storage.init_db()
        await self.storage.save_profile_cache(ProfileContext())

    async def asyncTearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


# ──────────────────────────────────────────────────────────────────────────────
# R3 / M3: envío idempotente y honesto
# ──────────────────────────────────────────────────────────────────────────────

class TestIdempotentDispatch(_TempDbCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.dispatcher = JobApplicationDispatcher(storage=self.storage)
        self.dispatcher.settings = Settings(
            database_path=self.db_path,
            n8n_application_webhook_url="https://n8n.example/webhook/apply",
            n8n_webhook_secret="n8n-shared-secret",
        )
        job = qualified_job("job-send-1", pitch_draft='{"cover_letter": "Hola."}')
        await self.storage.save_job(job)

    async def _send(self, **kw):
        args = dict(job_id="job-send-1", to_email="rrhh@acme.io", custom_subject="Postulación", custom_body="Cuerpo", confirmed=True, cv=portfolio_cv())
        args.update(kw)
        return await self.dispatcher.dispatch_application(**args)

    async def test_concurrent_sends_post_only_once(self):
        calls = []

        async def slow_post(url, json=None, headers=None):
            calls.append((url, json, headers))
            await asyncio.sleep(0.2)
            return MagicMock(status_code=200, text="OK")

        with patch("httpx.AsyncClient.post", side_effect=slow_post):
            r1, r2 = await asyncio.gather(self._send(), self._send())

        self.assertEqual(len(calls), 1, "Dos pedidos simultáneos no pueden mandar dos correos")
        oks = [r for r in (r1, r2) if r["ok"]]
        fails = [r for r in (r1, r2) if not r["ok"]]
        self.assertEqual(len(oks), 1)
        self.assertIn(fails[0]["error_code"], ("send_in_progress", "already_applied"))

        url, payload, headers = calls[0]
        self.assertEqual(url, "https://n8n.example/webhook/apply")
        self.assertEqual(headers["Idempotency-Key"], "apply-job-send-1")
        self.assertEqual(headers["X-N8N-Secret"], "n8n-shared-secret")
        self.assertEqual(payload["idempotency_key"], "apply-job-send-1")

        job = await self.storage.get_job("job-send-1")
        self.assertEqual(job.status, JobStatus.APPLIED)
        self.assertIsNone(job.send_state)

        # Un tercer intento posterior tampoco envía
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as again:
            r3 = await self._send()
            again.assert_not_called()
        self.assertEqual(r3["error_code"], "already_applied")

    async def test_timeout_leaves_unknown_and_blocks_retry_until_forced(self):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=httpx.ReadTimeout("timeout")):
            res = await self._send()
        self.assertFalse(res["ok"])
        self.assertEqual(res["error_code"], "send_outcome_unknown")
        job = await self.storage.get_job("job-send-1")
        self.assertEqual(job.send_state, "unknown")
        self.assertNotEqual(job.status, JobStatus.APPLIED)
        self.assertIsNone(job.applied_at)

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as blocked:
            res = await self._send()
            blocked.assert_not_called()
        self.assertEqual(res["error_code"], "send_outcome_unknown")

        ok = MagicMock(status_code=200, text="OK")
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=ok) as forced:
            res = await self._send(force_retry=True)
            forced.assert_called_once()
        self.assertTrue(res["ok"])

    async def test_rejected_by_n8n_releases_for_retry(self):
        bad = MagicMock(status_code=400, text="bad request")
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=bad):
            res = await self._send()
        self.assertEqual(res["error_code"], "provider_rejected")
        job = await self.storage.get_job("job-send-1")
        self.assertIsNone(job.send_state)
        self.assertIsNone(job.applied_at)

        ok = MagicMock(status_code=200, text="OK")
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=ok):
            res = await self._send()
        self.assertTrue(res["ok"])

    async def test_no_provider_never_registers(self):
        self.dispatcher.settings.n8n_application_webhook_url = ""
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
            res = await self._send(channel="n8n")
            post.assert_not_called()
        self.assertFalse(res["ok"])
        self.assertEqual(res["error_code"], "no_provider")
        job = await self.storage.get_job("job-send-1")
        self.assertIsNone(job.applied_at)
        self.assertIsNone(job.send_state)

    async def test_unknown_source_email_needs_typed_address(self):
        job = qualified_job("job-legacy-email", contact_email="peter@acme.io")
        await self.storage.save_job(job)
        stored = await self.storage.get_job("job-legacy-email")
        self.assertEqual(stored.contact_email_source, "unknown")

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
            res = await self.dispatcher.dispatch_application(job_id="job-legacy-email", confirmed=True)
            post.assert_not_called()
        self.assertEqual(res["error_code"], "unverified_email")

        preview = await self.dispatcher.get_application_preview("job-legacy-email")
        self.assertFalse(preview["contact_email_verified"])
        self.assertTrue(preview["requires_manual_email"])

        # Escribir la misma dirección a mano (to_email) la vuelve manual y se puede enviar
        ok = MagicMock(status_code=200, text="OK")
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=ok):
            res = await self.dispatcher.dispatch_application(
                job_id="job-legacy-email", to_email="peter@acme.io", confirmed=True, cv=portfolio_cv()
            )
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["contact_email_source"], "manual")
        self.assertEqual((await self.storage.get_job("job-legacy-email")).contact_email_source, "manual")

    async def test_applied_status_is_never_overwritten(self):
        applied = qualified_job("job-applied-keep", status=JobStatus.APPLIED, applied_at="2026-10-01T00:00:00+00:00")
        await self.storage.save_job(applied)
        stale = await self.storage.get_job("job-applied-keep")
        stale.status = JobStatus.DISCARDED
        await self.storage.save_job(stale)
        self.assertEqual((await self.storage.get_job("job-applied-keep")).status, JobStatus.APPLIED)
        await self.storage.delete_all_discarded_jobs()
        self.assertIsNotNone(await self.storage.get_job("job-applied-keep"))


# ──────────────────────────────────────────────────────────────────────────────
# E1 + dedup: el escaneo no borra historial ni duplica
# ──────────────────────────────────────────────────────────────────────────────

class TestScanKeepsHistory(_TempDbCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.engine = HunterEngine(storage=self.storage)
        self.engine.vectorize_and_score_jobs = AsyncMock(return_value=0)

    async def test_initialize_and_scan_never_delete_jobs(self):
        applied = qualified_job("job-applied", status=JobStatus.APPLIED, applied_at="2026-10-01T00:00:00+00:00", match_score=20)
        discarded = qualified_job("job-discarded", company="Globex", status=JobStatus.DISCARDED)
        low = qualified_job("job-low", company="Initech", status=JobStatus.EVALUATED, match_score=10)
        offtopic = JobOffer(id="job-php", source="remotive", title="Senior PHP Laravel Developer", company="Hooli",
                            url="https://x/php", description="PHP Laravel onsite", status=JobStatus.SAVED)
        for j in (applied, discarded, low, offtopic):
            await self.storage.save_job(j)

        self.engine.sources = [FakeSource("remotive", [discarded])]
        await self.engine.initialize()
        await self.engine.run_scan()

        for job_id in ("job-applied", "job-discarded", "job-low", "job-php"):
            self.assertIsNotNone(await self.storage.get_job(job_id), f"{job_id} fue borrada")
        self.assertEqual((await self.storage.get_job("job-discarded")).status, JobStatus.DISCARDED)
        self.assertEqual((await self.storage.get_job("job-applied")).status, JobStatus.APPLIED)

        # La purga explícita solo descarta (sin borrar) y nunca toca lo postulado
        discarded_count = await self.engine.discard_incompatible_jobs()
        self.assertEqual(discarded_count, 2)  # job-low (puntaje) y job-php (filtros)
        self.assertEqual((await self.storage.get_job("job-applied")).status, JobStatus.APPLIED)
        self.assertEqual((await self.storage.get_job("job-php")).status, JobStatus.DISCARDED)

    async def test_deleted_jobs_do_not_come_back_as_new(self):
        job = qualified_job("job-deleted")
        await self.storage.save_job(job)
        await self.storage.delete_job("job-deleted")

        same_elsewhere = qualified_job("job-deleted-other-source", source="weworkremotely")
        self.engine.sources = [FakeSource("remotive", [job]), FakeSource("weworkremotely", [same_elsewhere])]
        res = await self.engine.run_scan()
        self.assertEqual(res["new_jobs"], 0)
        self.assertIsNone(await self.storage.get_job("job-deleted"))

        # Pasado el plazo, la misma empresa + título desde otra fuente es una búsqueda nueva
        import aiosqlite
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE seen_jobs SET created_at = '2025-01-01T00:00:00+00:00'")
            await db.commit()
        res = await self.engine.run_scan()
        self.assertEqual(res["new_jobs"], 1)
        self.assertIsNone(await self.storage.get_job("job-deleted"), "el mismo id sigue sin volver")
        self.assertIsNotNone(await self.storage.get_job("job-deleted-other-source"))

        # "Borrar todas" conserva lo postulado
        await self.storage.save_job(qualified_job("job-a", company="A1"))
        await self.storage.save_job(qualified_job("job-b", company="B1", status=JobStatus.APPLIED, applied_at="2026-10-02"))
        await self.storage.delete_all_jobs()
        self.assertIsNone(await self.storage.get_job("job-a"))
        self.assertIsNotNone(await self.storage.get_job("job-b"))

    async def test_same_job_from_two_sources_is_saved_once(self):
        a = qualified_job("job-src-a", source="remotive", company="Acme Inc.", title="Full Stack Developer (Remote)")
        b = qualified_job("job-src-b", source="weworkremotely", company="ACME", title="Full-Stack Developer")
        self.assertEqual(job_dedup_key(a.company, a.title, a.source), job_dedup_key(b.company, b.title, b.source))

        self.engine.sources = [FakeSource("remotive", [a]), FakeSource("weworkremotely", [b])]
        res = await self.engine.run_scan()
        self.assertEqual(res["new_jobs"], 1)
        saved = [await self.storage.get_job("job-src-a"), await self.storage.get_job("job-src-b")]
        self.assertEqual(sum(1 for j in saved if j is not None), 1)

        # Los genéricos ("Empresa Confidencial", "Empresa Remota") no se deduplican por clave:
        # dos avisos distintos con el mismo título se guardan los dos
        self.assertIsNone(job_dedup_key("Empresa Confidencial (Neuquén)", "Full Stack Developer", "computrabajo"))
        self.assertIsNone(job_dedup_key("Empresa Remota", "Full Stack Developer", "remoteok"))
        c1 = qualified_job("job-conf-1", source="computrabajo", company="Empresa Confidencial")
        c2 = qualified_job("job-conf-2", source="computrabajo", company="Empresa Confidencial")
        r1 = qualified_job("job-rem-1", source="remoteok", company="Empresa Remota")
        r2 = qualified_job("job-rem-2", source="remotive", company="Empresa Remota")
        self.engine.sources = [FakeSource("computrabajo", [c1, c2]), FakeSource("remoteok", [r1]), FakeSource("remotive", [r2])]
        res = await self.engine.run_scan()
        self.assertEqual(res["new_jobs"], 4)

    async def test_scan_extracts_posting_email_with_source(self):
        job = qualified_job("job-mail")
        job.description += " Send your CV to talent@acme.io"
        self.engine.sources = [FakeSource("remotive", [job])]
        await self.engine.run_scan()
        saved = await self.storage.get_job("job-mail")
        self.assertEqual((saved.contact_email, saved.contact_email_source), ("talent@acme.io", "posting"))

    async def test_two_scans_cannot_run_at_once(self):
        self.engine.sources = [FakeSource("remotive", [qualified_job("job-slow")], delay=0.2)]
        first = asyncio.create_task(self.engine.run_scan())
        await asyncio.sleep(0.05)
        self.assertTrue(self.engine.scan_in_progress)
        with self.assertRaises(ScanInProgressError):
            await self.engine.run_scan()
        await first
        self.assertFalse(self.engine.scan_in_progress)


# ──────────────────────────────────────────────────────────────────────────────
# R4: sin IA no se inventa
# ──────────────────────────────────────────────────────────────────────────────

class TestHeuristicModeDoesNotInvent(_TempDbCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        LLMClient._quota_exhausted_until = 0.0
        self.engine = HunterEngine(storage=self.storage)
        self.no_ai = Settings(gemini_api_key="", anthropic_api_key="", database_path=self.db_path)
        for llm in (self.engine.matcher.llm, self.engine.cv_gen.llm, self.engine.pitch_gen.llm):
            llm.settings = self.no_ai

    async def test_generate_without_ai_raises_unless_heuristic_allowed(self):
        llm = LLMClient()
        llm.settings = self.no_ai
        with self.assertRaises(LLMUnavailableError):
            await llm.generate("Generá el JSON del CV adaptado")
        with self.assertRaises(LLMUnavailableError):
            await llm.generate('{"title": "", "markdown": ""}', json_mode=True)
        with self.assertRaises(LLMUnavailableError):
            await llm.generate("REDACTÁ UNA PROPUESTA elevator_pitch")
        data = json.loads(await llm.generate("EVALUÁ ESTA OFERTA LABORAL:\nTítulo: Dev", allow_heuristic=True))
        self.assertEqual(data["scored_by"], "heuristic")
        self.assertIsNone(data["recruiter_note"])

    async def test_heuristic_evaluation_never_saves_job(self):
        job = qualified_job("job-heur")
        await self.storage.save_job(job)
        await self.storage.set_setting("match_min_score", "50")

        res = await self.engine.evaluate_single_job("job-heur")
        self.assertIsNotNone(res)
        evaluated, match = res
        self.assertEqual(match.scored_by, "heuristic")
        self.assertGreaterEqual(match.score, 50, "el puntaje heurístico supera el umbral a propósito")
        saved = await self.storage.get_job("job-heur")
        self.assertEqual(saved.scored_by, "heuristic")
        self.assertEqual(saved.status, JobStatus.EVALUATED)
        self.assertIsNone(saved.connection_note)
        self.assertIsNone(saved.salary)

    async def test_cv_and_pitch_fail_without_ai(self):
        await self.storage.save_job(qualified_job("job-cv"))
        with self.assertRaises(LLMUnavailableError):
            await self.engine.generate_cv_for_job("job-cv")
        with self.assertRaises(LLMUnavailableError):
            await self.engine.generate_pitch_for_job("job-cv")
        saved = await self.storage.get_job("job-cv")
        self.assertIsNone(saved.tailored_cv)
        self.assertIsNone(saved.pitch_draft)

    async def test_cv_prompt_never_receives_job_evaluation(self):
        gen = CVGenerator()
        job = qualified_job("job-cv-2")
        heuristic_match = MatchResult(score=90, verdict="EXCELENTE_MATCH", summary="x", pros=["PRO_HEURISTICO"], scored_by="heuristic")
        evaluation = json.dumps({"score": 83, "verdict": "BUEN_MATCH", "summary": "compatibilidad del 83%", "experience": [{"role": "x"}]})
        with patch.object(gen.llm, "generate", new_callable=AsyncMock, return_value=evaluation) as gen_mock:
            with self.assertRaises(LLMOutputError):
                await gen.generate_tailored_cv(job, ProfileContext(), heuristic_match)
            prompt = gen_mock.call_args.kwargs["prompt"]
            self.assertNotIn("PRO_HEURISTICO", prompt)

    async def test_api_returns_clear_errors_without_ai(self):
        from eros.api import app, engine as api_engine

        os.environ["EROS_API_KEY"] = API_KEY
        get_settings.cache_clear()
        await api_engine.storage.init_db()
        await api_engine.storage.save_profile_cache(ProfileContext())
        await api_engine.storage.save_job(qualified_job("job-api-noai"))

        unavailable = AsyncMock(side_effect=LLMUnavailableError("No hay GEMINI_API_KEY"))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            with patch.object(api_engine.cv_gen.llm, "generate", unavailable), \
                 patch.object(api_engine.pitch_gen.llm, "generate", unavailable):
                r_cv = await client.post("/api/cv/job-api-noai", headers=AUTH)
                r_pitch = await client.post("/api/pitch/job-api-noai", headers=AUTH)
        for r in (r_cv, r_pitch):
            self.assertEqual(r.status_code, 503, r.text)
            self.assertIn("IA no disponible", r.json()["detail"])

    def test_article_prompt_forbids_invented_metrics(self):
        from eros.content.article import SYSTEM_PROMPT_ES
        self.assertIn("NUNCA inventes", SYSTEM_PROMPT_ES)
        self.assertNotIn("-65% Latencia", SYSTEM_PROMPT_ES)


# ──────────────────────────────────────────────────────────────────────────────
# F1: Radar → artículo (antes Radar → post omnicanal)
# ──────────────────────────────────────────────────────────────────────────────

class TestRadarToArticle(unittest.IsolatedAsyncioTestCase):
    async def test_rescan_keeps_generated_status(self):
        tmp = tempfile.mkdtemp()
        try:
            storage = RadarStorage(db_path=os.path.join(tmp, "radar.db"))
            await storage.init_db()
            trend = TrendItem(id="t1", title="pgvector", url="https://x/t1", source=TrendSource.HACKER_NEWS,
                              summary="s", relevance_score=80, engineering_angle="a", detected_at="2026-11-01")
            self.assertTrue(await storage.save_trend(trend))
            await storage.update_status("t1", TrendStatus.GENERATED, post_id="post-9")
            self.assertFalse(await storage.save_trend(trend))
            saved = await storage.get_trend("t1")
            self.assertEqual(saved.status, TrendStatus.GENERATED)
            self.assertEqual(saved.post_id, "post-9")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    async def test_article_from_trend_passes_url_angle_and_marks_generated(self):
        from eros.api import app, article_generator, engine as api_engine, radar_storage
        from test_articles import english_json, spanish_json

        os.environ["EROS_API_KEY"] = API_KEY
        get_settings.cache_clear()
        await api_engine.storage.init_db()
        await api_engine.storage.save_profile_cache(ProfileContext())
        await radar_storage.init_db()
        await radar_storage.save_trend(TrendItem(
            id="t-api", title="Postgres 18", url="https://hn.example/pg18", source=TrendSource.HACKER_NEWS,
            summary="Novedades de Postgres 18", relevance_score=90, engineering_angle="Ángulo base", detected_at="2026-11-01",
        ))
        llm = AsyncMock(side_effect=[spanish_json(), english_json()])
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            with patch.object(article_generator.llm, "generate", llm):
                r = await client.post("/api/articles/generate", json={"trend_id": "t-api", "angle": "Mi ángulo"}, headers=AUTH)
                self.assertEqual(r.status_code, 202, r.text)
                for _ in range(100):
                    task = (await client.get(r.json()["status_url"], headers=AUTH)).json()
                    if task["status"] != "running":
                        break
                    await asyncio.sleep(0.02)
        self.assertEqual(task["status"], "done", task)
        self.assertEqual(task["result"]["trend_id"], "t-api")
        prompt = llm.call_args_list[0].kwargs["prompt"]
        for expected in ("https://hn.example/pg18", "Mi ángulo", "Ángulo base", "Novedades de Postgres 18"):
            self.assertIn(expected, prompt)
        self.assertEqual((await radar_storage.get_trend("t-api")).status, TrendStatus.GENERATED)

    async def test_social_publishing_routes_are_gone(self):
        from eros.api import app

        os.environ["EROS_API_KEY"] = API_KEY
        get_settings.cache_clear()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            gone = [
                await client.post("/api/content/generate", json={"topic": "SSR"}, headers=AUTH),
                await client.get("/api/content/posts", headers=AUTH),
                await client.post("/api/content/posts/post-1/publish", headers=AUTH),
                await client.get("/api/content/carousel/post-1/html", headers=AUTH),
                await client.post("/api/webhooks/n8n/callback", json={"post_id": "post-1", "status": "published"}),
                await client.post("/api/radar/trends/t1/generate", json={}, headers=AUTH),
            ]
        for r in gone:
            self.assertEqual(r.status_code, 404, f"{r.request.method} {r.request.url.path} sigue existiendo")


# ──────────────────────────────────────────────────────────────────────────────
# F6 + extras: escaneo asincrónico, stats, health, logs
# ──────────────────────────────────────────────────────────────────────────────

class TestAsyncScanAndOps(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ["EROS_API_KEY"] = API_KEY
        get_settings.cache_clear()

    async def test_scan_returns_202_and_single_running_task(self):
        from eros.api import app, engine as api_engine

        async def slow_scan():
            await asyncio.sleep(0.2)
            return {"total_found": 7, "new_jobs": 2}

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            with patch.object(api_engine, "run_scan", side_effect=slow_scan) as scan_mock:
                r1 = await client.post("/api/scan?evaluate=false", headers=AUTH)
                r2 = await client.post("/api/scan", headers=AUTH)
                self.assertEqual(r1.status_code, 202)
                self.assertEqual(r2.status_code, 202)
                self.assertEqual(r1.json()["task_id"], r2.json()["task_id"])
                self.assertFalse(r1.json()["already_running"])
                self.assertTrue(r2.json()["already_running"])

                status_url = r1.json()["status_url"]
                running = await client.get(status_url, headers=AUTH)
                self.assertEqual(running.json()["status"], "running")
                for _ in range(50):
                    done = await client.get(status_url, headers=AUTH)
                    if done.json()["status"] != "running":
                        break
                    await asyncio.sleep(0.05)
                self.assertEqual(scan_mock.call_count, 1)
            self.assertEqual(done.json()["status"], "done")
            self.assertEqual(done.json()["result"]["scanned"], 7)
            self.assertEqual(done.json()["result"]["new_jobs"], 2)

            missing = await client.get("/api/tasks/scan_nope", headers=AUTH)
            self.assertEqual(missing.status_code, 404)

    async def test_scan_notify_avisa_solo_los_buenos_por_telegram(self):
        from eros.api import app, engine as api_engine, telegram_bot
        from eros.models import MatchResult

        good = (qualified_job("notify-good", company="Buena"), MatchResult(score=99, verdict="EXCELENTE_MATCH", summary="Encaja."))
        weak = (qualified_job("notify-weak", company="Floja"), MatchResult(score=1, verdict="DESCARTAR", summary="No encaja."))

        async def finished(task_url, client):
            for _ in range(50):
                done = await client.get(task_url, headers=AUTH)
                if done.json()["status"] != "running":
                    return done.json()
                await asyncio.sleep(0.05)
            self.fail("la tarea no terminó")

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            with patch.object(api_engine, "run_scan", AsyncMock(return_value={"total_found": 2, "new_jobs": 2})), \
                 patch.object(api_engine, "evaluate_pending_jobs", AsyncMock(return_value=[good, weak])), \
                 patch.object(telegram_bot, "notify_match", AsyncMock(return_value=True)) as notify:
                quiet = await finished((await client.post("/api/scan?evaluate=true", headers=AUTH)).json()["status_url"], client)
                self.assertNotIn("notified_count", quiet["result"])
                notify.assert_not_awaited()

                loud = await finished((await client.post("/api/scan?evaluate=true&notify=true", headers=AUTH)).json()["status_url"], client)
                self.assertEqual(loud["result"]["notified_count"], 1)
                notify.assert_awaited_once_with(*good)

    async def test_stats_count_each_job_once(self):
        from eros.api import app, engine as api_engine

        await api_engine.storage.init_db()
        before = (await api_engine.storage.count_jobs())["total"]
        await api_engine.storage.save_job(qualified_job("stats-new", company="StatsNew"))
        await api_engine.storage.save_job(qualified_job("stats-disc", company="StatsDisc", status=JobStatus.DISCARDED))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            stats = (await client.get("/api/stats", headers=AUTH)).json()
        self.assertEqual(stats["total"], before + 2)
        self.assertGreaterEqual(stats["discarded_count"], 1)

    async def test_health_reports_database(self):
        from eros.api import app, engine as api_engine

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            ok = await client.get("/health")
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(ok.json()["database"], "ok")
            with patch.object(api_engine.storage, "ping", AsyncMock(return_value=False)):
                down = await client.get("/health")
            self.assertEqual(down.status_code, 503)

    def test_telegram_token_is_redacted_in_logs(self):
        from eros.logging_setup import RedactSecretsFilter

        record = logging.LogRecord(
            "httpx", logging.INFO, __file__, 1,
            "HTTP Request: POST https://api.telegram.org/bot123456789:AAH-abcdefghijklmnopqrstuvwxyz012345/getUpdates %s",
            ("ok",), None,
        )
        RedactSecretsFilter().filter(record)
        self.assertNotIn("AAH-abcdefghijklmnopqrstuvwxyz012345", record.getMessage())
        self.assertIn("bot[REDACTED]", record.getMessage())


if __name__ == "__main__":
    unittest.main()
