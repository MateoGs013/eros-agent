import json
import logging
import re
from eros.integrations.llm import LLMClient
from eros.models import (
    JobOffer,
    MatchResult,
    ProfileContext,
    TailoredCV,
    CVProject,
    CVEducation,
)

logger = logging.getLogger(__name__)

CV_SYSTEM_PROMPT = """
Sos un redactor experto en Currículums Vitae técnicos de estándar Harvard y optimización para sistemas ATS (Applicant Tracking Systems: Greenhouse, Lever, Workday, Taleo).
Tu objetivo es tomar los datos reales de Mateo Gabriel Sonzogni y adaptarlos con precisión quirúrgica para una vacante específica.

REGLAS DE ORO:
1. NADA DE INVENTAR EXPERIENCIA FALSA: Mateo tiene proyectos reales en producción:
   - "Ynara AI Assistant": Tesis de grado Escuela Da Vinci, inferencia on-premise, Next.js, FastAPI, PostgreSQL, pgvector, latencia sub-100ms, 382 commits.
   - "Portafolio Dos Mundos": Plataforma Full Stack con backend desacoplado (Express 5, Prisma ORM, PostgreSQL 17) sirviendo API pública y panel admin con tokens seguros, y frontend Nuxt 4 con renderers gemelos DATOS y DISEÑO.
   - "ARG Piscinas": Web corporativa multi-idioma (ES/EN/DE) con panel admin en producción para cliente en Andalucía (España), Node.js, Prisma ORM, TypeScript, Vue 3.
   - "La Rúcula Gastrobar": Sitio editorial en producción para cliente en Cádiz (España), Vue 3, Vite, Tailwind CSS, GSAP, Lenis, Lighthouse 99 Performance / 100 SEO, menú QR con offline cache fallback.
   - "Eros Agent": Agente autónomo de prospección y reclutamiento con LLMs (Gemini Flash), scrapers multi-fuente asíncronos, FastAPI y SQLite.
   - "Barberpole / Soluciones de Gestión": Aplicación web de turnos y gestión de clientes con arquitectura modular, autenticación y base de datos relacional (TypeScript, Node.js, PostgreSQL, Vue 3).
   - "Escuela Da Vinci": Analista de Sistemas / Software & Systems Analysis (2023 – 2026).

2. COBERTURA TOTAL DE LA HOJA A4 (HARVARD SINGLE-PAGE STANDARD):
   - CRUCIAL: El CV debe llenar armónicamente entre el 90% y el 95% de una página A4, sin dejar grandes espacios vacíos por debajo y sin desbordar a una segunda página.
   - Incluí EXACTAMENTE 4 proyectos/experiencias relevantes seleccionados de la lista de producción anterior, priorizando los más afines a la vacante.
   - Cada proyecto DEBE tener EXACTAMENTE 3 viñetas (bullets) sustanciales, detalladas y ricas en contexto de ingeniería y métricas formuladas con Google XYZ ("Logró [X] medido por [Y] mediante [Z]").
   - Habilidades Técnicas (Skills) agrupadas en 4 categorías completas y densas: "Backend & APIs", "Databases & Storage", "Architecture & DevOps", "Frontend & UI Ecosystem".
   - Educación con detalle amplio sobre materias y fundamentos clave de Analista de Sistemas (Arquitectura de software, algoritmos, bases de datos, sistemas distribuidos).
   - Sección de Idiomas (Languages): Español (Nativo) e Inglés (B2 Profesional / Técnico).
   - Sección de Metodologías & Buenas Prácticas: Clean Architecture, Principios SOLID, Git Flow & CI/CD, Docker, Metodologías Ágiles (Scrum).

3. ADAPTACIÓN AL ROL:
   - Resaltá y ordená los proyectos y tecnologías que la oferta exige. Si piden Python/Backend/FastAPI, priorizá Ynara, Portafolio Dos Mundos y Eros Agent. Si piden Full Stack, balanceá Node.js, Vue y Next.js.
   - Si la oferta está en inglés, TODO el CV debe redactarse en INGLÉS técnico y profesional.
   - Si la oferta está en español, TODO el CV debe redactarse en ESPAÑOL rioplatense neutro.

Debes responder ÚNICAMENTE un objeto JSON válido con este formato:
{
  "name": "MATEO GABRIEL SONZOGNI",
  "title": "<Título profesional adaptado, ej: Full Stack Developer | Node.js & React o Python & Backend Engineer>",
  "location": "Neuquén / Río Negro, Patagonia, Argentina (UTC-3)",
  "contact": {
    "email": "mateogabus@gmail.com",
    "github": "https://github.com/MateoGs013",
    "linkedin": "https://www.linkedin.com/in/mateo-sonzogni",
    "portfolio": "https://mateogs.tech"
  },
  "summary": "<Resumen profesional de 3-4 líneas bien densas y técnicas centrado en arquitectura y valor entregado>",
  "skills": {
    "Backend & APIs": ["Python", "FastAPI", "Node.js", "Express", "TypeScript", "REST APIs"],
    "Databases & Storage": ["PostgreSQL", "MongoDB", "Prisma ORM", "pgvector", "Supabase", "Redis"],
    "Architecture & DevOps": ["Docker", "Linux VPS", "Git", "CI/CD Pipelines", "Nginx", "Microservicios"],
    "Frontend & UI Ecosystem": ["React", "Next.js", "Vue 3", "Nuxt 4", "Tailwind CSS", "TypeScript"]
  },
  "experience": [
    {
      "role": "<Rol, ej: Backend & AI Architect o Full Stack Developer>",
      "company_or_project": "<Nombre del proyecto o empresa>",
      "period": "<Período, ej: 2024 – 2026>",
      "location": "<Ubicación o Remote>",
      "bullets": [
        "<Bullet 1 con impacto medible y fórmula Google XYZ>",
        "<Bullet 2 con retos de arquitectura técnica>",
        "<Bullet 3 con integración, optimización o despliegue>"
      ],
      "tech_stack": ["<Tech1>", "<Tech2>", "<Tech3>"]
    }
  ],
  "education": [
    {
      "institution": "Escuela Da Vinci",
      "degree": "Analista de Sistemas / Software & Systems Analysis",
      "period": "2023 – 2026",
      "details": "Formación integral en ingeniería de software, arquitectura de sistemas distribuidos, diseño de bases de datos relacionales/vectoriales y algoritmos avanzados."
    }
  ],
  "languages": [
    "Español (Nativo)",
    "Inglés (B2 Profesional / Técnico: lectura fluida de documentación, tickets y comunicación asíncrona)"
  ],
  "methodologies": [
    "Arquitectura Limpia & Principios SOLID",
    "Contenerización con Docker & Despliegues en VPS Linux",
    "Control de versiones con Git Flow & CI/CD Pipelines",
    "Metodologías Ágiles (Scrum / Kanban)",
    "Rendimiento y Optimización Web (Lighthouse 95+)"
  ],
  "language": "es"
}
"""


