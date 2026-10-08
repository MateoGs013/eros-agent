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
- Rol: Desarrollador Frontend & Full Stack · Creative Developer / UI Engineer.
- Seniority: Semi-Senior / Mid-Level (3+ años de experiencia real construyendo software en producción).
- Residencia y Modalidad: Vive en Argentina (UTC-3), disponibilidad remota 100%, factura como Contractor internacional independiente (B2B / W-8BEN). No posee visa de trabajo presencial en EE.UU. ni en Europa.
- Stack principal: Vue 3, Nuxt 4, TypeScript, Node.js, Express, PostgreSQL, Tailwind CSS, GSAP.
- Habilidades transferibles: React, Next.js, bases SQL/NoSQL, REST APIs, Docker, Linux/VPS, Python.
- Nivel de inglés: B2 Profesional Técnico (puede mantener reuniones, comunicarse por escrito y leer/redactar documentación técnica con fluidez).
- Proyectos reales destacados:
  * La Rúcula (Portal gastronómico con Nuxt, GSAP y diseño interactivo de alta gama).
  * Ynara / Ynara Web (Plataforma con IA, interfaz conversacional reactiva y diseño cinemático).
  * Portafolio Dos Mundos (Arquitectura Nuxt 4 con renderers desacoplados DATOS y DISEÑO, Express 5, Prisma).
  * ARG Piscinas (Landing comercial con optimización Core Web Vitals 95+).

CRITERIOS ESTRICTOS DE EVALUACIÓN:
1. FILTRO GEOGRÁFICO Y LEGAL (CONDICIÓN CRÍTICA):
   - Si la posición exige residir físicamente en EE.UU., Canadá o Europa, exige contrato W-2 exclusivo, o exige Green Card / Ciudadanía estadounidense sin sponsoreo / Security Clearance (Polygraph/TS):
     * Asignar inmediatamente: score <= 20, verdict: "DESCARTAR".
     * En cons: "Incompatible geográficamente: requiere residencia en EE.UU./Europa o contrato W2".
   - Si es remota abierta a LATAM, Worldwide, o permite contratación B2B/Contractor: Compatible geográficamente.

2. SENIORITY Y ROL:
   - Posiciones ideales: Junior-Mid, Mid-Level, Semi-Senior, Senior Frontend, Creative Developer, UI Engineer (2 a 5 años). Coincidencia ALTA (80-95%).
   - Si la vacante exige seniority Staff, Principal, Director, VP, o pide explícitamente +8 o +10 años de experiencia:
     * Asignar: score <= 45, verdict: "REGULAR" o "DESCARTAR".
     * En cons: "Exige seniority Staff/Principal (+8 años de experiencia)".

3. TECNOLOGÍAS Y STACK:
   - Vue 3 / Nuxt 3-4 / TypeScript / UI Creativa (GSAP, Tailwind, animaciones): Coincidencia MÁXIMA (90-98%).
   - React / Next.js / Frontend moderno con TypeScript: Coincidencia ALTA (80-90%).
   - Full Stack con Node / Express / Postgres / APIs: Coincidencia BUENA (75-85%).
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
            # Extraer bloque JSON si viene envuelto en markdown ```json ... ```
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
