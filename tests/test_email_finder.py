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
        self.assertEqual(source, "posting")

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
        self.assertEqual(source, "posting")

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
        self.assertEqual(source, "hunter")
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
        self.assertEqual(source, "hunter")
        mock_get.assert_called_once()
        call_url = str(mock_get.call_args[0][0])
        self.assertIn("api.hunter.io/v2/domain-search", call_url)

    @patch("httpx.AsyncClient.get")
    async def test_07_hunter_io_error_never_falls_back_to_guessing(self, mock_get):
        finder = EmailFinder(self.settings_with_hunter)

        # Simular error 500 en Hunter.io
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        email, source = await finder.resolve_contact_email(
            company="Mercado Libre",
            job_url="https://linkedin.com/jobs/view/555",
        )

        # Sin un correo publicado ni encontrado por Hunter.io, no se arma ninguno
        self.assertIsNone(email)
        self.assertIsNone(source)

    # ──────────────────────────────────────────────────────────────────────────
    # 4. Nunca se adivinan correos
    # ──────────────────────────────────────────────────────────────────────────

    def test_08_no_guessing_api_left(self):
        finder = EmailFinder(self.settings_no_hunter)
        self.assertFalse(hasattr(finder, "generate_candidate_emails"))
        self.assertFalse(hasattr(finder, "check_dns_resolution"))

    async def test_09_known_company_without_published_email_returns_nothing(self):
        finder = EmailFinder(self.settings_no_hunter)

        email, source = await finder.resolve_contact_email(
            company="Ualá",
            job_url="https://remoteok.com/jobs/123",
        )

        self.assertIsNone(email)
        self.assertIsNone(source)

    async def test_10_placeholder_company_never_infers_domain(self):
        finder = EmailFinder(self.settings_with_hunter)

        self.assertIsNone(finder.infer_domain_from_company("Empresa Confidencial"))
        self.assertIsNone(finder.infer_domain_from_company("Confidential"))
        self.assertIsNone(finder.infer_domain_from_company("Stealth Startup"))
        self.assertTrue(finder.is_placeholder_company("Importante Empresa"))
        self.assertFalse(finder.is_placeholder_company("Mercado Libre"))

        # Con Hunter.io configurado, no se consulta ningún dominio inventado
        with patch.object(finder, "query_hunter_io", new_callable=AsyncMock) as mock_hunter:
            email, source = await finder.resolve_contact_email(
                company="Empresa Confidencial",
                job_url="https://ar.computrabajo.com/ofertas/1",
            )
            mock_hunter.assert_not_called()
        self.assertIsNone(email)
        self.assertIsNone(source)

    async def test_10b_company_site_email_only_same_domain(self):
        finder = EmailFinder(self.settings_no_hunter)

        page = MagicMock()
        page.status_code = 200
        page.text = "<p>Escribinos a careers@acme.io o a soporte@otro-proveedor.com</p>"
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=page):
            email, source = await finder.resolve_contact_email(
                company="Acme",
                job_url="https://jobs.acme.io/openings/42",
            )
        self.assertEqual(email, "careers@acme.io")
        self.assertEqual(source, "company_site")

        page.text = "<p>Contacto: info@otro-proveedor.com</p>"
        with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=page):
            email, source = await finder.resolve_contact_email(
                company="Acme",
                job_url="https://jobs.acme.io/openings/42",
            )
        self.assertIsNone(email)
        self.assertIsNone(source)

    # ──────────────────────────────────────────────────────────────────────────
    # 5. Tests de integración con Dispatcher y Engine
    # ──────────────────────────────────────────────────────────────────────────

    async def test_11_dispatcher_preview_never_guesses_and_flags_manual_email(self):
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
            from eros.integrations.llm import LLMUnavailableError
            dispatcher.pitch_gen.generate_pitch = AsyncMock(side_effect=LLMUnavailableError("sin IA"))

            preview = await dispatcher.get_application_preview("job-resolver-test-1")

            self.assertTrue(preview.get("ok"))
            self.assertEqual(preview.get("contact_email"), "")
            self.assertIsNone(preview.get("contact_email_source"))
            self.assertFalse(preview.get("contact_email_verified"))
            self.assertTrue(preview.get("requires_manual_email"))
            self.assertEqual(preview.get("pitch_source"), "template")

            updated_job = await storage.get_job("job-resolver-test-1")
            self.assertIsNone(updated_job.contact_email)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    async def test_12_engine_evaluation_stores_email_with_source(self):
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
                verdict="EXCELENTE_MATCH",
                summary="Buen calce",
                pros=["Stack coincidente"],
                cons=[],
            ))

            with patch.object(engine.email_finder, "fetch_company_site_email", new_callable=AsyncMock) as mock_site:
                mock_site.return_value = "talento@mercadolibre.com"
                res = await engine.evaluate_single_job("job-engine-eval-1")
                self.assertIsNotNone(res)
                eval_job, match = res
                self.assertEqual(eval_job.contact_email, "talento@mercadolibre.com")

                saved = await storage.get_job("job-engine-eval-1")
                self.assertEqual(saved.contact_email, "talento@mercadolibre.com")
                self.assertEqual(saved.contact_email_source, "company_site")

            # Sin correo publicado en ningún lado, no se guarda nada
            job2 = JobOffer(
                id="job-engine-eval-2",
                source="remotive",
                title="Backend Engineer",
                company="Empresa Confidencial",
                url="https://remotive.com/jobs/2",
                description="Buscamos ingeniero.",
            )
            await storage.save_job(job2)
            await engine.evaluate_single_job("job-engine-eval-2")
            saved2 = await storage.get_job("job-engine-eval-2")
            self.assertIsNone(saved2.contact_email)
            self.assertIsNone(saved2.contact_email_source)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    async def test_13_api_find_email_endpoint(self):
        import os
        import httpx
        from eros.api import app, engine

        os.environ["EROS_API_KEY"] = "eros_dev_test_secret_key"
        from eros.config import get_settings
        get_settings.cache_clear()

        await engine.storage.init_db()
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
        job_posted = JobOffer(
            id="job-api-find-2",
            source="getonboard",
            title="Frontend Vue",
            company="Ualá",
            url="https://getonboard.com/jobs/uala-2",
            description="Mandá tu CV a seleccion@uala.com.ar",
            contact_email=None,
        )
        await engine.storage.save_job(job_posted)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            headers = {"Authorization": "Bearer eros_dev_test_secret_key"}

            # Sin correo publicado: no encuentra ni adivina
            resp = await client.post("/api/jobs/job-api-find-1/find-email", headers=headers)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data.get("ok"))
            self.assertFalse(data.get("found"))
            self.assertIsNone(data.get("contact_email"))
            self.assertIsNone(data.get("contact_email_source"))
            db_job = await engine.storage.get_job("job-api-find-1")
            self.assertIsNone(db_job.contact_email)

            # Publicado en el aviso: lo encuentra con su fuente
            resp = await client.post("/api/jobs/job-api-find-2/find-email", headers=headers)
            data = resp.json()
            self.assertTrue(data.get("found"))
            self.assertEqual(data.get("contact_email"), "seleccion@uala.com.ar")
            self.assertEqual(data.get("source"), "posting")
            self.assertEqual(data.get("contact_email_source"), "posting")

            # Correo escrito a mano: queda con fuente manual y find-email no lo pisa
            resp = await client.patch(
                "/api/jobs/job-api-find-2/contact-email",
                json={"contact_email": "Mateo.Contacto@uala.com.ar"},
                headers=headers,
            )
            self.assertEqual(resp.json().get("contact_email_source"), "manual")
            resp = await client.post("/api/jobs/job-api-find-2/find-email", headers=headers)
            self.assertEqual(resp.json().get("contact_email"), "mateo.contacto@uala.com.ar")
            self.assertEqual(resp.json().get("contact_email_source"), "manual")

            # La lista de vacantes expone la fuente
            resp = await client.get("/api/jobs/job-api-find-2", headers=headers)
            self.assertEqual(resp.json()["data"]["contact_email_source"], "manual")

    async def test_14_legacy_guessed_emails_are_cleared_on_migration(self):
        import shutil
        import tempfile
        import aiosqlite
        from eros.db.storage import JobStorage

        temp_dir = tempfile.mkdtemp()
        db_path = f"{temp_dir}/legacy.db"
        try:
            storage = JobStorage(db_path=db_path)
            await storage.init_db()
            rows = [
                # adivinado a partir de un genérico
                ("legacy-1", "Empresa Confidencial", "https://ar.computrabajo.com/x", "Sin correo", "jobs@empresaconfidencial.com", "saved", None),
                # publicado en el aviso
                ("legacy-2", "Acme", "https://remotive.com/x", "Escribí a hr@acme.io", "hr@acme.io", "saved", None),
                # adivinado pero ya postulado: queda como historial, con fuente desconocida
                ("legacy-3", "Globex", "https://remotive.com/y", "Sin correo", "jobs@globex.com", "applied", "2026-10-01T00:00:00+00:00"),
                # de origen desconocido (no tiene forma de adivinado)
                ("legacy-4", "Initech", "https://remotive.com/z", "Sin correo", "peter@initech.com", "saved", None),
            ]
            async with aiosqlite.connect(db_path) as db:
                for job_id, company, url, desc, email, status, applied_at in rows:
                    await db.execute(
                        "INSERT INTO jobs (id, source, external_id, title, company, url, description, found_at, status, contact_email, applied_at) "
                        "VALUES (?, 'remotive', ?, 'Dev', ?, ?, ?, '2026-10-01', ?, ?, ?)",
                        (job_id, job_id, company, url, desc, status, email, applied_at),
                    )
                await db.commit()

            await storage.init_db()

            j1 = await storage.get_job("legacy-1")
            j2 = await storage.get_job("legacy-2")
            j3 = await storage.get_job("legacy-3")
            j4 = await storage.get_job("legacy-4")
            self.assertIsNone(j1.contact_email)
            self.assertEqual((j2.contact_email, j2.contact_email_source), ("hr@acme.io", "posting"))
            self.assertEqual((j3.contact_email, j3.contact_email_source), ("jobs@globex.com", "unknown"))
            self.assertEqual((j4.contact_email, j4.contact_email_source), ("peter@initech.com", "unknown"))
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
