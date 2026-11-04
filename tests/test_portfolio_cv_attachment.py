"""Eros adjunta solo el CV que manda el portafolio (nov-2026).

El admin del portafolio arma el CV Harvard ATS desde su base, lo imprime a PDF y lo manda en
`apply-email` como `cv`. Eros lo adjunta tal cual (n8n y SMTP) y nunca arma ni adjunta uno propio:
sin `cv` responde `cv_required`, con uno roto `invalid_cv`, y en ninguno de los dos casos toma la
marca de envío ni llama al proveedor. Telegram ya no postula. Nada sale a la red.
"""

import base64
import hashlib
import os
import shutil
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from eros.config import Settings, get_settings
from eros.db.storage import JobStorage
from eros.hunter.attached_cv import MAX_PDF_BYTES, AttachedCVError, parse_attached_cv
from eros.hunter.dispatcher import JobApplicationDispatcher
from eros.models import JobOffer, JobStatus, ProfileContext
from portfolio_cv import PORTFOLIO_FILENAME, PORTFOLIO_PDF, portfolio_cv

API_KEY = "eros_cv_attach_test_key_0123456789"
AUTH = {"Authorization": f"Bearer {API_KEY}"}


def job(job_id: str) -> JobOffer:
    return JobOffer(
        id=job_id,
        source="remotive",
        external_id=job_id,
        title="Frontend Engineer",
        company="Example Labs",
        url=f"https://remotive.example/jobs/{job_id}",
        description="Remote role. Vue 3 and TypeScript.",
        pitch_draft='{"cover_letter": "Hola."}',
    )


class ParseAttachedCvTest(unittest.TestCase):
    def code_of(self, raw) -> str:
        with self.assertRaises(AttachedCVError) as ctx:
            parse_attached_cv(raw)
        return ctx.exception.code

    def test_valid_cv_keeps_bytes_name_and_text(self):
        cv = parse_attached_cv(portfolio_cv())
        self.assertEqual(cv.pdf_bytes, PORTFOLIO_PDF)
        self.assertEqual(cv.filename, PORTFOLIO_FILENAME)
        self.assertEqual(cv.sha256, hashlib.sha256(PORTFOLIO_PDF).hexdigest())
        self.assertEqual(base64.b64decode(cv.pdf_base64), PORTFOLIO_PDF)
        self.assertEqual(cv.lang, "es")
        self.assertAlmostEqual(cv.height_mm, 256.4)

    def test_missing_cv_is_cv_required(self):
        self.assertEqual(self.code_of(None), "cv_required")

    def test_broken_cvs_are_invalid(self):
        not_pdf = b"<html>no soy un PDF</html>"
        cases = {
            "no es objeto": "texto",
            "nombre con ruta": portfolio_cv(filename="../../etc/passwd.pdf"),
            "nombre sin .pdf": portfolio_cv(filename="CV.exe"),
            "base64 roto": portfolio_cv(pdf_base64="%%%no-base64%%%"),
            "no es PDF": portfolio_cv(
                pdf_base64=base64.b64encode(not_pdf).decode(), sha256=hashlib.sha256(not_pdf).hexdigest()
            ),
            "sha distinto": portfolio_cv(sha256="0" * 64),
            "sin sha": portfolio_cv(sha256=None),
            "texto vacío": portfolio_cv(text="   "),
            "texto enorme": portfolio_cv(text="x" * 20_001),
        }
        for name, raw in cases.items():
            with self.subTest(name):
                self.assertEqual(self.code_of(raw), "invalid_cv")

    def test_pdf_over_two_megabytes_is_invalid(self):
        big = b"%PDF-1.4\n" + b"0" * MAX_PDF_BYTES
        raw = portfolio_cv(pdf_base64=base64.b64encode(big).decode(), sha256=hashlib.sha256(big).hexdigest())
        self.assertEqual(self.code_of(raw), "invalid_cv")


class DispatchNeedsPortfolioCvTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.mkdtemp()
        self.storage = JobStorage(db_path=os.path.join(self.tmp, "cv.db"))
        await self.storage.init_db()
        await self.storage.save_profile_cache(ProfileContext())
        await self.storage.save_job(job("job-cv-1"))
        self.dispatcher = JobApplicationDispatcher(storage=self.storage)
        self.dispatcher.settings = Settings(
            database_path=self.storage.db_path,
            n8n_application_webhook_url="https://n8n.example/webhook/apply",
        )

    async def asyncTearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    async def send(self, **kw):
        args = dict(job_id="job-cv-1", to_email="rrhh@example.com", custom_subject="Postulación", custom_body="Cuerpo", confirmed=True)
        args.update(kw)
        return await self.dispatcher.dispatch_application(**args)

    async def assert_untouched(self):
        saved = await self.storage.get_job("job-cv-1")
        self.assertIsNone(saved.send_state, "Sin un CV válido no se toma la marca de envío")
        self.assertIsNone(saved.applied_at)
        self.assertNotEqual(saved.status, JobStatus.APPLIED)

    async def test_without_cv_nothing_is_sent(self):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
            res = await self.send()
            post.assert_not_called()
        self.assertFalse(res["ok"])
        self.assertEqual(res["error_code"], "cv_required")
        await self.assert_untouched()

    async def test_invalid_cv_nothing_is_sent(self):
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
            res = await self.send(cv=portfolio_cv(sha256="f" * 64))
            post.assert_not_called()
        self.assertEqual(res["error_code"], "invalid_cv")
        await self.assert_untouched()

    async def test_never_builds_its_own_cv(self):
        """El CVGenerator de Eros no participa del envío: si se lo llama, la prueba falla."""
        boom = MagicMock(side_effect=AssertionError("Eros armó su propio CV"))
        ok = MagicMock(status_code=200, text="OK")
        with patch("eros.hunter.cv_generator.CVGenerator.render_pdf", boom), \
             patch("eros.hunter.cv_generator.CVGenerator.render_plain_text", boom), \
             patch("eros.hunter.cv_generator.CVGenerator._build_fallback_cv", boom), \
             patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=ok) as post:
            res = await self.send(cv=portfolio_cv())
        self.assertTrue(res["ok"], res)
        boom.assert_not_called()
        payload = post.call_args.kwargs["json"]
        self.assertEqual(base64.b64decode(payload["cv_pdf_base64"]), PORTFOLIO_PDF)
        self.assertEqual(payload["cv_sha256"], hashlib.sha256(PORTFOLIO_PDF).hexdigest())
        self.assertIsNone(payload["cv_data"])
        self.assertIsNone(payload["cv_html_url"])
        # El job no guarda un CV de Eros por enviar.
        self.assertIsNone((await self.storage.get_job("job-cv-1")).tailored_cv)

    async def test_retry_after_unknown_sends_the_new_cv(self):
        """Tras un envío cortado, el reintento forzado adjunta el CV que llega en ese pedido."""
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=httpx.ReadTimeout("timeout")):
            res = await self.send(cv=portfolio_cv())
        self.assertEqual(res["error_code"], "send_outcome_unknown")

        other_pdf = PORTFOLIO_PDF + b"% segunda version\n"
        other = portfolio_cv(
            pdf_base64=base64.b64encode(other_pdf).decode(), sha256=hashlib.sha256(other_pdf).hexdigest()
        )
        ok = MagicMock(status_code=200, text="OK")
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=ok) as post:
            res = await self.send(cv=other, force_retry=True)
        self.assertTrue(res["ok"], res)
        self.assertEqual(base64.b64decode(post.call_args.kwargs["json"]["cv_pdf_base64"]), other_pdf)
        self.assertEqual(post.call_args.kwargs["headers"]["Idempotency-Key"], "apply-job-cv-1")


class ApplyEmailApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_api_answers_422_cv_required_and_invalid_cv(self):
        from eros.api import app, engine as api_engine

        os.environ["EROS_API_KEY"] = API_KEY
        get_settings.cache_clear()
        await api_engine.storage.init_db()
        await api_engine.storage.save_profile_cache(ProfileContext())
        await api_engine.storage.save_job(job("job-cv-api"))
        settings = api_engine.app_dispatcher.settings
        old_url = settings.n8n_application_webhook_url
        settings.n8n_application_webhook_url = "https://n8n.example/webhook/apply"
        body = {"to_email": "rrhh@example.com", "subject": "Postulación", "body": "Cuerpo", "confirmed": True, "channel": "n8n"}
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                missing = await client.post("/api/jobs/job-cv-api/apply-email", json=body, headers=AUTH)
                broken = await client.post(
                    "/api/jobs/job-cv-api/apply-email", json={**body, "cv": portfolio_cv(sha256="a" * 64)}, headers=AUTH
                )
        finally:
            settings.n8n_application_webhook_url = old_url
        self.assertEqual(missing.status_code, 422, missing.text)
        self.assertEqual(missing.json()["error_code"], "cv_required")
        self.assertEqual(broken.status_code, 422, broken.text)
        self.assertEqual(broken.json()["error_code"], "invalid_cv")
        saved = await api_engine.storage.get_job("job-cv-api")
        self.assertIsNone(saved.send_state)
        self.assertIsNone(saved.applied_at)


class TelegramDoesNotApplyTest(unittest.IsolatedAsyncioTestCase):
    async def test_apply_buttons_point_to_the_admin(self):
        from eros.bot.telegram import TelegramBot

        bot = TelegramBot()
        bot.engine = MagicMock()
        bot.engine.app_dispatcher.dispatch_application = AsyncMock()
        bot.send_message = AsyncMock(return_value=True)
        with patch("httpx.AsyncClient.post", new_callable=AsyncMock):
            for data in ("apply_email:job-1", "confirm_apply:job-1"):
                await bot._handle_callback("cb", 7, data)

        bot.engine.app_dispatcher.dispatch_application.assert_not_awaited()
        self.assertEqual(bot.send_message.await_count, 2)
        for call in bot.send_message.await_args_list:
            self.assertIn("Postulá desde el admin", call.args[1])
            self.assertIn("No se envió nada", call.args[1])


if __name__ == "__main__":
    unittest.main()
