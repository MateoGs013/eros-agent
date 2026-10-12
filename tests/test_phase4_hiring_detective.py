import unittest
import asyncio
import tempfile
import shutil
import re
from unittest.mock import AsyncMock, MagicMock
from bs4 import BeautifulSoup

from eros.models import JobOffer, MatchResult, ProfileContext, ProjectSummary
from eros.db.storage import JobStorage
from eros.hunter.sources.linkedin import LinkedInJobsSource
from eros.hunter.matcher import JobMatcher
from eros.hunter.engine import HunterEngine
from eros.bot.telegram import TelegramBot
from eros.config import Settings


class TestPhase4HiringDetective(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = f"{self.temp_dir}/test_jobs.db"
        self.storage = JobStorage(db_path=self.db_path)
        await self.storage.init_db()

        self.sample_profile = ProfileContext(
            name="Mateo",
            role="Full Stack & Creative Engineer",
            tech_stack=["Vue 3", "Nuxt 3", "TypeScript", "Node.js", "Tailwind CSS", "PostgreSQL"],
            projects=[
                ProjectSummary(slug="dos-mundos", title="Portafolio Dos Mundos", summary="Web con Three.js y Nuxt", techs=["Nuxt", "Vue", "Three.js"]),
                ProjectSummary(slug="eros-os", title="Eros Career OS", summary="Agente autónomo de carrera", techs=["Python", "FastAPI"])
            ],
            languages="Inglés C1 / Español Nativo",
            timezone="UTC-3"
        )

    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _has_emojis(self, text: str) -> bool:
        """Verifica que no existan emojis en el texto según el mandato estricto."""
        emoji_pattern = re.compile(
            r"[\U00010000-\U0010ffff]|[\u2600-\u27bf]|[\u2300-\u23ff]|[\u2b50-\u2b55]",
            flags=re.UNICODE
        )
        return bool(emoji_pattern.search(text))

    async def test_01_models_support_hiring_manager_fields(self):
        """Verifica que JobOffer y MatchResult soporten los campos de hiring manager y nota."""
        job = JobOffer(
            id="job-123",
            source="linkedin",
            title="Senior Frontend Engineer",
            company="Tech Corp",
            url="https://www.linkedin.com/jobs/view/123",
            country="Remoto LATAM",
            hiring_manager_name="Elena Gómez",
            hiring_manager_title="Senior Talent Lead",
            hiring_manager_url="https://www.linkedin.com/in/elena-gomez",
            connection_note="Hola Elena, vi la búsqueda de Senior Frontend Engineer en Tech Corp. Especialista en Vue/Nuxt y TS. mateogs.tech"
        )
        self.assertEqual(job.hiring_manager_name, "Elena Gómez")
        self.assertEqual(job.hiring_manager_title, "Senior Talent Lead")
        self.assertEqual(job.hiring_manager_url, "https://www.linkedin.com/in/elena-gomez")
        self.assertTrue(len(job.connection_note) < 280)
        self.assertFalse(self._has_emojis(job.connection_note))

        match = MatchResult(
            score=90,
            verdict="EXCELENTE",
            summary="Excelente fit con el stack",
            recruiter_note="Hola Elena, vi la vacante. Especialista en Nuxt/Vue. Saludos!",
            hiring_manager_name="Elena Gómez",
            hiring_manager_title="Senior Talent Lead",
            hiring_manager_url="https://www.linkedin.com/in/elena-gomez"
        )
        self.assertEqual(match.recruiter_note, "Hola Elena, vi la vacante. Especialista en Nuxt/Vue. Saludos!")

    async def test_02_database_persistence_and_retrieval(self):
        """Verifica que JobStorage persista y recupere fielmente los campos de recruiter y nota."""
        job = JobOffer(
            id="job-persist-1",
            source="linkedin",
            title="Nuxt 3 Developer",
            company="Modern Web Labs",
            url="https://www.linkedin.com/jobs/view/999",
            country="Remoto",
            hiring_manager_name="Carlos Ruiz",
            hiring_manager_title="Head of Engineering",
            hiring_manager_url="https://www.linkedin.com/in/carlos-ruiz-eng",
            connection_note="Hola Carlos, vi la búsqueda de Nuxt 3 Developer en Modern Web Labs. Me especializo en Vue/Nuxt y Node. Mi portafolio: mateogs.tech"
        )
        is_new = await self.storage.save_job(job)
        self.assertTrue(is_new)

        retrieved = await self.storage.get_job("job-persist-1")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.hiring_manager_name, "Carlos Ruiz")
        self.assertEqual(retrieved.hiring_manager_title, "Head of Engineering")
        self.assertEqual(retrieved.hiring_manager_url, "https://www.linkedin.com/in/carlos-ruiz-eng")
        self.assertEqual(retrieved.connection_note, job.connection_note)

    def test_03_linkedin_extractor_with_hirer_card(self):
        """Verifica la detección de recruiter en el HTML público de LinkedIn con tarjeta específica."""
        html_doc = """
        <html>
            <body>
                <div class="job-view-layout">
                    <div class="message-the-recruiter hirer-card">
                        <a href="https://www.linkedin.com/in/sarah-connor-talent?ref=job_details">
                            <span class="hirer-name">Sarah Connor</span>
                        </a>
                        <p class="role-headline">Lead Technical Recruiter at Cyberdyne \U0001f680\u2728</p>
                    </div>
                </div>
            </body>
        </html>
        """
        soup = BeautifulSoup(html_doc, "html.parser")
        name, title, url = LinkedInJobsSource.extract_hiring_manager(soup)
        self.assertEqual(name, "Sarah Connor")
        self.assertEqual(title, "Lead Technical Recruiter at Cyberdyne")
        self.assertEqual(url, "https://www.linkedin.com/in/sarah-connor-talent")
        self.assertFalse(self._has_emojis(title))

    def test_04_linkedin_extractor_fallback_in_profile(self):
        """Verifica la detección de enlace de perfil /in/ cuando no hay clase formal."""
        html_doc = """
        <html>
            <body>
                <div class="job-details">
                    <p>Para preguntas sobre la posición contactar a:</p>
                    <a href="https://www.linkedin.com/in/martin-fowler-arch?trk=public_jobs">Martin Fowler</a>
                </div>
            </body>
        </html>
        """
        soup = BeautifulSoup(html_doc, "html.parser")
        name, title, url = LinkedInJobsSource.extract_hiring_manager(soup)
        self.assertEqual(name, "Martin Fowler")
        self.assertEqual(url, "https://www.linkedin.com/in/martin-fowler-arch")

    def test_05_linkedin_extractor_empty_when_no_recruiter(self):
        """Verifica que devuelva None cuando la ficha no incluye recruiter."""
        html_doc = "<html><body><div class='job'>Sin datos de reclutador</div></body></html>"
        soup = BeautifulSoup(html_doc, "html.parser")
        name, title, url = LinkedInJobsSource.extract_hiring_manager(soup)
        self.assertIsNone(name)
        self.assertIsNone(title)
        self.assertIsNone(url)

    async def test_06_matcher_generates_connection_note_under_280_chars_no_emojis(self):
        """Verifica que el matcher genere una nota < 280 caracteres y sin emojis."""
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="""
        {
            "score": 92,
            "verdict": "EXCELENTE",
            "summary": "Match perfecto con Nuxt 3 y TypeScript.",
            "pros": ["Stack 100% compatible", "Remoto LATAM"],
            "cons": [],
            "missing_skills": [],
            "matching_projects": ["Portafolio Dos Mundos"],
            "salary_estimate": "USD 3,500 - 4,500 / mes",
            "hiring_manager_name": "Valeria Lynch",
            "hiring_manager_title": "Head of Talent",
            "recruiter_note": "Hola Valeria, vi la búsqueda de Senior Frontend en Acme. Me especializo en Vue 3, Nuxt 3 y TypeScript. Te invito a ver mis proyectos en mateogs.tech. Me encantaría conectar!"
        }
        """)

        matcher = JobMatcher(llm_client=mock_llm)
        job = JobOffer(
            id="job-eval-1",
            source="linkedin",
            title="Senior Frontend Developer",
            company="Acme Corp",
            url="https://www.linkedin.com/jobs/view/555",
            country="Remoto",
            hiring_manager_name="Valeria Lynch"
        )

        res = await matcher.evaluate(job, self.sample_profile)
        self.assertEqual(res.score, 92)
        self.assertEqual(res.hiring_manager_name, "Valeria Lynch")
        self.assertIsNotNone(res.recruiter_note)
        self.assertLess(len(res.recruiter_note), 280)
        self.assertFalse(self._has_emojis(res.recruiter_note))
        self.assertIn("mateogs.tech", res.recruiter_note)

    async def test_07_matcher_fallback_note_when_llm_fails(self):
        """Verifica que el fallback del matcher produzca una nota válida < 280 chars y sin emojis."""
        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(side_effect=Exception("API Timeout"))

        matcher = JobMatcher(llm_client=mock_llm)
        job = JobOffer(
            id="job-eval-fail",
            source="linkedin",
            title="Tech Lead Frontend",
            company="Globex",
            url="https://www.linkedin.com/jobs/view/777",
            country="Remoto",
            hiring_manager_name="Marcos Paz"
        )

        res = await matcher.evaluate(job, self.sample_profile)
        self.assertIsNotNone(res.recruiter_note)
        self.assertLess(len(res.recruiter_note), 280)
        self.assertFalse(self._has_emojis(res.recruiter_note))
        self.assertIn("Marcos", res.recruiter_note)

    async def test_08_hunter_engine_persists_match_fields(self):
        """Verifica que JobHunterEngine persista connection_note y hiring manager tras evaluar."""
        job = JobOffer(
            id="job-eng-1",
            source="linkedin",
            title="Nuxt Engineer",
            company="Startup XYZ",
            url="https://www.linkedin.com/jobs/view/101",
            country="Remoto",
            hiring_manager_name="Lucía Morales",
            hiring_manager_url="https://www.linkedin.com/in/lucia-morales"
        )
        await self.storage.save_job(job)

        mock_llm = MagicMock()
        mock_llm.embed_text = AsyncMock(return_value=[0.1] * 768)
        mock_llm.generate = AsyncMock(return_value="""
        {
            "score": 88,
            "verdict": "EXCELENTE",
            "summary": "Coincidencia alta.",
            "pros": ["Vue 3", "Nuxt 3"],
            "cons": [],
            "missing_skills": [],
            "matching_projects": ["Portafolio Dos Mundos"],
            "salary_estimate": "USD 3,000 / mes",
            "hiring_manager_name": "Lucía Morales",
            "hiring_manager_title": "Engineering Recruiter",
            "recruiter_note": "Hola Lucía, vi la búsqueda de Nuxt Engineer en Startup XYZ. Especialista en Nuxt y TS. Mi portafolio: mateogs.tech. Saludos!"
        }
        """)

        engine = HunterEngine(storage=self.storage)
        engine.settings.match_min_score = 75
        engine.matcher = JobMatcher(llm_client=mock_llm)
        engine.portfolio_client = MagicMock()
        engine.portfolio_client.fetch_profile = AsyncMock(return_value=self.sample_profile)

        eval_res = await engine.evaluate_single_job("job-eng-1")
        self.assertIsNotNone(eval_res)
        updated_job, match = eval_res

        self.assertEqual(updated_job.hiring_manager_title, "Engineering Recruiter")
        self.assertEqual(updated_job.connection_note, match.recruiter_note)
        self.assertFalse(self._has_emojis(updated_job.connection_note))

        # Comprobar en SQLite
        saved_db = await self.storage.get_job("job-eng-1")
        self.assertEqual(saved_db.hiring_manager_name, "Lucía Morales")
        self.assertEqual(saved_db.hiring_manager_title, "Engineering Recruiter")
        self.assertEqual(saved_db.connection_note, match.recruiter_note)

    async def test_09_telegram_bot_message_formatting_zero_emojis(self):
        """Verifica que notify_match construya el mensaje con <code> de un toque y CERO emojis."""
        bot = TelegramBot()
        bot.allowed_user_id = 12345
        sent_payloads = []

        async def fake_send_message(chat_id, text, reply_markup=None):
            sent_payloads.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup})
            return True

        bot.send_message = fake_send_message

        job = JobOffer(
            id="job-tel-1",
            source="linkedin",
            title="Senior Nuxt Specialist",
            company="Digital Studio",
            url="https://www.linkedin.com/jobs/view/202",
            country="Remoto",
            salary="USD 4,000 / mes",
            hiring_manager_name="Federico Chiesa",
            hiring_manager_title="Talent Acquisition",
            hiring_manager_url="https://www.linkedin.com/in/federico-chiesa",
            connection_note="Hola Federico, vi la vacante en Digital Studio. Me especializo en Vue/Nuxt. mateogs.tech"
        )
        match = MatchResult(
            score=95,
            verdict="EXCELENTE",
            summary="Excelente oportunidad para creative frontend.",
            pros=["Nuxt 3", "Three.js", "Remoto"],
            recruiter_note=job.connection_note,
            hiring_manager_name=job.hiring_manager_name,
            hiring_manager_title=job.hiring_manager_title,
            hiring_manager_url=job.hiring_manager_url
        )

        res = await bot.notify_match(job, match)
        self.assertTrue(res)
        self.assertEqual(len(sent_payloads), 1)

        msg = sent_payloads[0]["text"]
        markup = sent_payloads[0]["reply_markup"]

        # Verificación estricta de CERO EMOJIS
        self.assertFalse(self._has_emojis(msg), f"El mensaje de Telegram contiene emojis: {msg}")

        # Verificación de formateo accesible con <code> para un solo toque
        self.assertIn("<code>Hola Federico, vi la vacante en Digital Studio. Me especializo en Vue/Nuxt. mateogs.tech</code>", msg)
        self.assertIn("Federico Chiesa", msg)
        self.assertIn("Talent Acquisition", msg)

        # Verificación de botón 'Ver Recruiter'
        keyboard_buttons = [btn for row in markup["inline_keyboard"] for btn in row]
        recruiter_btn = next((b for b in keyboard_buttons if b["text"] == "Ver Recruiter"), None)
        self.assertIsNotNone(recruiter_btn)
        self.assertEqual(recruiter_btn["url"], "https://www.linkedin.com/in/federico-chiesa")


if __name__ == "__main__":
    unittest.main()
