import unittest
import fitz

from eros.models import (
    TailoredCV,
    CVProject,
    CVEducation,
    ProfileContext,
    JobOffer,
)
from eros.hunter.cv_generator import CVGenerator


class TestCVATSQuality(unittest.TestCase):
    """Batería de pruebas de calidad para la norma Harvard ATS de 1 página A4."""

    def setUp(self):
        self.generator = CVGenerator()
        self.sample_profile = ProfileContext(
            name="Mateo Gabriel Sonzogni",
            role="Full Stack & Backend Software Engineer",
            location="Neuquén / Río Negro, Patagonia Argentina",
            timezone="UTC-3",
            tech_stack=["Python", "FastAPI", "Node.js", "Express", "PostgreSQL", "Vue 3", "Nuxt 4", "Docker"],
            projects=[],
            education="Escuela Da Vinci / CET 30",
        )
        self.sample_job = JobOffer(
            id="job-ats-production",
            source="linkedin",
            title="Senior Python & Backend Engineer",
            company="Global Tech Enterprise",
            url="https://example.com/jobs/python-lead",
            description=(
                "Buscamos un Ingeniero de Software Backend con sólida experiencia en Python, FastAPI, "
                "PostgreSQL, microservicios, contenedores Docker y Clean Architecture. Modalidad Remota."
            ),
        )

    def test_01_brief_cv_fills_page_without_residual_whitespace(self):
        """Verifica que un CV breve eleve armónicamente su escala para ocupar >= 85% de la hoja A4 sin desbordar."""
        brief_cv = TailoredCV(
            name="MATEO GABRIEL SONZOGNI",
            title="Full Stack & Backend Developer",
            location="Neuquén / Río Negro, Argentina (UTC-3)",
            email="mateogabus@gmail.com",
            github="https://github.com/MateoGs013",
            linkedin="https://linkedin.com/in/mateo-sonzogni",
            portfolio="https://mateogs.tech",
            summary="Desarrollador de software especializado en arquitecturas limpias y APIs de alto rendimiento con Python y FastAPI.",
            skills={
                "Backend & APIs": ["Python", "FastAPI", "Node.js", "PostgreSQL"],
                "Frontend & UI": ["Vue 3", "Nuxt 4", "React", "Tailwind CSS"],
                "Architecture & DevOps": ["Docker", "Linux VPS", "Git Flow", "CI/CD Pipelines"],
            },
            experience=[
                CVProject(
                    title="Ynara AI Assistant",
                    role="Backend Developer",
                    period="2024 – 2026",
                    location="Buenos Aires, Argentina (Remote)",
                    bullets=[
                        "Desarrollo de API con FastAPI logrando latencia sub-100ms.",
                        "Integración de embeddings vectoriales con pgvector y PostgreSQL.",
                    ],
                    tech_stack=["Python", "FastAPI", "pgvector"],
                ),
                CVProject(
                    title="Portafolio (mateogs.tech)",
                    role="Full Stack Developer",
                    period="2025 – 2026",
                    location="Argentina (Remote)",
                    bullets=[
                        "Plataforma desacoplada con Express 5 y frontend interactivo en Nuxt 4.",
                        "Modelado relacional con PostgreSQL 17 y Prisma ORM.",
                    ],
                    tech_stack=["Node.js", "Nuxt 4", "PostgreSQL"],
                ),
                CVProject(
                    title="ARG Piscinas",
                    role="Full Stack Developer",
                    period="2024 – 2025",
                    location="Andalucía, España (Remote)",
                    bullets=[
                        "Plataforma corporativa multi-idioma con panel de administración a medida.",
                        "Despliegue automatizado en Linux VPS con contenedores Docker.",
                    ],
                    tech_stack=["Vue 3", "TypeScript", "Docker"],
                ),
                CVProject(
                    title="La Rúcula Gastrobar",
                    role="Frontend Developer",
                    period="2024 – 2025",
                    location="Cádiz, España (Remote)",
                    bullets=[
                        "Aplicación web editorial con Lighthouse 99 Performance.",
                        "Menú dinámico interactivo con offline cache fallback.",
                    ],
                    tech_stack=["Vue 3", "Tailwind CSS"],
                ),
            ],
            education=[
                CVEducation(
                    institution="Escuela Da Vinci",
                    degree="Técnico Superior en Desarrollo Web",
                    period="2024 – 2026",
                    details="Desarrollo Full Stack y bases de datos relacionales.",
                ),
                CVEducation(
                    institution="CET N.º 30",
                    degree="Técnico en Programación",
                    period="2017 – 2023",
                    details="7 años de formación técnica en algoritmia y sistemas operativos.",
                ),
            ],
            languages=["Español (Nativo)", "Inglés (B2 Profesional)"],
            methodologies=["Clean Architecture", "SOLID", "Docker", "Git Flow"],
            language="es",
        )

        pdf_bytes = self.generator.render_pdf(brief_cv)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        self.assertEqual(doc.page_count, 1, "El CV breve debe tener exactamente 1 página A4")

        page = doc[0]
        self.assertAlmostEqual(page.rect.width, 595.28, delta=1.0)
        self.assertAlmostEqual(page.rect.height, 841.89, delta=1.0)

        blocks = page.get_text("blocks")
        max_y = max(b[3] for b in blocks)
        coverage = max_y / page.rect.height

        # Norma Harvard ATS: Cobertura >= 85% para evitar espacios blancos vacíos
        self.assertGreaterEqual(
            coverage,
            0.85,
            f"El CV breve debe cubrir al menos el 85% de la página (actual: {coverage*100:.2f}%)",
        )

    def test_02_production_standard_cv_coverage_between_88_and_95_percent(self):
        """Verifica que el CV estándar de producción ocupe armónicamente entre 88% y 95% de la hoja A4."""
        std_cv = self.generator._build_fallback_cv(self.sample_profile, self.sample_job)

        pdf_bytes = self.generator.render_pdf(std_cv)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        self.assertEqual(doc.page_count, 1, "El CV de producción debe ser estrictamente de 1 página A4")

        page = doc[0]
        self.assertAlmostEqual(page.rect.width, 595.28, delta=1.0)
        self.assertAlmostEqual(page.rect.height, 841.89, delta=1.0)

        blocks = page.get_text("blocks")
        max_y = max(b[3] for b in blocks)
        coverage = max_y / page.rect.height

        # Norma Harvard ATS: Contenido armónico entre el 88% y el 95% de la altura de la página A4
        self.assertGreaterEqual(
            coverage,
            0.88,
            f"El CV estándar debe cubrir al menos el 88% de la página (actual: {coverage*100:.2f}%)",
        )
        self.assertLessEqual(
            coverage,
            0.95,
            f"El CV estándar no debe superar el 95% de la página para respetar márgenes (actual: {coverage*100:.2f}%)",
        )

    def test_03_dense_cv_5_projects_4_bullets_strict_single_page(self):
        """Verifica que un CV denso (5 proyectos, 4 bullets c/u) se auto-calibre sin desbordar a 2da página."""
        dense_cv = TailoredCV(
            name="MATEO GABRIEL SONZOGNI",
            title="Staff Backend & Distributed Systems Engineer",
            location="Patagonia, Argentina (UTC-3)",
            email="mateogabus@gmail.com",
            github="https://github.com/MateoGs013",
            linkedin="https://www.linkedin.com/in/mateo-sonzogni",
            portfolio="https://mateogs.tech",
            summary=(
                "Ingeniero de software con sólida trayectoria liderando arquitecturas resilientes en Python, "
                "FastAPI, Node.js y bases de datos relacionales en alta concurrencia. Especialista en optimización "
                "de rendimiento y pipelines de streaming de alta disponibilidad."
            ),
            skills={
                "Backend & APIs": ["Python", "FastAPI", "Node.js", "Express 5", "REST APIs", "gRPC"],
                "Databases & Storage": ["PostgreSQL 17", "Prisma ORM", "Redis", "pgvector", "Supabase"],
                "Architecture & DevOps": ["Docker", "Kubernetes", "Linux VPS", "CI/CD Pipelines", "Nginx"],
                "Frontend & UI Ecosystem": ["Vue 3", "Nuxt 4", "React", "Next.js", "Tailwind CSS"],
            },
            experience=[
                CVProject(
                    title=f"Proyecto Corporativo Escalable {i}",
                    role="Lead Software Architect",
                    period="2023 – 2026",
                    location="Buenos Aires, Argentina (Remote)",
                    bullets=[
                        "Lideró el diseño e implementación de subsistemas de misión crítica procesando 15k req/s con FastAPI.",
                        "Optimizó tiempos de respuesta en un 42% reestructurando consultas y transacciones en PostgreSQL.",
                        "Automatizó pipelines de integración continua con GitHub Actions reduciendo el lead time de despliegue.",
                        "Estableció lineamientos de arquitectura limpia y cobertura de pruebas unitarias superiores al 90%.",
                    ],
                    tech_stack=["Python", "FastAPI", "PostgreSQL", "Docker"],
                )
                for i in range(1, 6)
            ],
            education=[
                CVEducation(
                    institution="Escuela Da Vinci",
                    degree="Técnico Superior en Desarrollo Web",
                    period="2024 – 2026",
                    details="Formación en arquitecturas web avanzadas y bases de datos relacionales.",
                ),
                CVEducation(
                    institution="CET N.º 30",
                    degree="Técnico en Programación",
                    period="2017 – 2023",
                    details="7 años de formación técnica en algoritmia y sistemas operativos.",
                ),
            ],
            languages=["Español (Nativo)", "Inglés (B2 Profesional)"],
            methodologies=["Clean Architecture", "SOLID", "Docker", "Git Flow", "Scrum"],
            language="es",
        )

        pdf_bytes = self.generator.render_pdf(dense_cv)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        self.assertEqual(doc.page_count, 1, "El CV denso NUNCA debe desbordar a una 2da página (page_count == 1 estricto)")

        page = doc[0]
        self.assertAlmostEqual(page.rect.width, 595.28, delta=1.0)
        self.assertAlmostEqual(page.rect.height, 841.89, delta=1.0)

        blocks = page.get_text("blocks")
        max_y = max(b[3] for b in blocks)
        coverage = max_y / page.rect.height

        # No debe sobrepasar el margen inferior
        self.assertLessEqual(
            coverage,
            0.96,
            f"El contenido no debe salirse del margen inferior imprimible (actual: {coverage*100:.2f}%)",
        )


if __name__ == "__main__":
    unittest.main()
