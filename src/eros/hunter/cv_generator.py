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
   - "Freelance Full Stack": Desarrollo de punta a punta, arquitectura backend y despliegue en VPS Linux con Docker de ~10 soluciones reales (TypeScript, Node.js, PostgreSQL, Prisma, Docker).
   - "Escuela Da Vinci": Analista de Sistemas / Diseño y Programación de Videojuegos (2023 – 2026).
2. ADAPTACIÓN AL ROL:
   - Resaltá y ordená los proyectos y tecnologías que la oferta exige. Si piden React/Next, priorizá Ynara y ARG Piscinas. Si piden Vue/animaciones/frontend creativo, priorizá La Rúcula.
   - Redactá bullet points con la fórmula Google XYZ: "Logró [X] medido por [Y] mediante [Z]".
3. IDIOMA ESTRICTO:
   - Si la oferta está en inglés, TODO el CV debe estar en INGLÉS técnico y profesional.
   - Si la oferta está en español, TODO el CV debe estar en ESPAÑOL rioplatense neutro.
4. ESTRUCTURA ATS:
   - Un título profesional conciso y alineado al puesto.
   - Resumen ejecutivo de 3-4 líneas centrado en el valor técnico.
   - Skills agrupadas lógicamente con las tecnologías de la oferta listadas primero.
   - Experiencia con 2-3 bullets de alto impacto por proyecto.