class CVGenerator:
    """Generador agéntico de CVs adaptados en formato Harvard ATS."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()

    async def generate_tailored_cv(
        self,
        job: JobOffer,
        profile: ProfileContext,
        match: MatchResult | None = None,
    ) -> TailoredCV:
        """Adapta el CV de Mateo a los requisitos específicos de una oferta laboral."""
        prompt = f"""
VACANTE OBJETIVO:
Empresa: {job.company}
Puesto: {job.title}
Ubicación / Modalidad: {job.country or 'Remoto'}
Descripción y Requisitos:
{job.description[:2800]}

DATOS DE MATEO:
Nombre: {profile.name}
Rol base: {profile.role}
Ubicación: {profile.location} ({profile.timezone})
Stack: {', '.join(profile.tech_stack)}
Proyectos:
{json.dumps([p.model_dump() for p in profile.projects], ensure_ascii=False, indent=2)}

PUNTOS FUERTES DETECTADOS EN EL MATCH:
{json.dumps(match.pros if match else [], ensure_ascii=False)}

Generá el JSON del CV adaptado siguiendo estrictamente las instrucciones del sistema.
"""

        try:
            raw_text = await self.llm.generate(
                prompt=prompt,
                system_prompt=CV_SYSTEM_PROMPT,
            )

            cleaned = re.sub(r"^```json\s*", "", raw_text.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"^```\s*", "", cleaned, flags=re.MULTILINE)
            data = json.loads(cleaned)

            contact = data.get("contact", {})
            exp_items = [
                CVProject(
                    title=exp.get("company_or_project", ""),
                    role=exp.get("role", ""),
                    period=exp.get("period", ""),
                    location=exp.get("location", "Remote"),
                    bullets=exp.get("bullets", []),
                    tech_stack=exp.get("tech_stack", []),
                )
                for exp in data.get("experience", [])
            ]

            # Garantizar que siempre haya al menos 4 proyectos para cubrir la hoja A4
            if len(exp_items) < 4:
                existing_titles = {e.title.lower() for e in exp_items}
                fallback_cv = self._build_fallback_cv(profile, job)
                for f_exp in fallback_cv.experience:
                    if not any(f_exp.title.lower() in et or et in f_exp.title.lower() for et in existing_titles):
                        exp_items.append(f_exp)
                        existing_titles.add(f_exp.title.lower())
                    if len(exp_items) >= 4:
                        break

            lang_is_en = data.get("language", "en") == "en"
            languages_val = data.get("languages", [])
            if isinstance(languages_val, str):
                languages_val = [languages_val]
            elif not isinstance(languages_val, list) or not languages_val:
                languages_val = (
                    ["Spanish (Native)", "English (B2 Professional / Technical Working Proficiency)"]
                    if lang_is_en
                    else ["Español (Nativo)", "Inglés (B2 Profesional / Técnico: lectura fluida de documentación, tickets y comunicación asíncrona)"]
                )

            methodologies_val = data.get("methodologies", data.get("certifications_or_methodologies", []))
            if isinstance(methodologies_val, str):
                methodologies_val = [methodologies_val]
            elif not isinstance(methodologies_val, list) or not methodologies_val:
                methodologies_val = (
                    ["Clean Architecture & SOLID Principles", "Docker Containerization & Linux Deployments", "Git Flow & CI/CD Pipelines", "Agile / Scrum Methodologies", "Web Performance Optimization (Lighthouse 95+)"]
                    if lang_is_en
                    else ["Arquitectura Limpia & Principios SOLID", "Contenerización con Docker & Despliegues en VPS Linux", "Git Flow & CI/CD Pipelines", "Metodologías Ágiles (Scrum)", "Rendimiento y Optimización Web (Lighthouse 95+)"]
                )

            return TailoredCV(
                name=data.get("name", "MATEO GABRIEL SONZOGNI"),
                title=data.get("title", profile.role),
                location=data.get("location", "Neuquén / Río Negro, Patagonia Argentina (UTC-3)"),
                email=contact.get("email", "mateogabus@gmail.com"),
                github=contact.get("github", "https://github.com/MateoGs013"),
                linkedin=contact.get("linkedin", "https://www.linkedin.com/in/mateo-sonzogni"),
                portfolio=contact.get("portfolio", "https://mateogs.tech"),
                summary=data.get("summary", ""),
                skills=data.get("skills", {}),
                experience=exp_items,
                education=[
                    CVEducation(
                        institution=ed.get("institution", "Escuela Da Vinci"),
                        degree=ed.get("degree", "Analista de Sistemas / Software & Systems Analysis"),
                        period=ed.get("period", "2023 – 2026"),
                        details=ed.get("details", "Formación integral en ingeniería de software, arquitectura de sistemas distribuidos, bases de datos y algoritmos."),
                    )
                    for ed in data.get("education", [])
                ] or [
                    CVEducation(
                        institution="Escuela Da Vinci",
                        degree="Analista de Sistemas / Software & Systems Analysis",
                        period="2023 – 2026",
                        details="Formación integral en ingeniería de software, arquitectura de sistemas distribuidos, bases de datos y algoritmos.",
                    )
                ],
                languages=languages_val,
                methodologies=methodologies_val,
                language=data.get("language", "en"),
            )
        except Exception as e:
            logger.error(f"Error generando CV adaptado con LLM: {e}")
            return self._build_fallback_cv(profile, job)

    def _build_fallback_cv(self, profile: ProfileContext, job: JobOffer) -> TailoredCV:
        """Fallback determinista en caso de indisponibilidad temporal del LLM con 4 proyectos completos."""
        is_en = not any(w in (job.description or "").lower() for w in ["requisitos", "experiencia", "conocimientos", "puesto", "remoto", "presencial", "desarrollador", "empresa", "trabajo", "habilidades", "argentina", "postularse", "ingeniero", "sistemas"])
        
        if is_en:
            title = "Full Stack & Backend Software Engineer"
            summary = (
                "Software engineer specialized in scalable backend architectures, high-performance web systems, and AI inference pipelines. "
                "Proven production track record delivering enterprise-grade platforms for clients across Spain and Argentina. "
                "Proficient in Python, FastAPI, Node.js, Express, TypeScript, Vue 3, Nuxt 4, React, Next.js, and PostgreSQL."
            )
            languages = ["Spanish (Native)", "English (B2 Professional / Technical Working Proficiency)"]
            methodologies = [
                "Clean Architecture & SOLID Principles",
                "Docker Containerization & Linux VPS Deployments",
                "Git Flow, Code Review & CI/CD Pipelines",
                "Agile / Scrum Methodologies",
                "Web Performance Optimization (Lighthouse 95+)",
            ]
            exp = [
                CVProject(
                    title="Ynara AI Assistant",
                    role="Lead Backend & AI Architect (Degree Thesis)",
                    period="2024 – 2026",
                    location="Buenos Aires, Argentina (Remote)",
                    bullets=[
                        "Architected high-throughput inference API with FastAPI and Python, achieving sub-100ms response times for on-premise execution.",
                        "Implemented semantic and episodic memory layer utilizing PostgreSQL and pgvector for efficient similarity retrieval.",
                        "Led repository engineering with 382 commits, designing modular backend architecture and Next.js / TypeScript client integration.",
                    ],
                    tech_stack=["Python", "FastAPI", "PostgreSQL", "pgvector", "TypeScript", "Next.js"],
                ),
                CVProject(
                    title="Portafolio Dos Mundos",
                    role="Full Stack Software Engineer",
                    period="2025 – 2026",
                    location="Argentina (Remote)",
                    bullets=[
                        "Engineered decoupled web platform serving high-speed public API and secure token-authenticated reactive admin panel with Express 5.",
                        "Designed robust database schema using PostgreSQL 17 and Prisma ORM, implementing relational constraints and connection pooling.",
                        "Built twin interactive renderers in Nuxt 4 with custom reactive state management and sub-second page transitions.",
                    ],
                    tech_stack=["Node.js", "Express 5", "PostgreSQL 17", "Prisma ORM", "Nuxt 4", "Docker"],
                ),
                CVProject(
                    title="ARG Piscinas",
                    role="Full Stack Developer",
                    period="2024 – 2025",
                    location="Andalucía, Spain (Remote)",
                    bullets=[
                        "Developed corporate multi-language web platform (ES/EN/DE) with bespoke content management backoffice deployed to production.",
                        "Ensured strict end-to-end type safety and automated migration pipelines utilizing Node.js, TypeScript, and Prisma ORM.",
                        "Configured self-hosted production deployment on Linux VPS with Docker containers and automated Nginx reverse proxy.",
                    ],
                    tech_stack=["Node.js", "TypeScript", "Prisma ORM", "PostgreSQL", "Docker", "Vue 3"],
                ),
                CVProject(
                    title="La Rúcula Gastrobar",
                    role="Full Stack & UI Systems Developer",
                    period="2024 – 2025",
                    location="Cádiz, Spain (Remote)",
                    bullets=[
                        "Engineered modern editorial web application achieving verified Lighthouse scores of 99 Performance and 100 SEO.",
                        "Developed dynamic interactive menu with offline cache fallback and smooth micro-animations using Vue 3, Vite, and GSAP.",
                        "Integrated client-side state machine ensuring fault-tolerant navigation under poor mobile connectivity.",
                    ],
                    tech_stack=["Vue 3", "Vite", "Tailwind CSS", "GSAP", "Lenis", "PWA"],
                ),
            ]
        else:
            title = "Desarrollador Full Stack & Backend Engineer"
            summary = (
                "Desarrollador de software especializado en arquitecturas backend escalables, sistemas web de alto rendimiento y pipelines de IA. "
                "Sólida trayectoria en producción entregando soluciones de punta a punta para clientes en España y Argentina. "
                "Dominio de Python, FastAPI, Node.js, Express, TypeScript, Vue 3, Nuxt 4, React, Next.js y PostgreSQL."
            )
            languages = [
                "Español (Nativo)",
                "Inglés (B2 Profesional / Técnico: lectura fluida de especificaciones, documentación técnica y comunicación asíncrona)",
            ]
            methodologies = [
                "Arquitectura Limpia & Principios SOLID",
                "Contenerización con Docker & Despliegues en VPS Linux",
                "Control de versiones con Git Flow & CI/CD Pipelines",
                "Metodologías Ágiles (Scrum / Kanban)",
                "Rendimiento y Optimización Web (Lighthouse 95+)",
            ]
            exp = [
                CVProject(
                    title="Ynara AI Assistant",
                    role="Backend & AI Architect (Tesis de Grado)",
                    period="2024 – 2026",
                    location="Buenos Aires, Argentina (Remote)",
                    bullets=[
                        "Diseñó y desarrolló una API de alta performance con FastAPI y Python para inferencia on-premise, logrando latencias sub-100ms.",
                        "Implementó memoria semántica y episódica mediante PostgreSQL y pgvector, gestionando eficientemente embeddings vectoriales.",
                        "Lideró el desarrollo con 382 commits, estructurando la arquitectura backend, el motor de inferencia y la integración con Next.js y TypeScript.",
                    ],
                    tech_stack=["Python", "FastAPI", "PostgreSQL", "pgvector", "TypeScript", "Next.js"],
                ),
                CVProject(
                    title="Portafolio Dos Mundos",
                    role="Full Stack Software Engineer",
                    period="2025 – 2026",
                    location="Argentina (Remote)",
                    bullets=[
                        "Diseñó una arquitectura desacoplada con Express 5 sirviendo una API pública de alta velocidad y un panel admin seguro con token.",
                        "Modeló la base de datos relacional con PostgreSQL 17 y Prisma ORM, asegurando tipado estricto end-to-end e integridad transaccional.",
                        "Desarrolló frontend gemelo interactivo con Nuxt 4, logrando transiciones fluidas y gestión reactiva de estado sin sobrecarga.",
                    ],
                    tech_stack=["Node.js", "Express 5", "PostgreSQL 17", "Prisma ORM", "Nuxt 4", "Docker"],
                ),
                CVProject(
                    title="ARG Piscinas & Proyectos Freelance",
                    role="Full Stack Developer",
                    period="2023 – 2025",
                    location="Andalucía, España (Remote)",
                    bullets=[
                        "Diseñó y construyó plataforma web multi-idioma (ES/EN/DE) con panel de control a medida para gestión de catálogo corporativo.",
                        "Construyó APIs robustas con Node.js, TypeScript y Prisma ORM para soluciones empresariales desplegadas en producción.",
                        "Administró bases de datos relacionales PostgreSQL y configuró despliegues en servidores VPS Linux utilizando contenedores Docker.",
                    ],
                    tech_stack=["Node.js", "TypeScript", "Prisma ORM", "PostgreSQL", "Docker", "Vue 3"],
                ),
                CVProject(
                    title="La Rúcula Gastrobar",
                    role="Desarrollador Full Stack & UI Systems",
                    period="2024 – 2025",
                    location="Cádiz, España (Remote)",
                    bullets=[
                        "Construyó aplicación web editorial logrando métricas de rendimiento Lighthouse verificadas de 99 Performance y 100 SEO.",
                        "Implementó sistema de carta interactiva con soporte de offline cache para acceso instantáneo y animaciones con Vue 3 y GSAP.",
                        "Desarrolló interfaz accesible y responsive optimizada para dispositivos móviles en entornos de alta demanda operativa.",
                    ],
                    tech_stack=["Vue 3", "Vite", "Tailwind CSS", "GSAP", "Lenis", "PWA"],
                ),
            ]

        return TailoredCV(
            name="MATEO GABRIEL SONZOGNI",
            title=title,
            location="Neuquén / Río Negro, Patagonia Argentina (UTC-3)",
            email="mateogabus@gmail.com",
            github="https://github.com/MateoGs013",
            linkedin="https://www.linkedin.com/in/mateo-sonzogni",
            portfolio="https://mateogs.tech",
            summary=summary,
            skills={
                "Backend & APIs": ["Python", "FastAPI", "Node.js", "Express", "TypeScript", "REST APIs"],
                "Databases & Storage": ["PostgreSQL", "MongoDB", "Prisma ORM", "pgvector", "Supabase", "Redis"],
                "Architecture & DevOps": ["Docker", "Linux VPS", "Git", "CI/CD Pipelines", "Nginx", "Microservicios"],
                "Frontend & UI Ecosystem": ["React", "Next.js", "Vue 3", "Nuxt 4", "Tailwind CSS", "TypeScript"],
            },
            experience=exp,
            education=[
                CVEducation(
                    institution="Escuela Da Vinci",
                    degree="Analista de Sistemas / Software & Systems Analysis",
                    period="2023 – 2026",
                    details="Formación integral en ingeniería de software, arquitectura de sistemas distribuidos, bases de datos relacionales y algoritmos avanzados.",
                )
            ],
            languages=languages,
            methodologies=methodologies,
            language="en" if is_en else "es",
        )

    def render_harvard_html(self, cv: TailoredCV) -> str:
        """Renderiza un documento HTML estricto Harvard ATS (1 página A4, imprimible a PDF)."""
        skills_html = ""
        for category, items in cv.skills.items():
            skills_html += f"""
            <div class="skills-row">
                <span class="skill-category">{category}:</span>
                <span class="skill-items">{", ".join(items)}</span>
            </div>
            """

        experience_html = ""
        for exp in cv.experience:
            bullets = "".join(f"<li>{b}</li>" for b in exp.bullets)
            techs = f"<div class='exp-techs'><em>Tech:</em> {', '.join(exp.tech_stack)}</div>" if exp.tech_stack else ""
            experience_html += f"""
            <div class="exp-entry">
                <div class="exp-header">
                    <span class="exp-title"><strong>{exp.title}</strong> — {exp.role}</span>
                    <span class="exp-period">{exp.period}</span>
                </div>
                <div class="exp-sub">
                    <span class="exp-loc">{exp.location}</span>
                </div>
                <ul class="exp-bullets">
                    {bullets}
                </ul>
                {techs}
            </div>
            """

        education_html = ""
        for ed in cv.education:
            education_html += f"""
            <div class="edu-entry">
                <div class="edu-header">
                    <strong>{ed.institution}</strong> — {ed.degree}
                    <span class="edu-period">{ed.period}</span>
                </div>
                {f'<div class="edu-details">{ed.details}</div>' if ed.details else ''}
            </div>
            """

        is_en = cv.language == "en"
        summary_title = "PROFESSIONAL SUMMARY" if is_en else "PERFIL PROFESIONAL"
        skills_title = "TECHNICAL SKILLS" if is_en else "HABILIDADES TÉCNICAS"
        exp_title = "FEATURED PROJECTS & EXPERIENCE" if is_en else "PROYECTOS Y EXPERIENCIA DESTACADA"
        edu_title = "EDUCATION" if is_en else "EDUCACIÓN"

        # Sección de Idiomas y Metodologías / Estándares de Ingeniería
        extra_sections_html = ""
        lang_rows = []
        if cv.languages:
            lang_label = "Languages" if is_en else "Idiomas"
            lang_rows.append(f"""
            <div class="skills-row">
                <span class="skill-category">{lang_label}:</span>
                <span class="skill-items">{' · '.join(cv.languages)}</span>
            </div>
            """)
        if cv.methodologies:
            meth_label = "Engineering Standards & Practices" if is_en else "Buenas Prácticas & Estándares"
            lang_rows.append(f"""
            <div class="skills-row">
                <span class="skill-category">{meth_label}:</span>
                <span class="skill-items">{' · '.join(cv.methodologies)}</span>
            </div>
            """)
        if lang_rows:
            extra_title = "LANGUAGES & ENGINEERING PRACTICES" if is_en else "IDIOMAS Y BUENAS PRÁCTICAS"
            extra_sections_html = f"""
            <section class="cv-section">
                <h2 class="section-title">{extra_title}</h2>
                {''.join(lang_rows)}
            </section>
            """

        return f"""<!doctype html>
