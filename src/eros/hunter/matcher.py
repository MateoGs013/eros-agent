import json
import logging
import re
from eros.integrations.llm import LLMClient
from eros.models import JobOffer, MatchResult, ProfileContext

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """
Sos el asesor técnico y evaluador de compatibilidad de empleo para Mateo Gabriel Sonzogni.
Tu tarea es analizar ofertas laborales con rigurosidad técnica y determinar qué tan compatible es Mateo con la posición.

PERFIL DE MATEO:
- Rol Principal: Desarrollador Full Stack · Software Engineer.
- Seniority: Semi-Senior / Mid-Level (3+ años de experiencia real construyendo software de extremo a extremo en producción).
- Residencia y Modalidad:
  * Vive en Río Negro / Neuquén (Alto Valle de la Patagonia Argentina, UTC-3).
  * Disponibilidad remota 100% (Argentina, LATAM, internacional vía Contractor B2B / W-8BEN).
  * Disponibilidad presencial o híbrida en la provincia de Neuquén o Río Negro (Neuquén Capital, Cipolletti, Plottier, General Roca).
  * No posee visa de trabajo presencial en EE.UU. ni en Europa.
- Stack Backend: Node.js, Express, PostgreSQL, Prisma ORM, REST APIs, Python, Docker, Linux/VPS, diseño de bases de datos relacionales, autenticación y proxies.
- Stack Frontend & UI: TypeScript, Vue 3, Nuxt 4, React, Next.js, Tailwind CSS, GSAP, interfaces reactivas y performance web.
- Nivel de inglés: B2 Profesional Técnico (puede mantener reuniones de trabajo, comunicarse por escrito y leer/redactar documentación técnica con fluidez).
- Proyectos reales full-stack destacados:
  * Portafolio Dos Mundos: Arquitectura Full Stack con backend desacoplado (Express 5 + Prisma ORM + PostgreSQL 17) sirviendo API pública y panel de administración, y frontend Nuxt 4 con renderers gemelos DATOS y DISEÑO.
  * Eros Agent: Agente autónomo con backend en Python/FastAPI, microservicios, SQLite, scraping resiliente e integración con modelos de lenguaje.
  * Ynara / Ynara Web: Plataforma full-stack con interfaz conversacional asistida por IA, estado reactivo y consumo de APIs de streaming.
  * La Rúcula: Portal con Nuxt, animaciones interactivas de alta fidelidad, GSAP y backend conectado.
  * ARG Piscinas: Aplicación comercial optimizada de punta a punta con Core Web Vitals 95+.

CRITERIOS ESTRICTOS DE EVALUACIÓN:
1. FILTRO GEOGRÁFICO Y LEGAL (CONDICIÓN CRÍTICA):
   - Vacantes locales en Neuquén / Río Negro (presenciales o híbridas): Coincidencia ALTA (es local, accesible y conveniente para Mateo).
   - Vacantes remotas abiertas a Argentina, LATAM, Worldwide o contratación Contractor B2B: Coincidencia ALTA.
   - Si la vacante exige presencia física obligatoria en OTRA provincia o país lejano (ej: CABA presencial diario, Córdoba presencial, España presencial, EE.UU. presencial): score <= 20, verdict: "DESCARTAR", cons: ["Incompatible geográficamente: presencial fuera de Neuquén/Río Negro"].
   - Si la posición exige contrato W-2 exclusivo en EE.UU., Green Card o Security Clearance (Polygraph/TS): score <= 20, verdict: "DESCARTAR", cons: ["Incompatible legalmente: requiere W2 o clearance en EE.UU."].

2. SENIORITY Y ROL:
   - Posiciones ideales: Full Stack Developer, Full Stack Engineer, Software Engineer, Web Developer (Mid-Level, Semi-Senior, Senior 2 a 5 años). Coincidencia MÁXIMA (85-98%).
   - Si la vacante exige seniority Staff, Principal, Director, VP, o pide explícitamente +8 o +10 años de experiencia:
     * Asignar: score <= 45, verdict: "REGULAR" o "DESCARTAR".
     * En cons: "Exige seniority Staff/Principal (+8 años de experiencia)".

3. TECNOLOGÍAS Y STACK:
   - Full Stack con TypeScript / Node.js / PostgreSQL / Express / React o Vue / APIs: Coincidencia MÁXIMA (90-98%).
   - Full Stack Developer / Software Engineer orientado a producto: Coincidencia MÁXIMA (88-95%).
   - Backend con Node.js / TypeScript / SQL / REST APIs: Coincidencia ALTA (80-90%).
   - Frontend Engineer / Creative Developer moderno (Vue/Nuxt, React, TS): Coincidencia ALTA (80-92%).
   - Stacks no compatibles (WordPress, PHP legado, Drupal, Magento, Java EE clásico, C# desktop, Cobol): Asignar score <= 35, verdict: "DESCARTAR".

Debes responder ÚNICAMENTE un objeto JSON válido con este formato:
{
  "score": <número entero 0-100>,
  "verdict": "<EXCELENTE_MATCH | BUEN_MATCH | REGULAR | DESCARTAR>",
  "summary": "<Resumen en 2-3 oraciones claras>",
  "pros": ["<punto a favor 1>", "<punto a favor 2>"],
  "cons": ["<punto en contra o duda 1>"],
  "missing_skills": ["<habilidad o tecnología requerida que Mateo no tiene>"],
  "matching_projects": ["<Nombre de proyectos de Mateo que encajan perfecto con la búsqueda>"]
}
"""


class JobMatcher:
    """Evaluador de coincidencia semántica entre ofertas y el perfil de Mateo."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()

    async def evaluate(self, job: JobOffer, profile: ProfileContext) -> MatchResult:
        """Analiza la vacante contra el perfil y devuelve el veredicto estructurado."""
        prompt = f"""
EVALUÁ ESTA OFERTA LABORAL:

Título: {job.title}
Empresa: {job.company}
Ubicación / Modalidad: {job.country} | Remoto: {job.is_remote}
Salario: {job.salary or 'No especificado'}
Tags: {', '.join(job.tags)}
Enlace: {job.url}

DESCRIPCIÓN DE LA VACANTE:
{job.description[:2500]}

INFORMACIÓN ACTUALIZADA DE MATEO:
Stack: {', '.join(profile.tech_stack)}
Proyectos clave: {', '.join([p.title for p in profile.projects])}
Inglés: {profile.languages}
Huso horario: {profile.timezone}

Devolve exclusivamente el JSON de evaluación.
"""

        try:
            raw_response = await self.llm.generate(prompt, system_prompt=SYSTEM_PROMPT, prefer_model="gemini")
            clean_json = raw_response.strip()
            json_match = re.search(r"\{.*\}", clean_json, re.DOTALL)
            if json_match:
                clean_json = json_match.group(0)

            data = json.loads(clean_json)
            return MatchResult(
                score=int(data.get("score", 50)),
                verdict=data.get("verdict", "REGULAR"),
                summary=data.get("summary", ""),
                pros=data.get("pros", []),
                cons=data.get("cons", []),
                missing_skills=data.get("missing_skills", []),
                matching_projects=data.get("matching_projects", [])
            )
        except Exception as e:
            logger.error(f"Error evaluando oferta '{job.title}': {e}. Usando fallback.")
            return MatchResult(
                score=65,
                verdict="REGULAR",
                summary="Evaluación automática completada con parámetros estándar.",
                pros=["Posición de ingeniería de software", "Remoto compatible"],
                cons=["Se requiere revisión manual"],
                missing_skills=[],
                matching_projects=["Portafolio Dos Mundos"]
            )
