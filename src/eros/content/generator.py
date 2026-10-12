import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from eros.config import get_settings
from eros.content.models import (
    ContentGenerateRequest,
    ContentPillar,
    ContentPost,
    ContentPostStatus,
    DevToArticle,
    SlideItem,
)
from eros.content.storage import ContentStorage
from eros.hunter.engine import HunterEngine
from eros.integrations.llm import LLMClient
from eros.models import ProfileContext, ProjectSummary

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """Eres el Agente Estratega de Contenido y Marca Técnica de Mateo Gabriel Sonzogni (Desarrollador Frontend & Full Stack · Creative Developer en Patagonia Argentina).

Tu objetivo es redactar contenido técnico omnicanal de altísimo valor ("high-signal engineering content") para LinkedIn, Twitter/X y Dev.to, junto a un guion de 5 diapositivas para un carousel visual.

Reglas inquebrantables de estilo y tono:
1. TONO: Ingenieril, honesto, empírico y directo. CERO frases motivacionales vacías de autoayuda ("persigue tus sueños", "nunca te rindas"). HABLA DE CÓDIGO, ARQUITECTURA, TRADE-OFFS Y MÉTRICAS REALES.
2. EVIDENCIA REAL: Conecta las lecciones con los proyectos reales de Mateo (Portafolio Dos Mundos, La Rúcula, Ynara, ARG Piscinas, null-net, lampone, Eros Agent).
3. FORMATO LINKEDIN:
   - REGLA ESTRICTA: CERO EMOJIS. No uses emojis bajo ninguna circunstancia. Usa viñetas de texto limpias ("•", "→", "-") o numeradas.
   - Gancho (Hook): Primeras 2 líneas directas, contrastantes o con métricas antes de que el usuario haga clic en "ver más".
   - Cuerpo: Problema real -> Hipótesis fallida o trade-off -> Arquitectura/Código implementado (bullet points con viñetas limpias: • o →) -> Métrica/Resultado medible.
   - Cierre y Pregunta de Debate: Invita a otros TLs y desarrolladores a opinar sobre el enfoque.
   - 3 a 5 hashtags específicos del ecosistema (#webdev #frontend #typescript #softwarearchitecture #vuejs).
   - Primer Comentario: Un comentario complementario con el enlace de producción o repositorio (ej: "Pueden ver la arquitectura en vivo y el panel en: https://mateogs.tech").
4. FORMATO TWITTER/X:
   - Un hilo de 3 a 5 tweets.
   - Cada tweet DEBE tener menos de 275 caracteres.
   - Numerados claramente: 1/4, 2/4, etc.
5. FORMATO DEV.TO:
   - Título atractivo y profesional.
   - 4 tags en minúsculas (ej: ["webdev", "javascript", "vue", "architecture"]).
   - Artículo completo en Markdown con subtítulos (##), bloques de código con sintaxis, diagramas conceptuales o listas.
6. CAROUSEL (5 DIAPOSITIVAS):
   - Slide 1 (Portada): Título contundente, subtítulo intrigante, autor y badge destacado.
   - Slide 2 (El Cuello de Botella / Problema): Qué fallaba o qué limitación existía en el diseño previo.
   - Slide 3 (La Solución Arquitectónica): Código o patrón técnico aplicado.
   - Slide 4 (Métricas y Benchmarks): Comparativa (antes vs después, latencia, bundle size, Lighthouse).
   - Slide 5 (Conclusión y CTA): Resumen accionable en 3 pasos + enlace a https://mateogs.tech.

RESPONDE EXCLUSIVAMENTE CON UN OBJETO JSON VÁLIDO según el esquema solicitado."""