<html lang="{cv.language}">
<head>
<meta charset="utf-8">
<title>{cv.name} — Curriculum Vitae</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  @page {{
    size: A4 portrait;
    margin: 8mm 12mm 8mm 12mm;
  }}
  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Calibri", "Helvetica Neue", Arial, sans-serif;
    color: #111111;
    background: #ffffff;
    font-size: 9.3pt;
    line-height: 1.34;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }}
  .cv-page {{
    max-width: 210mm;
    margin: 0 auto;
    padding: 10mm 14mm;
    background: #ffffff;
  }}
  @media print {{
    .cv-page {{
      padding: 0;
      max-width: 100%;
    }}
    .no-print {{
      display: none !important;
    }}
  }}
  .no-print-toolbar {{
    position: sticky;
    top: 0;
    z-index: 100;
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: #111111;
    color: #ffffff;
    padding: 10px 20px;
    font-family: ui-monospace, monospace;
    font-size: 13px;
    border-bottom: 2px solid #ff3e00;
  }}
  .btn-print {{
    background: #ff3e00;
    color: #ffffff;
    border: none;
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
    border-radius: 4px;
    cursor: pointer;
    font-family: inherit;
  }}
  .btn-print:hover {{
    background: #ff551c;
  }}
  
  /* Cabecera Harvard */
  .cv-header {{
    text-align: center;
    margin-bottom: 7px;
    border-bottom: 1.5px solid #111111;
    padding-bottom: 5px;
  }}
  .cv-name {{
    font-size: 16pt;
    font-weight: 700;
    letter-spacing: 0.04em;
    color: #000000;
    margin-bottom: 2px;
  }}
  .cv-title {{
    font-size: 10pt;
    font-weight: 600;
    color: #222222;
    margin-bottom: 3px;
  }}
  .cv-contact {{
    font-size: 8.6pt;
    color: #444444;
    display: flex;
    justify-content: center;
    flex-wrap: wrap;
    gap: 7px;
  }}
  .cv-contact a {{
    color: #111111;
    text-decoration: none;
  }}
  .cv-contact a:hover {{
    text-decoration: underline;
  }}
  .sep {{
    color: #888888;
  }}

  /* Secciones Estándar Harvard ATS */
  .cv-section {{
    margin-top: 6px;
    margin-bottom: 6px;
  }}
  .section-title {{
    font-size: 9.3pt;
    font-weight: 700;
    letter-spacing: 0.05em;
    color: #000000;
    border-bottom: 1px solid #111111;
    padding-bottom: 2px;
    margin-bottom: 4px;
    text-transform: uppercase;
  }}
  .cv-summary {{
    font-size: 8.9pt;
    color: #222222;
    text-align: justify;
    line-height: 1.34;
  }}

  /* Skills */
  .skills-row {{
    font-size: 8.7pt;
    margin-bottom: 2px;
    line-height: 1.3;
  }}
  .skill-category {{
    font-weight: 700;
    color: #111111;
  }}
  .skill-items {{
    color: #222222;
  }}

  /* Experiencia */
  .exp-entry {{
    margin-bottom: 5.5px;
  }}
  .exp-header {{
    display: flex;
    justify-content: space-between;
    font-size: 9.2pt;
  }}
  .exp-period {{
    font-size: 8.6pt;
    color: #333333;
    font-weight: 500;
  }}
  .exp-sub {{
    font-size: 8.3pt;
    color: #555555;
    margin-bottom: 1.5px;
  }}
  .exp-bullets {{
    margin-left: 16px;
    font-size: 8.6pt;
    color: #222222;
    line-height: 1.32;
  }}
  .exp-bullets li {{
    margin-bottom: 1.5px;
  }}
  .exp-techs {{
    font-size: 8pt;
    color: #444444;
    margin-top: 1.5px;
    margin-left: 16px;
  }}

  /* Educación */
  .edu-entry {{
    margin-bottom: 2px;
    font-size: 8.9pt;
  }}
  .edu-header {{
    display: flex;
    justify-content: space-between;
  }}
  .edu-period {{
    font-size: 8.5pt;
    color: #333333;
  }}
  .edu-details {{
    font-size: 8.3pt;
    color: #444444;
    line-height: 1.3;
    margin-top: 1px;
  }}
