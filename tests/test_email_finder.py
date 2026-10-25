"""Tests unitarios para el servicio de resolución automática de correos de selección (EmailFinder)."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from eros.config import Settings
from eros.hunter.email_finder import EmailFinder
from eros.models import JobOffer, JobStatus, ProfileContext, MatchResult


class TestEmailFinder(unittest.IsolatedAsyncioTestCase):
    """Pruebas exhaustivas para EmailFinder y su cascada de resolución."""

    def setUp(self):
        self.settings_no_hunter = Settings(
            hunter_io_api_key="",
            database_path=":memory:",
        )
        self.settings_with_hunter = Settings(
            hunter_io_api_key="test_hunter_api_key_xyz",
            database_path=":memory:",
        )

    # ──────────────────────────────────────────────────────────────────────────
    # 1. Tests de extracción directa desde descripción
    # ──────────────────────────────────────────────────────────────────────────

    async def test_01_direct_extraction_from_description(self):
        finder = EmailFinder(self.settings_no_hunter)
        description = (
            "Buscamos desarrollador Full Stack Senior.\n"
            "Interesados enviar currículum a talent@fintech-latam.io para coordinar entrevista."
        )

        email, source = await finder.resolve_contact_email(
            company="Fintech Latam",
            job_url="https://linkedin.com/jobs/view/12345",
            description=description,
        )

        self.assertEqual(email, "talent@fintech-latam.io")
        self.assertEqual(source, "description")

    async def test_02_direct_extraction_ignores_blacklisted_domains(self):
        finder = EmailFinder(self.settings_no_hunter)
        description = (
            "Reportar errores a dev@sentry.io o noreply@domain.com.\n"
            "Postulaciones a rrhh@startech.co únicamente."
        )

        email, source = await finder.resolve_contact_email(
            company="StarTech",
            description=description,
        )

        self.assertEqual(email, "rrhh@startech.co")
        self.assertEqual(source, "description")

    # ──────────────────────────────────────────────────────────────────────────
    # 2. Tests de deducción de dominio y filtrado de portales genéricos
    # ──────────────────────────────────────────────────────────────────────────

    def test_03_extract_domain_from_url_filters_portals(self):
        finder = EmailFinder(self.settings_no_hunter)

        # Portales genéricos deben ignorarse
        self.assertIsNone(finder.extract_domain_from_url("https://www.linkedin.com/jobs/view/999"))
        self.assertIsNone(finder.extract_domain_from_url("https://getonboard.com/jobs/dev"))
        self.assertIsNone(finder.extract_domain_from_url("https://ar.computrabajo.com/ofertas/123"))
        self.assertIsNone(finder.extract_domain_from_url("https://remoteok.com/remote-jobs/777"))
        self.assertIsNone(finder.extract_domain_from_url("https://weworkremotely.com/jobs/888"))
        self.assertIsNone(finder.extract_domain_from_url("https://boards.greenhouse.io/stripe/jobs/1"))

        # Dominios corporativos reales deben extraerse correctamente
        self.assertEqual(
            finder.extract_domain_from_url("https://mercadolibre.com/careers/123"),
            "mercadolibre.com",
        )
        self.assertEqual(
            finder.extract_domain_from_url("https://jobs.spotify.com/positions/dev"),
            "spotify.com",
        )
        self.assertEqual(
            finder.extract_domain_from_url("https://careers.uala.com.ar/openings"),
            "uala.com.ar",
        )

    def test_04_infer_domain_from_company_name(self):
        finder = EmailFinder(self.settings_no_hunter)

        self.assertEqual(finder.infer_domain_from_company("Mercado Libre"), "mercadolibre.com")
        self.assertEqual(finder.infer_domain_from_company("Ualá"), "uala.com.ar")
        self.assertEqual(finder.infer_domain_from_company("Globant S.A."), "globant.com")
        self.assertEqual(finder.infer_domain_from_company("Acme Technologies Inc."), "acme.com")
        self.assertEqual(finder.infer_domain_from_company("Nova Corp"), "nova.com")

    # ──────────────────────────────────────────────────────────────────────────
    # 3. Tests de Hunter.io API (Mock)
    # ──────────────────────────────────────────────────────────────────────────

    @patch("httpx.AsyncClient.get")
    async def test_05_hunter_io_email_finder_with_recruiter(self, mock_get):
        finder = EmailFinder(self.settings_with_hunter)

        # Simular respuesta exitosa de /email-finder
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "first_name": "Martín",
                "last_name": "Gómez",
                "email": "martin.gomez@globant.com",
                "score": 85,
                "position": "Tech Recruiter",
            }
        }
        mock_get.return_value = mock_response

        email, source = await finder.resolve_contact_email(
            company="Globant",
            recruiter_name="Martín Gómez",
            job_url="https://linkedin.com/jobs/view/123",
        )

        self.assertEqual(email, "martin.gomez@globant.com")
        self.assertEqual(source, "hunter_io")
        mock_get.assert_called_once()
        call_url = str(mock_get.call_args[0][0])
        self.assertIn("api.hunter.io/v2/email-finder", call_url)

    @patch("httpx.AsyncClient.get")
    async def test_06_hunter_io_domain_search_generic_email(self, mock_get):
        finder = EmailFinder(self.settings_with_hunter)

        # Simular respuesta exitosa de /domain-search
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "domain": "acmecorp.com",
                "emails": [
                    {
                        "value": "jobs@acmecorp.com",
                        "type": "generic",
                        "confidence": 90,
                        "department": "hr",
                    }
                ],
            }
        }
        mock_get.return_value = mock_response

        email, source = await finder.resolve_contact_email(
            company="Acme Corp",
            job_url="https://weworkremotely.com/jobs/99",
        )

        self.assertEqual(email, "jobs@acmecorp.com")
        self.assertEqual(source, "hunter_io")
        mock_get.assert_called_once()
        call_url = str(mock_get.call_args[0][0])
        self.assertIn("api.hunter.io/v2/domain-search", call_url)

    @patch("httpx.AsyncClient.get")
    async def test_07_hunter_io_error_falls_back_to_guessing(self, mock_get):
        finder = EmailFinder(self.settings_with_hunter)

        # Simular error 500 en Hunter.io
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        with patch.object(finder, "check_dns_resolution", new_callable=AsyncMock) as mock_dns:
            mock_dns.return_value = True

            email, source = await finder.resolve_contact_email(
                company="Mercado Libre",
                job_url="https://linkedin.com/jobs/view/555",
            )

            self.assertEqual(email, "jobs@mercadolibre.com")
            self.assertEqual(source, "domain_guessing")

    # ──────────────────────────────────────────────────────────────────────────
    # 4. Tests de Candidate Generation y Domain Guessing
    # ──────────────────────────────────────────────────────────────────────────

    def test_08_candidate_generation_includes_recruiter_and_generics(self):
        finder = EmailFinder(self.settings_no_hunter)

        candidates = finder.generate_candidate_emails("techcorp.io", recruiter_name="Martín Gómez")

        self.assertIn("martin.gomez@techcorp.io", candidates)
        self.assertIn("mgomez@techcorp.io", candidates)
        self.assertIn("jobs@techcorp.io", candidates)
        self.assertIn("careers@techcorp.io", candidates)
        self.assertIn("talent@techcorp.io", candidates)
        self.assertIn("hiring@techcorp.io", candidates)
        self.assertIn("rrhh@techcorp.io", candidates)

    async def test_09_domain_guessing_resolves_when_dns_valid(self):
        finder = EmailFinder(self.settings_no_hunter)

        with patch.object(finder, "check_dns_resolution", new_callable=AsyncMock) as mock_dns:
            mock_dns.return_value = True

            email, source = await finder.resolve_contact_email(
                company="Ualá",
                job_url="https://remoteok.com/jobs/123",
            )

            self.assertEqual(email, "jobs@uala.com.ar")
            self.assertEqual(source, "domain_guessing")
            mock_dns.assert_called_once_with("uala.com.ar")

    async def test_10_domain_guessing_fails_when_dns_invalid(self):
        finder = EmailFinder(self.settings_no_hunter)

        with patch.object(finder, "check_dns_resolution", new_callable=AsyncMock) as mock_dns:
            mock_dns.return_value = False

            email, source = await finder.resolve_contact_email(
                company="NonExistentFakeCompanyXYZ12345",
            )

            self.assertIsNone(email)
            self.assertIsNone(source)

    # ──────────────────────────────────────────────────────────────────────────
    # 5. Tests de integración con Dispatcher y Engine
    # ──────────────────────────────────────────────────────────────────────────

    async def test_11_dispatcher_preview_resolves_email_on_the_fly(self):
        import shutil
        import tempfile
        from eros.hunter.dispatcher import JobApplicationDispatcher
        from eros.db.storage import JobStorage

        temp_dir = tempfile.mkdtemp()
        db_path = f"{temp_dir}/test_jobs.db"
        try:
            storage = JobStorage(db_path=db_path)
            await storage.init_db()

            job = JobOffer(
                id="job-resolver-test-1",
                source="linkedin",
                title="Backend Python Engineer",
                company="Mercado Libre",
                url="https://linkedin.com/jobs/view/111",
                description="Vacante para sumarse al equipo de pagos.",
                contact_email=None,
            )
            await storage.save_job(job)

            dispatcher = JobApplicationDispatcher(storage=storage)

            # Mockear check_dns_resolution en el email_finder del dispatcher
            with patch.object(dispatcher.email_finder, "check_dns_resolution", new_callable=AsyncMock) as mock_dns:
                mock_dns.return_value = True

                preview = await dispatcher.get_application_preview("job-resolver-test-1")

                self.assertTrue(preview.get("ok"))
                self.assertEqual(preview.get("contact_email"), "jobs@mercadolibre.com")

                # Verificar que se actualizó en la base de datos
                updated_job = await storage.get_job("job-resolver-test-1")
                self.assertIsNotNone(updated_job)
                self.assertEqual(updated_job.contact_email, "jobs@mercadolibre.com")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    async def test_12_engine_evaluation_resolves_email(self):
        import shutil
        import tempfile
        from eros.hunter.engine import HunterEngine
        from eros.db.storage import JobStorage

        temp_dir = tempfile.mkdtemp()
        db_path = f"{temp_dir}/test_jobs.db"
        try:
            storage = JobStorage(db_path=db_path)
            await storage.init_db()

            job = JobOffer(
                id="job-engine-eval-1",
                source="remotive",
                title="Full Stack Software Engineer",
                company="Mercado Libre",
                url="https://mercadolibre.com/careers/55",
                description="Buscamos ingeniero.",
                contact_email=None,
            )
            await storage.save_job(job)

            engine = HunterEngine(storage=storage)
            engine.matcher.evaluate = AsyncMock(return_value=MatchResult(
                score=88,
                verdict="APLICAR",
                summary="Buen calce",
                pros=["Stack coincidente"],
                cons=[],
                reason="Excelente perfil",
            ))

            with patch.object(engine.email_finder, "check_dns_resolution", new_callable=AsyncMock) as mock_dns:
                mock_dns.return_value = True

                res = await engine.evaluate_single_job("job-engine-eval-1")
                self.assertIsNotNone(res)
                eval_job, match = res
                self.assertEqual(eval_job.contact_email, "jobs@mercadolibre.com")

                saved = await storage.get_job("job-engine-eval-1")
                self.assertIsNotNone(saved)
                self.assertEqual(saved.contact_email, "jobs@mercadolibre.com")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    async def test_13_api_find_email_endpoint(self):
        import os
        import httpx
        from eros.api import app, engine

        os.environ["EROS_API_KEY"] = "eros_dev_test_secret_key"
        from eros.config import get_settings
        get_settings.cache_clear()

        job = JobOffer(
            id="job-api-find-1",
            source="getonboard",
            title="Senior Backend Go/Python",
            company="Ualá",
            url="https://getonboard.com/jobs/uala-1",
            description="Sumate a nuestro equipo.",
            contact_email=None,
        )
        await engine.storage.save_job(job)

        with patch.object(engine.email_finder, "check_dns_resolution", new_callable=AsyncMock) as mock_dns:
            mock_dns.return_value = True

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                headers = {"Authorization": "Bearer eros_dev_test_secret_key"}
                resp = await client.post("/api/jobs/job-api-find-1/find-email", headers=headers)
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertTrue(data.get("ok"))
                self.assertTrue(data.get("found"))
                self.assertEqual(data.get("contact_email"), "jobs@uala.com.ar")
                self.assertEqual(data.get("source"), "domain_guessing")

                # Verificar persistencia en base de datos
                db_job = await engine.storage.get_job("job-api-find-1")
                self.assertIsNotNone(db_job)
                self.assertEqual(db_job.contact_email, "jobs@uala.com.ar")


if __name__ == "__main__":
    unittest.main()
