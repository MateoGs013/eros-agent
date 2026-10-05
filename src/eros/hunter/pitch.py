import json
import logging
import re
from eros.integrations.llm import LLMClient
from eros.models import JobOffer, MatchResult, PitchDraft, ProfileContext

logger = logging.getLogger(__name__)

PITCH_SYSTEM_PROMPT = """
Sos el redactor técnico de presentaciones de Mateo Gabriel Sonzogni.
Tu objetivo es redactar un pitch / mensaje de postulación conciso, convincente y de alto impacto técnico para una vacante específica.

REGLAS DE ESCRITURA:
1. NADA DE CLICHÉS NI SLOP CORPORATIVO ("Estimado equipo, me dirijo con gran entusiasmo...").
2. Comenzar directo al valor: quién es Mateo, qué problemas ha resuelto y cómo se conecta su experiencia con lo que la empresa busca.
3. Mencionar proyectos reales como evidencia concreta (ej. arquitectura en Nuxt 4, animaciones GSAP, APIs en Node/Express, PostgreSQL, deploy en VPS con Docker).
4. Incluir el enlace al portafolio en vivo: https://mateogs.tech
5. Idioma: Si la oferta laboral está en inglés, redactá en INGLÉS fluido y profesional. Si está en español, redactá en ESPAÑOL rioplatense neutro.

Debes responder ÚNICAMENTE un objeto JSON válido con este formato:
{
  "subject_or_hook": "<Línea de asunto o primer gancho directo>",
  "elevator_pitch": "<Mensaje corto de 3-4 párrafos para LinkedIn/Email directo/Formulario>",
  "cover_letter": "<Carta de presentación completa si el formulario exige cover letter>",
  "suggested_projects": ["<Proyecto 1 a destacar>", "<Proyecto 2 a destacar>"]
}
"""


class PitchGenerator:
    """Generador de propuestas y cartas de presentación personalizadas."""

    def __init__(self, llm_client: LLMClient | None = None):
        self.llm = llm_client or LLMClient()

    async def generate_pitch(
        self,
        job: JobOffer,
        profile: ProfileContext,
        match: MatchResult | None = None
    ) -> PitchDraft:
        """Redacta una propuesta específica conectando los requisitos con el portfolio de Mateo."""
        prompt = f"""
REDACTÁ UNA PROPUESTA PARA ESTA OFERTA:

Empresa: {job.company}
Puesto: {job.title}
Descripción y Requisitos:
{job.description[:2500]}

DATOS DE MATEO:
Rol: {profile.role}
Stack: {', '.join(profile.tech_stack)}
Proyectos Relevantes: {', '.join([f'{p.title} ({p.summary})' for p in profile.projects[:4]])}
Puntos a favor detectados: {', '.join(match.pros if match else [])}

Devolve exclusivamente el objeto JSON con la propuesta.
"""

        try:
            raw_response = await self.llm.generate(prompt, system_prompt=PITCH_SYSTEM_PROMPT, prefer_model="claude")
            clean_json = raw_response.strip()
            json_match = re.search(r"\{.*\}", clean_json, re.DOTALL)
            if json_match:
                clean_json = json_match.group(0)

            data = json.loads(clean_json)
            return PitchDraft(
                subject_or_hook=data.get("subject_or_hook", f"Full-stack / Frontend Engineer — Mateo Sonzogni ({job.title})"),
                elevator_pitch=data.get("elevator_pitch", ""),
                cover_letter=data.get("cover_letter", ""),
                suggested_projects=data.get("suggested_projects", [])
            )
        except Exception as e:
            logger.error(f"Error generando pitch para '{job.title}': {e}. Usando plantilla directa.")
            return PitchDraft(
                subject_or_hook=f"Frontend & Full Stack Developer — Mateo Sonzogni ({job.title})",
                elevator_pitch=(
                    f"Hola equipo de {job.company},\n\n"
                    f"Les escribo porque vi la posición de {job.title} y mi perfil técnico coincide directamente con los desafíos de la posición. "
                    f"Me especializo en TypeScript, Vue 3, Nuxt y Node.js, trabajando la intersección entre experiencia de usuario cuidada y arquitectura sólida de backend (PostgreSQL, Docker, APIs REST).\n\n"
                    f"Pueden ver mis proyectos en producción, código y métricas en vivo en mi portafolio: https://mateogs.tech\n\n"
                    f"Quedo a disposición para conversar. Saludos,\nMateo Sonzogni"
                ),
                cover_letter="Disponible previa solicitud.",
                suggested_projects=["Portafolio Dos Mundos", "La Rúcula"]
            )
