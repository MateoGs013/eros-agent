import unittest
import tempfile
import shutil
import re
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
            name="Mateo Barale",
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
            candidate_name="Mateo Barale",
            candidate_email="mateo@example.com",
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
        job = JobOffer(
            id="job-email-2",
            source="linkedin",
            title="Frontend Specialist",
            company="Acme Corp",
            url="https://linkedin.com/jobs/view/2",
            contact_email="recruiting@acme.corp",
            pitch_draft='{"cover_letter": "Estimado equipo de Acme...", "subject": "Postulacion Mateo"}',
        )
        await self.storage.save_job(job)

        preview = await self.dispatcher.get_application_preview("job-email-2")
        self.assertTrue(preview["ok"])
        self.assertEqual(preview["contact_email"], "recruiting@acme.corp")
        self.assertIn("Mateo", preview["subject"])
        self.assertIn("Acme", preview["body"])
        self.assertFalse(self._has_emojis(preview["subject"]))
        self.assertFalse(self._has_emojis(preview["body"]))

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


if __name__ == "__main__":
    unittest.main()