Debes responder ÚNICAMENTE un objeto JSON válido con este formato:
{
  "name": "MATEO GABRIEL SONZOGNI",
  "title": "<Título profesional adaptado, ej: Frontend Engineer | React & TypeScript o Full Stack Developer>",
  "location": "Río Negro, Patagonia, Argentina (UTC-3)",
  "contact": {
    "email": "mateogabus@gmail.com",
    "github": "https://github.com/MateoGs013",
    "linkedin": "https://www.linkedin.com/in/mateo-sonzogni",
    "portfolio": "https://mateogs.tech"
  },
  "summary": "<Resumen profesional de 3-4 líneas>",
  "skills": {
    "Frontend & UI": ["TypeScript", "React", "..."],
    "Backend & Databases": ["Node.js", "FastAPI", "..."],
    "Architecture & Tools": ["Git", "Docker", "..."]
  },
  "experience": [
    {
      "role": "<Rol, ej: Lead Frontend & Software Architect>",
      "company_or_project": "<Nombre del proyecto o empresa>",
      "period": "<Período, ej: 05/2026 – 07/2026>",
      "location": "<Ubicación, ej: Buenos Aires, Argentina (Remote) o Cádiz, Spain>",
      "bullets": [
        "<Bullet 1 con impacto medible>",
        "<Bullet 2 con tecnologías clave>"
      ],
      "tech_stack": ["<Tech1>", "<Tech2>", "..."]
    }
  ],
  "education": [
    {
      "institution": "Escuela Da Vinci",
      "degree": "Analista de Sistemas / Software & Systems Analysis",
      "period": "2023 – 2026",
      "details": "Pre-approved degree thesis on adaptive on-premise AI assistants with 382 commits."
    }
  ],
  "language": "en"
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
            return TailoredCV(
                name=data.get("name", "MATEO GABRIEL SONZOGNI"),
                title=data.get("title", profile.role),
                location=data.get("location", "Río Negro, Patagonia Argentina (UTC-3)"),
                email=contact.get("email", "mateogabus@gmail.com"),
                github=contact.get("github", "https://github.com/MateoGs013"),
                linkedin=contact.get("linkedin", "https://www.linkedin.com/in/mateo-sonzogni"),
                portfolio=contact.get("portfolio", "https://mateogs.tech"),
                summary=data.get("summary", ""),
                skills=data.get("skills", {}),
                experience=[
                    CVProject(
                        title=exp.get("company_or_project", ""),
                        role=exp.get("role", ""),
                        period=exp.get("period", ""),
                        location=exp.get("location", "Remote"),
                        bullets=exp.get("bullets", []),
                        tech_stack=exp.get("tech_stack", []),
                    )
                    for exp in data.get("experience", [])
                ],
                education=[
                    CVEducation(
                        institution=ed.get("institution", "Escuela Da Vinci"),
                        degree=ed.get("degree", "Analista de Sistemas"),
                        period=ed.get("period", "2023 – 2026"),
                        details=ed.get("details", ""),
                    )
                    for ed in data.get("education", [])
                ],
                language=data.get("language", "en"),
            )
        except Exception as e:
            logger.error(f"Error generando CV adaptado con LLM: {e}")
            return self._build_fallback_cv(profile, job)

    def _build_fallback_cv(self, profile: ProfileContext, job: JobOffer) -> TailoredCV:
        """Fallback determinista en caso de indisponibilidad temporal del LLM."""
        is_en = not any(w in (job.description or "").lower() for w in ["requisitos", "experiencia", "conocimientos", "puesto", "remoto"])
        
        if is_en:
            title = "Frontend & Full Stack Software Engineer"
            summary = (
                "Software engineer specialized in reactive frontend architecture, high-performance UI, and API systems. "
                "Proven production track record with 10+ web deliverables across Spain and Argentina. "
                "Proficient in TypeScript, Vue 3, Nuxt 4, React, Next.js, Node.js, FastAPI, and PostgreSQL."
            )
        else:
            title = "Desarrollador Frontend & Full Stack"
            summary = (
                "Desarrollador de software especializado en arquitectura frontend reactiva, UI de alto rendimiento y APIs. "
                "Experiencia comprobable en producción con más de 10 proyectos entregados para clientes en España y Argentina. "
                "Dominio de TypeScript, Vue 3, Nuxt 4, React, Next.js, Node.js, FastAPI y PostgreSQL."
            )

        return TailoredCV(
            name="MATEO GABRIEL SONZOGNI",
            title=title,
            location="Río Negro, Patagonia Argentina (UTC-3)",
            email="mateogabus@gmail.com",
            github="https://github.com/MateoGs013",
            linkedin="https://www.linkedin.com/in/mateo-sonzogni",
            portfolio="https://mateogs.tech",
            summary=summary,
            skills={
                "Languages & Core": ["TypeScript", "JavaScript", "Python", "HTML5", "CSS3 / Sass"],
                "Frontend Ecosystem": ["React", "Next.js", "Vue 3", "Nuxt 4", "Tailwind CSS", "GSAP"],
                "Backend & Storage": ["Node.js", "Express", "FastAPI", "PostgreSQL", "Prisma ORM"],
                "DevOps & Workflow": ["Docker", "Git", "GitHub Actions", "Linux / VPS"],
            },
            experience=[
                CVProject(
                    title="Ynara AI Assistant",
                    role="Lead Frontend & Software Architect",
                    period="05/2026 – 07/2026",
                    location="Buenos Aires, Argentina (Remote)",
                    bullets=[
                        "Led end-to-end technical architecture and reactive frontend with 382 commits across 6 weeks.",
                        "Built low-latency inference pipelines and vector memory using Next.js, FastAPI, and PostgreSQL pgvector.",
                    ],
                    tech_stack=["FastAPI", "Next.js", "PostgreSQL", "pgvector", "TypeScript"],
                ),
                CVProject(
                    title="La Rúcula Gastrobar",
                    role="Full Stack Developer & UI Designer",
                    period="03/2026 – 07/2026",
                    location="Cádiz, Spain (Remote)",
                    bullets=[
                        "Engineered high-end editorial web app achieving Lighthouse scores of 99 Performance and 100 SEO.",
                        "Implemented offline cache fallback and smooth reactive animations with Vue 3, Tailwind, and GSAP.",
                    ],
                    tech_stack=["Vue 3", "Vite", "Tailwind CSS", "GSAP", "Lenis"],
                ),
                CVProject(
                    title="ARG Piscinas",
                    role="Full Stack Developer",
                    period="01/2026 – 07/2026",
                    location="Andalucía, Spain (Remote)",
                    bullets=[
                        "Developed corporate multi-language web platform (ES/EN/DE) with custom content management backoffice.",
                        "Ensured strict end-to-end typing with Prisma ORM, Node.js, TypeScript, and PostgreSQL.",
                    ],
                    tech_stack=["Vue 3", "Node.js", "Prisma", "Tailwind CSS", "TypeScript"],
                ),
            ],
            education=[
                CVEducation(
                    institution="Escuela Da Vinci",
                    degree="Systems & Software Analysis / Video Game Design",
                    period="2023 – 2026",
                    details="Pre-approved degree thesis on adaptive on-premise AI assistants with 382 commits.",
                )
            ],
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

        return f"""<!doctype html>
<html lang="{cv.language}">
<head>
<meta charset="utf-8">
<title>{cv.name} — Curriculum Vitae</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  @page {{
    size: A4 portrait;
    margin: 12mm 16mm;
  }}
  * {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
  }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Calibri", "Helvetica Neue", Arial, sans-serif;
    color: #111111;
    background: #ffffff;
    font-size: 10.5pt;
    line-height: 1.35;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }}
  .cv-page {{
    max-width: 210mm;
    margin: 0 auto;
    padding: 18mm 18mm;
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
    margin-bottom: 12px;
    border-bottom: 1.5px solid #111111;
    padding-bottom: 8px;
  }}
  .cv-name {{
    font-size: 18pt;
    font-weight: 700;
    letter-spacing: 0.05em;
    color: #000000;
    margin-bottom: 2px;
  }}
  .cv-title {{
    font-size: 11pt;
    font-weight: 600;
    color: #222222;
    margin-bottom: 4px;
  }}
  .cv-contact {{
    font-size: 9pt;
    color: #444444;
    display: flex;
    justify-content: center;
    flex-wrap: wrap;
    gap: 8px;
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
    margin-top: 10px;
    margin-bottom: 10px;
  }}
  .section-title {{
    font-size: 10pt;
    font-weight: 700;
    letter-spacing: 0.06em;
    color: #000000;
    border-bottom: 1px solid #111111;
    padding-bottom: 2px;
    margin-bottom: 6px;
    text-transform: uppercase;
  }}
  .cv-summary {{
    font-size: 9.5pt;
    color: #222222;
    text-align: justify;
    line-height: 1.4;
  }}

  /* Skills */
  .skills-row {{
    font-size: 9.2pt;
    margin-bottom: 3px;
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
    margin-bottom: 8px;
  }}
  .exp-header {{
    display: flex;
    justify-content: space-between;
    font-size: 9.8pt;
  }}
  .exp-period {{
    font-size: 9pt;
    color: #333333;
    font-weight: 500;
  }}
  .exp-sub {{
    font-size: 8.8pt;
    color: #555555;
    margin-bottom: 3px;
  }}
  .exp-bullets {{
    margin-left: 18px;
    font-size: 9.2pt;
    color: #222222;
    line-height: 1.35;
  }}
  .exp-bullets li {{
    margin-bottom: 2px;
  }}
  .exp-techs {{
    font-size: 8.5pt;
    color: #444444;
    margin-top: 2px;
    margin-left: 18px;
  }}

  /* Educación */
  .edu-entry {{
    margin-bottom: 4px;
    font-size: 9.5pt;
  }}
  .edu-header {{
    display: flex;
    justify-content: space-between;
  }}
  .edu-period {{
    font-size: 9pt;
    color: #333333;
  }}
  .edu-details {{
    font-size: 8.8pt;
    color: #444444;
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
  </main>
</body>
</html>
"""