</style>
</head>
<body>
  <div class="no-print no-print-toolbar">
    <div>
      <strong>EROS AGENT</strong> // TAILORED ATS RESUME GENERATOR
    </div>
    <div>
      <button class="btn-print" onclick="window.print()">🖨️ Descargar / Imprimir en PDF (A4)</button>
    </div>
  </div>

  <main class="cv-page">
    <header class="cv-header">
      <h1 class="cv-name">{cv.name}</h1>
      <div class="cv-title">{cv.title}</div>
      <div class="cv-contact">
        <span>{cv.location}</span>
        <span class="sep">·</span>
        <a href="mailto:{cv.email}">{cv.email}</a>
        <span class="sep">·</span>
        <a href="{cv.portfolio}" target="_blank">mateogs.tech</a>
        <span class="sep">·</span>
        <a href="{cv.linkedin}" target="_blank">LinkedIn</a>
        <span class="sep">·</span>
        <a href="{cv.github}" target="_blank">GitHub</a>
      </div>
    </header>

    <section class="cv-section">
      <h2 class="section-title">{summary_title}</h2>
      <p class="cv-summary">{cv.summary}</p>
    </section>

    <section class="cv-section">
      <h2 class="section-title">{skills_title}</h2>
      {skills_html}
    </section>

    <section class="cv-section">
      <h2 class="section-title">{exp_title}</h2>
      {experience_html}
    </section>

    <section class="cv-section">
      <h2 class="section-title">{edu_title}</h2>
      {education_html}
    </section>

    {extra_sections_html}
  </main>
</body>
</html>
"""