class ContentGenerator:
    """Generador autónomo omnicanal de publicaciones técnicas y carousels."""

    def __init__(self, storage: ContentStorage | None = None, engine: HunterEngine | None = None):
        self.storage = storage or ContentStorage()
        self.engine = engine or HunterEngine()
        self.llm = LLMClient()
        self.settings = get_settings()

    async def generate_post(self, request: ContentGenerateRequest) -> ContentPost:
        """Crea una publicación completa omnicanal a partir de un tema o proyecto."""
        profile = await self.engine.get_active_profile()
        
        # Seleccionar proyecto de referencia si aplica
        selected_project: ProjectSummary | None = None
        if request.project_slug:
            selected_project = next((p for p in profile.projects if p.slug == request.project_slug), None)

        pillar = request.pillar or ContentPillar.ARCHITECTURE
        topic = request.topic or (
            f"Arquitectura y lecciones en producción de {selected_project.title}"
            if selected_project
            else "Optimización de rendimiento y arquitectura frontend moderna"
        )

        user_prompt = self._build_prompt(topic, pillar, selected_project, profile, request.custom_instructions)

        logger.info(f"Generando contenido omnicanal para tema: '{topic}' (Pilar: {pillar.value})...")
        raw_response = await self.llm.generate(
            prompt=user_prompt,
            system_prompt=SYSTEM_PROMPT,
            prefer_model="gemini",
            temperature=0.35,
            json_mode=True,
            max_tokens=4096,
        )

        post = self._parse_response(raw_response, topic, pillar, request.project_slug)
        await self.storage.save_post(post)
        logger.info(f"Publicación generada exitosamente con ID: {post.id}")
        return post

    def _build_prompt(
        self,
        topic: str,
        pillar: ContentPillar,
        project: ProjectSummary | None,
        profile: ProfileContext,
        custom_instructions: str | None,
    ) -> str:
        project_context = ""
        if project:
            project_context = f"""
PROYECTO DE REFERENCIA:
- Nombre: {project.title} ({project.slug})
- Resumen: {project.summary}
- Tecnologías: {', '.join(project.techs)}
- Resultados/Métricas: {project.outcome or 'En producción'}
- URL: {project.url or 'https://mateogs.tech'}
"""

        available_projects = ", ".join([f"{p.title} ({', '.join(p.techs[:3])})" for p in profile.projects])

        custom_block = f"\nINSTRUCCIONES ADICIONALES DEL AUTOR:\n{custom_instructions}" if custom_instructions else ""

        return f"""Tema a tratar: {topic}
Pilar de contenido: {pillar.value}

CONTEXTO DEL AUTOR:
- Nombre: {profile.name}
- Rol: {profile.role}
- Ubicación: {profile.location}
- Stack principal: {', '.join(profile.tech_stack[:10])}
- Proyectos en su portafolio: {available_projects}
{project_context}
{custom_block}

Genera un JSON con esta estructura exacta:
{{
  "title": "Título técnico atractivo para la pieza",
  "hook": "Las 2 primeras frases de alto impacto",
  "linkedin_post": "Texto completo formateado para LinkedIn SIN EMOJIS (prohibido emojis, usar viñetas '•' o '→') y hashtags",
  "first_comment": "Texto del primer comentario con el enlace al proyecto o portafolio",
  "twitter_thread": [
    "1/4 Tweet inicial...",
    "2/4 Tweet desarrollo...",
    "3/4 Tweet técnica/código...",
    "4/4 Tweet conclusión..."
  ],
  "devto_article": {{
    "title": "Título para Dev.to",
    "tags": ["tag1", "tag2", "tag3", "tag4"],
    "markdown_body": "Contenido completo en Markdown..."
  }},
  "carousel_slides": [
    {{
      "index": 1,
      "title": "Título Slide 1",
      "subtitle": "Subtítulo intrigante",
      "bullets": ["Punto 1", "Punto 2"],
      "metric_badge": "Ej: 99/100 Lighthouse",
      "code_snippet": null,
      "footer": "Mateo Sonzogni · mateogs.tech"
    }},
    {{
      "index": 2,
      "title": "Título Slide 2 (El Problema)",
      "subtitle": "Descripción del cuello de botella",
      "bullets": ["Punto 1", "Punto 2"],
      "metric_badge": null,
      "code_snippet": null,
      "footer": "Desafío técnico en producción"
    }},
    {{
      "index": 3,
      "title": "Título Slide 3 (La Solución)",
      "subtitle": "Implementación técnica",
      "bullets": ["Punto 1", "Punto 2"],
      "metric_badge": null,
      "code_snippet": "// Código o config clave...",
      "footer": "Arquitectura implementada"
    }},
    {{
      "index": 4,
      "title": "Título Slide 4 (Métricas)",
      "subtitle": "Resultados comprobables",
      "bullets": ["Punto 1", "Punto 2"],
      "metric_badge": "Ej: -65% Latencia",
      "code_snippet": null,
      "footer": "Impacto en producción"
    }},
    {{
      "index": 5,
      "title": "Título Slide 5 (Conclusión)",
      "subtitle": "Takeaway accionable",
      "bullets": ["Punto 1", "Punto 2", "Punto 3"],
      "metric_badge": "mateogs.tech",
      "code_snippet": null,
      "footer": "Desliza para conectar · @MateoGs013"
    }}
  ]
}}
"""

    def _parse_response(
        self,
        raw_text: str,
        topic: str,
        pillar: ContentPillar,
        project_slug: str | None
    ) -> ContentPost:
        """Parsea la respuesta JSON del LLM de forma resiliente."""
        cleaned = raw_text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except Exception as e:
            logger.error(f"Error parseando JSON de Gemini ({e}): {raw_text[:200]}")
            # Fallback seguro
            data = {
                "title": f"Lecciones de Ingeniería: {topic}",
                "hook": f"En producción, la teoría se choca con la realidad. Así abordamos {topic}.",
                "linkedin_post": f"{topic}\n\nEn producción las cosas cambian. Aquí los aprendizajes y decisiones clave.\n\n#webdev #architecture",
                "first_comment": "Podés ver más detalles técnicos en https://mateogs.tech",
                "twitter_thread": [f"1/2 Lecciones de producción sobre {topic}...", "2/2 Fin del hilo. Más en mateogs.tech"],
                "devto_article": {
                    "title": f"Cómo abordamos {topic}",
                    "tags": ["webdev", "architecture", "javascript", "vue"],
                    "markdown_body": f"# {topic}\n\nDetalles de arquitectura e implementación."
                },
                "carousel_slides": [
                    {"index": i, "title": f"Punto {i}", "subtitle": "Explicación", "bullets": ["Detalle"], "metric_badge": None, "code_snippet": None, "footer": "mateogs.tech"}
                    for i in range(1, 6)
                ]
            }

        post_id = f"post_{datetime.now().strftime('%Y%m%d%H%M')}_{uuid.uuid4().hex[:6]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        # Parsear slides
        slides = []
        for s in data.get("carousel_slides", []):
            slides.append(SlideItem(
                index=int(s.get("index", len(slides) + 1)),
                title=str(s.get("title", "")),
                subtitle=str(s.get("subtitle", "")),
                bullets=[str(b) for b in s.get("bullets", [])],
                metric_badge=s.get("metric_badge"),
                code_snippet=s.get("code_snippet"),
                footer=s.get("footer"),
            ))

        devto_data = data.get("devto_article", {})
        devto = DevToArticle(
            title=str(devto_data.get("title", data.get("title", topic))),
            tags=[str(t) for t in devto_data.get("tags", ["webdev", "architecture"])],
            markdown_body=str(devto_data.get("markdown_body", "")),
        )

        return ContentPost(
            id=post_id,
            title=str(data.get("title", topic)),
            topic=topic,
            pillar=pillar,
            project_slug=project_slug,
            hook=str(data.get("hook", "")),
            linkedin_text=str(data.get("linkedin_post", "")),
            first_comment=str(data.get("first_comment", "Portafolio y métricas en vivo: https://mateogs.tech")),
            twitter_thread=[str(t) for t in data.get("twitter_thread", [])],
            devto=devto,
            carousel_slides=slides,
            status=ContentPostStatus.DRAFT,
            created_at=now_iso,
            updated_at=now_iso,
        )
