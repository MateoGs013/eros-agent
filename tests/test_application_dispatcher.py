import unittest
import tempfile
import shutil
import re
import base64
import email
from unittest.mock import AsyncMock, MagicMock, patch

from eros.models import JobOffer, ProfileContext, ProjectSummary
from eros.db.storage import JobStorage
from eros.hunter.filters import extract_contact_email
from eros.hunter.dispatcher import JobApplicationDispatcher
from eros.config import Settings


class TestJobApplicationDispatcher(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = f"{self.temp_dir}/test_jobs.db"
        self.storage = JobStorage(db_path=self.db_path)
        await self.storage.init_db()

        self.sample_profile = ProfileContext(
            name="Mateo Sonzogni",
            role="Full Stack & Creative Engineer",
            tech_stack=["Vue 3", "Nuxt 3", "TypeScript", "Node.js", "Tailwind CSS", "PostgreSQL"],
            projects=[
                ProjectSummary(slug="portfolio", title="Portafolio Profesional", summary="Web moderna con Nuxt", techs=["Nuxt", "Vue"]),
                ProjectSummary(slug="eros-os", title="Eros Career OS", summary="Agente autonomo", techs=["Python", "FastAPI"])
            ],
            languages="Ingles C1 / Espanol Nativo",
            timezone="UTC-3"
        )

        self.settings = Settings(
            database_path=self.db_path,
            candidate_name="Mateo Sonzogni",
            candidate_email="mateogabus@gmail.com",
            n8n_application_webhook_url="https://n8n.example.com/webhook/test-app",
        )

        self.dispatcher = JobApplicationDispatcher(storage=self.storage)
        self.dispatcher.settings = self.settings

    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _has_emojis(self, text: str) -> bool:
        emoji_pattern = re.compile(
            r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]",
            flags=re.UNICODE
        )
        return bool(emoji_pattern.search(text))

    def test_01_extract_contact_email_valid_and_filters(self):
        # Valid extractions
        text1 = "Para postularte envia tu CV a talento@startup.io indicando remuneracion pretendida."
        self.assertEqual(extract_contact_email(text1), "talento@startup.io")

        text2 = "Contact hiring lead at jobs@company.tech or careers@company.tech"
        self.assertEqual(extract_contact_email(text2), "jobs@company.tech")

        # Exclusions: tracking / technical / bogus
        text_sentry = "Send errors to o123@ingest.sentry.io or noreply@mailer.com"
        self.assertIsNone(extract_contact_email(text_sentry))

        text_img = "Download banner at icon@2x.png or logo@3x.jpg"
        self.assertIsNone(extract_contact_email(text_img))

    async def test_02_job_model_and_storage_contact_email(self):
        job = JobOffer(
            id="job-email-1",
            source="getonboard",
            title="Senior Full Stack Engineer",
            company="Globex",
            url="https://example.com/job/1",
            contact_email="careers@globex.com",
            description="Buscamos Senior Full Stack.",
        )
        await self.storage.save_job(job)

        saved = await self.storage.get_job("job-email-1")
        self.assertIsNotNone(saved)
        self.assertEqual(saved.contact_email, "careers@globex.com")
        self.assertIsNone(saved.applied_at)

        # Update contact email
        await self.storage.update_job_contact_email("job-email-1", "hr@globex.com")
        updated = await self.storage.get_job("job-email-1")
        self.assertEqual(updated.contact_email, "hr@globex.com")

    async def test_03_application_preview_generation(self):
        # Job en inglés
        job_en = JobOffer(
            id="job-email-2",
            source="linkedin",
            title="Frontend Specialist",
            company="Acme Corp",
            url="https://linkedin.com/jobs/view/2",
            contact_email="recruiting@acme.corp",
            pitch_draft='{"cover_letter": "I would love to join your team...", "subject": "Application Mateo"}',
        )
        await self.storage.save_job(job_en)

        preview = await self.dispatcher.get_application_preview("job-email-2")
        self.assertTrue(preview["ok"])
        self.assertEqual(preview["contact_email"], "recruiting@acme.corp")
        self.assertEqual(preview["cv_filename"], "CV_Mateo_Sonzogni.pdf")
        self.assertTrue(preview.get("has_pdf_attachment"))
        self.assertIn("Mateo", preview["subject"])
        self.assertIn("Acme", preview["body"])
        self.assertIn("I have attached my tailored single-page ATS Resume (PDF) for your review.", preview["body"])
        self.assertFalse(self._has_emojis(preview["subject"]))
        self.assertFalse(self._has_emojis(preview["body"]))

        # Job en español
        job_es = JobOffer(
            id="job-email-es",
            source="getonboard",
            title="Desarrollador Full Stack Python",
            company="Startup Latinoamericana",
            url="https://example.com/job/latam",
            description="Requisitos: experiencia sólida con FastAPI y Vue 3.",
            contact_email="talento@startup.io",
        )
        await self.storage.save_job(job_es)
        preview_es = await self.dispatcher.get_application_preview("job-email-es")
        self.assertTrue(preview_es["ok"])
        self.assertIn("Adjunto mi Currículum Vitae en formato Harvard ATS (PDF de 1 página) para su revisión.", preview_es["body"])

    async def test_04_dispatch_via_webhook(self):
        job = JobOffer(
            id="job-email-3",
            source="getonboard",
            title="Python Developer",
            company="Initech",
            url="https://example.com/job/3",
            contact_email="jobs@initech.com",
            pitch_draft='{"cover_letter": "Presento mi candidatura.", "subject": "Postulacion Python"}',
        )
        await self.storage.save_job(job)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "OK"

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_http:
            mock_http.return_value = mock_resp
            result = await self.dispatcher.dispatch_application(
                job_id="job-email-3",
                to_email="jobs@initech.com",
                custom_subject="Postulacion a Python Developer",
                custom_body="Presento mi candidatura para la vacante de Python Developer.",
                channel="n8n"
            )

            self.assertTrue(result["ok"])
            self.assertEqual(result["provider"], "n8n")
            mock_http.assert_called_once()
            called_payload = mock_http.call_args[1]["json"]
            self.assertEqual(called_payload["event"], "job.application")
            self.assertEqual(called_payload["recipient_email"], "jobs@initech.com")
            self.assertEqual(called_payload["cv_filename"], "CV_Mateo_Sonzogni.pdf")
            self.assertIn("cv_pdf_base64", called_payload)
            self.assertTrue(len(called_payload["cv_pdf_base64"]) > 0)
            decoded_pdf = base64.b64decode(called_payload["cv_pdf_base64"])
            self.assertTrue(decoded_pdf.startswith(b"%PDF"))

        # Verify job marked as applied
        applied_job = await self.storage.get_job("job-email-3")
        self.assertEqual(applied_job.status.value, "applied")
        self.assertIsNotNone(applied_job.applied_at)

    async def test_05_dispatch_local_mode(self):
        job = JobOffer(
            id="job-email-4",
            source="workana",
            title="Nuxt Engineer",
            company="Creative Lab",
            url="https://example.com/job/4",
            contact_email="apply@creativelab.io",
            pitch_draft='{"cover_letter": "Estimado equipo...", "subject": "Postulacion Nuxt"}',
        )
        await self.storage.save_job(job)

        result = await self.dispatcher.dispatch_application(
            job_id="job-email-4",
            to_email="apply@creativelab.io",
            custom_subject="Postulacion Nuxt Engineer",
            custom_body="Estimado equipo...",
            channel="local"
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "local_registered")

        saved = await self.storage.get_job("job-email-4")
        self.assertEqual(saved.status.value, "applied")
        self.assertIsNotNone(saved.applied_at)

    async def test_06_dispatch_via_smtp_attaches_pdf(self):
        """Verifica que el despacho SMTP directo adjunte CV_Mateo_Sonzogni.pdf con bytes %PDF."""
        job = JobOffer(
            id="job-email-smtp",
            source="linkedin",
            title="Senior Python Backend Engineer",
            company="Globex Corporation",
            url="https://example.com/job/smtp",
            contact_email="hiring@globex.com",
            pitch_draft='{"cover_letter": "I would love to join your engineering team.", "subject": "Senior Python Backend Engineer"}',
        )
        await self.storage.save_job(job)

        self.dispatcher.settings.smtp_host = "smtp.example.com"
        self.dispatcher.settings.smtp_port = 587
        self.dispatcher.settings.smtp_user = "user"
        self.dispatcher.settings.smtp_pass = "pass"

        sent_messages = []

        class MockSMTP:
            def __init__(self, host, port, timeout=15):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

            def starttls(self, context=None):
                pass

            def login(self, user, pwd):
                pass

            def sendmail(self, from_addr, to_addrs, msg_str):
                sent_messages.append((from_addr, to_addrs, msg_str))

        with patch("smtplib.SMTP", side_effect=MockSMTP):
            res = await self.dispatcher.dispatch_application(
                job_id="job-email-smtp",
                to_email="hiring@globex.com",
                confirmed=True,
                channel="smtp",
            )
            self.assertTrue(res["ok"])
            self.assertEqual(res["provider"], "smtp")
            self.assertEqual(len(sent_messages), 1)
            from_addr, to_addrs, raw_msg = sent_messages[0]
            self.assertEqual(to_addrs, ["hiring@globex.com"])

            # Parsear mensaje MIME
            parsed = email.message_from_string(raw_msg)

            # Verificar adjunto PDF
            attachments = [p for p in parsed.walk() if p.get_content_disposition() == "attachment"]
            self.assertEqual(len(attachments), 1)
            pdf_part = attachments[0]
            self.assertEqual(pdf_part.get_filename(), "CV_Mateo_Sonzogni.pdf")
            self.assertEqual(pdf_part.get_content_type(), "application/pdf")
            decoded_pdf = pdf_part.get_payload(decode=True)
            self.assertTrue(decoded_pdf.startswith(b"%PDF"))

            # Verificar cuerpo de texto y links
            text_parts = [p for p in parsed.walk() if p.get_content_type() == "text/plain"]
            self.assertTrue(len(text_parts) > 0)
            body_text = text_parts[0].get_payload(decode=True).decode("utf-8")
            self.assertIn("I have attached my tailored single-page ATS Resume (PDF) for your review.", body_text)
            self.assertIn("https://mateogs.tech", body_text)

    def test_07_render_pdf_strict_single_page_a4(self):
        """Verifica que render_pdf genere bytes válidos que empiezan con %PDF y exactamente 1 página A4."""
        import fitz
        from eros.hunter.cv_generator import CVGenerator

        gen = CVGenerator()
        job = JobOffer(
            id="job-pdf-single-page",
            source="linkedin",
            title="Full Stack Software Engineer",
            company="Acme Corp",
            url="https://example.com/job/pdf",
            description="Python, FastAPI, Vue 3, PostgreSQL",
        )
        cv = gen._build_fallback_cv(self.sample_profile, job)
        pdf_bytes = gen.render_pdf(cv)

        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 1000)

        # Verificar dimensiones y cantidad de páginas con PyMuPDF
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        self.assertEqual(len(doc), 1, "El PDF Harvard ATS debe ser exactamente de 1 página A4")
        page = doc[0]
        # A4 estándar: 595.28 x 841.89 puntos
        self.assertAlmostEqual(page.rect.width, 595.28, delta=1.0)
        self.assertAlmostEqual(page.rect.height, 841.89, delta=1.0)
        text = page.get_text()
        self.assertIn("Mateo", text)
        self.assertIn("Ynara", text)

    async def test_08_api_get_cv_pdf_endpoint(self):
        """Verifica que los endpoints GET /api/cv/{id}/pdf y /api/jobs/{id}/cv/pdf respondan con media_type application/pdf."""
        import httpx
        from eros.api import app, engine

        await engine.initialize()
        job = JobOffer(
            id="job-pdf-api-test",
            source="linkedin",
            title="Cloud Architect",
            company="SkyTech",
            url="https://example.com/job/sky",
            description="Docker, Linux, FastAPI, Python",
        )
        await engine.storage.save_job(job)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/cv/job-pdf-api-test/pdf")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers["content-type"], "application/pdf")
            self.assertIn("CV_Mateo_Sonzogni.pdf", resp.headers["content-disposition"])
            self.assertTrue(resp.content.startswith(b"%PDF"))

            # Alias /api/jobs/{id}/cv/pdf
            resp_alias = await client.get("/api/jobs/job-pdf-api-test/cv/pdf")
            self.assertEqual(resp_alias.status_code, 200)
            self.assertEqual(resp_alias.headers["content-type"], "application/pdf")
            self.assertTrue(resp_alias.content.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
