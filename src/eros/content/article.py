"""Artículos largos para el portafolio (mateogs.tech), en español y en inglés.

Eros solo los escribe y los devuelve: la API del portafolio es la que los publica.
Son dos llamadas a la IA: el artículo en español y después su traducción fiel al inglés.
Lo que vuelve se valida contra lo que el portafolio sabe mostrar; si no cumple, se lanza
LLMOutputError con el motivo en vez de devolver un artículo roto.
"""

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from eros.config import get_settings
from eros.content.models import (
    ARTICLE_MARKDOWN_MAX,
    ARTICLE_SUMMARY_MAX,
    ARTICLE_TITLE_MAX,
    ArticleGenerateRequest,
    ArticleResult,
    ArticleVersion,
)
from eros.hunter.engine import HunterEngine
from eros.integrations.llm import LLMClient, LLMOutputError
from eros.models import ProfileContext, ProjectSummary
from eros.radar.models import TrendItem, TrendStatus
from eros.radar.storage import RadarStorage

logger = logging.getLogger(__name__)

# Un artículo de 1500 palabras más el JSON no entra en los 4096 tokens ni en los 45 s de siempre.
# Los modelos flash que razonan descuentan ese razonamiento del mismo tope, por eso sobra margen.
ARTICLE_MAX_TOKENS = 16384
ARTICLE_TIMEOUT = 150.0

MIN_WORDS_ES = 500
# La traducción no puede quedar mucho más corta que el original (sería un resumen o vino cortada)
MIN_TRANSLATION_RATIO = 0.6
MAX_TAGS = 6
MAX_TAG_LENGTH = 24

ES_INCOMPLETE = "El artículo vino incompleto"
ES_FORMAT = "El artículo no respeta el formato del portafolio"
EN_INCOMPLETE = "La traducción al inglés vino incompleta"
EN_FORMAT = "La traducción al inglés no respeta el formato del portafolio"


SYSTEM_PROMPT_ES = """Sos el redactor técnico de Mateo Gabriel Sonzogni (Desarrollador Frontend & Full Stack · Creative Developer en la Patagonia argentina). Escribís artículos largos para su portafolio, mateogs.tech, en primera persona como Mateo y en español rioplatense (voseo), con tono ingenieril, honesto y concreto.

Reglas inquebrantables:
1. VOZ: primera persona ("armé", "elegí", "me equivoqué"). CERO frases motivacionales o de relleno. Hablá de código, arquitectura, decisiones y trade-offs.
2. DATOS: NUNCA inventes métricas, porcentajes, latencias, puntajes de Lighthouse, benchmarks ni cantidades de usuarios. Usá solo números que aparezcan en los datos que te paso; si no hay un dato real, describí el cambio sin número.
3. EVIDENCIA REAL: NUNCA inventes proyectos, clientes, empresas ni experiencia. Solo podés citar los proyectos reales de la lista del perfil, con su nombre tal cual. Si el tema es general, anclalo en uno de esos proyectos o en el stack real de Mateo.
4. LARGO: el cuerpo tiene entre 900 y 1500 palabras (sin contar el código).
5. FORMATO DEL CUERPO (solo el Markdown que el portafolio sabe mostrar):
   - Subtítulos con ## y ###. Nunca # (el título va aparte: no lo repitas en el cuerpo).
   - Párrafos, listas con viñetas o numeradas, citas con >, bloques de código con ``` y el lenguaje, código en línea con `, negrita e itálica.
   - Enlaces solo a direcciones http:// o https://.
   - PROHIBIDO: tablas, imágenes, HTML crudo y emojis (tampoco en el título ni en el resumen).
   - Etiquetas o tipos como <template> o Array<string> van siempre dentro de código.
6. TÍTULO de hasta 160 caracteres. RESUMEN de hasta 400 caracteres: una o dos frases que digan de qué trata y qué se lleva quien lo lee.
7. TAGS: de 1 a 6, en minúsculas y cortos (una palabra, o dos unidas con guion), por ejemplo "nuxt", "postgres", "accesibilidad".

RESPONDÉ EXCLUSIVAMENTE CON UN OBJETO JSON VÁLIDO según el esquema pedido."""


SYSTEM_PROMPT_EN = """You translate Mateo Gabriel Sonzogni's portfolio articles (mateogs.tech) from Spanish into natural, technical English.

Rules:
1. Faithful translation: same content, same first-person voice, same structure (the same headings, lists, quotes and code blocks, in the same order). Do not add, drop or summarize anything, and never invent data, metrics or clients.
2. Keep code blocks and inline code exactly as they are (you may translate comments inside code). Keep every link URL unchanged.
3. Same Markdown rules: ## and ### headings only (never #), no tables, no images, no raw HTML, no emojis.
4. Title up to 160 characters; summary up to 400 characters.

Reply ONLY with a valid JSON object following the requested schema."""


# ──────────────────────────────────────────────────────────────────────────────
# Validación del Markdown
# ──────────────────────────────────────────────────────────────────────────────

FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
INLINE_CODE_RE = re.compile(r"`+[^`]*`+")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
IMAGE_RE = re.compile(r"!\[[^\]]*\]\(")
LINK_RE = re.compile(r"(?<!!)\[[^\]]*\]\(\s*<?([^)\s>]*)")
REF_LINK_RE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?(?:\s|$)")
HTML_TAG_RE = re.compile(
    r"<!--|<\s*/?\s*(?:a|abbr|article|aside|audio|b|blockquote|br|button|canvas|center|code|del|details|div|em|embed|"
    r"figcaption|figure|font|form|h[1-6]|hr|i|iframe|img|input|ins|kbd|li|link|mark|meta|object|ol|p|picture|pre|"
    r"s|script|section|small|source|span|strong|style|sub|summary|sup|svg|table|tbody|td|th|thead|tr|u|ul|video)\b[^>]*>",
    re.IGNORECASE,
)
EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"  # pictogramas, emoticones, transporte, banderas
    "☀-➿"  # símbolos varios y dingbats (☀ ✅ ✨ ❌)
    "⬅-⬇⬛⬜⭐⭕"
    "⌚⌛⏩-⏳⏸-⏺"
    "️"  # selector de variante emoji
    "]"
)
WORD_RE = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*")


def _prose_lines(markdown: str) -> list[str]:
    """Líneas fuera de los bloques de código, sin el código en línea. Lanza ValueError si un bloque no cierra."""
    lines: list[str] = []
    fence: str | None = None
    for line in markdown.split("\n"):
        m = FENCE_RE.match(line)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            continue
        if m:
            fence = m.group(1)
            continue
        lines.append(INLINE_CODE_RE.sub("", line))
    if fence:
        raise ValueError("un bloque de código quedó sin cerrar")
    return lines


def normalize_markdown(markdown: str) -> str:
    """Saca el H1 inicial (el título va aparte), baja otros # a ## y los ####+ a ###.

    No toca el contenido de los bloques de código.
    """
    out: list[str] = []
    fence: str | None = None
    seen_content = False
    for line in markdown.replace("\r\n", "\n").split("\n"):
        m = FENCE_RE.match(line)
        if fence:
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = None
            out.append(line)
            continue
        if m:
            fence = m.group(1)
            seen_content = True
            out.append(line)
            continue
        heading = HEADING_RE.match(line)
        if heading:
            level = len(heading.group(1))
            if level == 1 and not seen_content:
                seen_content = True
                continue
            if level == 1:
                line = f"## {heading.group(2)}"
            elif level > 3:
                line = f"### {heading.group(2)}"
        if line.strip():
            seen_content = True
        out.append(line)
    return "\n".join(out).strip()


def find_emoji(text: str) -> str | None:
    m = EMOJI_RE.search(text or "")
    return m.group(0) if m else None


def find_format_problem(markdown: str) -> str | None:
    """Devuelve el primer motivo por el que el portafolio no podría mostrar el Markdown, o None."""
    for line in _prose_lines(markdown):
        stripped = line.strip()
        if len(stripped) > 1 and stripped.startswith("|") and stripped.endswith("|"):
            return f"tiene una tabla ({stripped[:60]})"
        tag = HTML_TAG_RE.search(line)
        if tag:
            return f"tiene HTML crudo ({tag.group(0)[:60]})"
        if IMAGE_RE.search(line):
            return "tiene una imagen"
        urls = [m.group(1) for m in LINK_RE.finditer(line)]
        ref = REF_LINK_RE.match(line)
        if ref:
            urls.append(ref.group(1))
        for url in urls:
            if not re.match(r"https?://", url, re.IGNORECASE):
                return f"tiene un enlace que no es http/https ({url[:60] or 'vacío'})"
    emoji = find_emoji(markdown)
    if emoji:
        return f"tiene emojis ({emoji})"
    return None


def count_words(markdown: str) -> int:
    """Palabras del texto, sin contar los bloques de código ni las direcciones de los enlaces."""
    try:
        lines = _prose_lines(markdown)
    except ValueError:
        lines = markdown.split("\n")
    text = re.sub(r"\]\([^)]*\)", "]", "\n".join(lines))
    return len(WORD_RE.findall(text))


def normalize_tags(raw: Any) -> list[str]:
    """Minúsculas, sin #, espacios a guion; descarta vacíos, repetidos y largos. Máximo 6."""
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, list):
        return []
    tags: list[str] = []
    for item in raw:
        tag = str(item).strip().lower().lstrip("#").strip()
        tag = re.sub(r"\s+", "-", tag)
        tag = re.sub(r"[^\w.+#-]", "", tag).strip("-.")
        if not tag or len(tag) > MAX_TAG_LENGTH or tag in tags:
            continue
        tags.append(tag)
    return tags[:MAX_TAGS]


def _load_json(raw_text: str, incomplete: str) -> dict[str, Any]:
    cleaned = (raw_text or "").strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    try:
        data = json.loads(cleaned.strip())
    except Exception as e:
        logger.error(f"Respuesta de IA inutilizable para el artículo ({e}): {(raw_text or '')[:200]}")
        raise LLMOutputError(f"{incomplete}: la IA no devolvió un JSON válido ({e}).") from e
    if not isinstance(data, dict):
        raise LLMOutputError(f"{incomplete}: la IA no devolvió un objeto JSON.")
    return data


def validate_version(data: dict[str, Any], incomplete: str, bad_format: str) -> ArticleVersion:
    """Valida título, resumen y Markdown de una versión del artículo (es o en)."""
    fields: dict[str, str] = {}
    for name in ("title", "summary", "markdown"):
        value = data.get(name)
        if not isinstance(value, str) or not value.strip():
            raise LLMOutputError(f"{incomplete}: falta el campo «{name}».")
        fields[name] = value.strip()

    title, summary = fields["title"], fields["summary"]
    if len(title) > ARTICLE_TITLE_MAX:
        raise LLMOutputError(f"{bad_format}: el título tiene {len(title)} caracteres (máximo {ARTICLE_TITLE_MAX}).")
    if len(summary) > ARTICLE_SUMMARY_MAX:
        raise LLMOutputError(f"{bad_format}: el resumen tiene {len(summary)} caracteres (máximo {ARTICLE_SUMMARY_MAX}).")
    for label, text in (("título", title), ("resumen", summary)):
        emoji = find_emoji(text)
        if emoji:
            raise LLMOutputError(f"{bad_format}: el {label} tiene emojis ({emoji}).")
        if HTML_TAG_RE.search(text):
            raise LLMOutputError(f"{bad_format}: el {label} tiene HTML crudo.")

    markdown = normalize_markdown(fields["markdown"])
    if not markdown:
        raise LLMOutputError(f"{incomplete}: el cuerpo quedó vacío.")
    if len(markdown) > ARTICLE_MARKDOWN_MAX:
        raise LLMOutputError(f"{bad_format}: el cuerpo tiene {len(markdown)} caracteres (máximo {ARTICLE_MARKDOWN_MAX}).")
    try:
        problem = find_format_problem(markdown)
    except ValueError as e:
        raise LLMOutputError(f"{incomplete}: {e}.") from e
    if problem:
        raise LLMOutputError(f"{bad_format}: el cuerpo {problem}.")

    return ArticleVersion(title=title, summary=summary, markdown=markdown)


@dataclass
class SpanishDraft:
    topic: str
    tags: list[str]
    project_slug: str | None
    version: ArticleVersion


def parse_spanish_article(
    raw_text: str,
    requested_topic: str | None = None,
    forced_project_slug: str | None = None,
    known_project_slugs: list[str] | None = None,
) -> SpanishDraft:
    """Parsea y valida el artículo en español. Si no sirve, lanza LLMOutputError (nunca hay relleno)."""
    data = _load_json(raw_text, ES_INCOMPLETE)
    version = validate_version(data, ES_INCOMPLETE, ES_FORMAT)

    words = count_words(version.markdown)
    if words < MIN_WORDS_ES:
        raise LLMOutputError(
            f"{ES_INCOMPLETE}: tiene {words} palabras y el mínimo es {MIN_WORDS_ES} (se pidieron entre 900 y 1500)."
        )

    tags = normalize_tags(data.get("tags"))
    if not tags:
        raise LLMOutputError(f"{ES_INCOMPLETE}: no trae tags.")

    topic = str(data.get("topic") or "").strip() or requested_topic or version.title
    slug = forced_project_slug
    if not slug:
        candidate = str(data.get("project_slug") or "").strip()
        slug = candidate if candidate in (known_project_slugs or []) else None

    return SpanishDraft(topic=topic[:300], tags=tags, project_slug=slug, version=version)


def parse_english_translation(raw_text: str, spanish: ArticleVersion) -> ArticleVersion:
    """Parsea y valida la traducción. Tiene que conservar el largo del original (no un resumen)."""
    data = _load_json(raw_text, EN_INCOMPLETE)
    version = validate_version(data, EN_INCOMPLETE, EN_FORMAT)
    words_es = count_words(spanish.markdown)
    words_en = count_words(version.markdown)
    if words_en < words_es * MIN_TRANSLATION_RATIO:
        raise LLMOutputError(
            f"{EN_INCOMPLETE}: tiene {words_en} palabras contra {words_es} del original en español."
        )
    return version


# ──────────────────────────────────────────────────────────────────────────────
# Generador
# ──────────────────────────────────────────────────────────────────────────────

class ArticleRequestError(ValueError):
    """El pedido apunta a algo que no existe (proyecto o tendencia). `code` va al error de la tarea."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


class ArticleGenerator:
    """Escribe un artículo para el portafolio en español y su traducción al inglés."""

    def __init__(self, engine: HunterEngine | None = None, radar_storage: RadarStorage | None = None):
        self.engine = engine or HunterEngine()
        self.radar_storage = radar_storage or RadarStorage()
        self.llm = LLMClient()
        self.settings = get_settings()

    async def generate(self, request: ArticleGenerateRequest) -> ArticleResult:
        profile = await self.engine.get_active_profile()
        project = None
        if request.project_slug:
            profile, project = await self._find_project(profile, request.project_slug)

        trend: TrendItem | None = None
        if request.trend_id:
            trend = await self.radar_storage.get_trend(request.trend_id)
            if not trend:
                raise ArticleRequestError(f"La tendencia «{request.trend_id}» no existe en el Radar.", code="trend_not_found")

        prompt = self._build_prompt(request, profile, project, trend)
        logger.info(f"Escribiendo artículo para el portafolio (tema: {request.topic or 'lo elige Eros'})...")
        raw_es, model_es = await self._write(prompt, SYSTEM_PROMPT_ES, temperature=0.5, failure=ES_INCOMPLETE)
        draft = parse_spanish_article(
            raw_es,
            requested_topic=request.topic or (trend.title if trend else None),
            forced_project_slug=project.slug if project else None,
            known_project_slugs=[p.slug for p in profile.projects],
        )

        logger.info(f"Traduciendo al inglés: '{draft.version.title}'...")
        raw_en, model_en = await self._write(
            self._build_translation_prompt(draft.version), SYSTEM_PROMPT_EN, temperature=0.2, failure=EN_INCOMPLETE
        )
        english = parse_english_translation(raw_en, draft.version)

        if trend:
            await self.radar_storage.update_status(trend.id, TrendStatus.GENERATED)

        model = model_es if model_es == model_en else f"{model_es} (es) · {model_en} (en)"
        return ArticleResult(
            topic=draft.topic,
            project_slug=draft.project_slug,
            trend_id=trend.id if trend else None,
            tags=draft.tags,
            es=draft.version,
            en=english,
            model=model,
        )

    async def _find_project(self, profile: ProfileContext, slug: str) -> tuple[ProfileContext, ProjectSummary]:
        """Busca el proyecto en el perfil; si no está, sincroniza una vez (puede ser una obra recién publicada)."""
        project = next((p for p in profile.projects if p.slug == slug), None)
        if not project:
            try:
                profile = await self.engine.sync_profile()
            except Exception as e:
                logger.warning(f"No se pudo sincronizar el perfil buscando el proyecto '{slug}': {e}")
            project = next((p for p in profile.projects if p.slug == slug), None)
        if not project:
            raise ArticleRequestError(f"El proyecto «{slug}» no está en el perfil del portafolio.", code="project_not_found")
        return profile, project

    async def _write(self, prompt: str, system_prompt: str, temperature: float, failure: str) -> tuple[str, str]:
        """Una llamada larga a la IA. Sin IA lanza LLMUnavailableError; cortada, LLMOutputError."""
        self.llm.last_model = None
        try:
            raw = await self.llm.generate(
                prompt=prompt,
                system_prompt=system_prompt,
                prefer_model="gemini",
                temperature=temperature,
                json_mode=True,
                max_tokens=ARTICLE_MAX_TOKENS,
                timeout=ARTICLE_TIMEOUT,
            )
        except LLMOutputError as e:
            reason = str(e)
            raise LLMOutputError(f"{failure}: {reason[:1].lower()}{reason[1:]}") from e
        return raw, self.llm.last_model or self.settings.gemini_model

    def _build_prompt(
        self,
        request: ArticleGenerateRequest,
        profile: ProfileContext,
        project: ProjectSummary | None,
        trend: TrendItem | None,
    ) -> str:
        if request.topic:
            topic_block = f"TEMA: {request.topic}"
        elif project:
            topic_block = f"TEMA: elegilo vos. Una decisión técnica, un problema o una técnica concreta del proyecto {project.title}."
        elif trend:
            topic_block = f"TEMA: {trend.title}, contado desde la experiencia real de Mateo (no como noticia)."
        else:
            topic_block = (
                "TEMA: elegilo vos. Tiene que estar anclado en uno de los proyectos reales de la lista o en el stack real "
                "de Mateo, y ser algo concreto (una decisión, un problema, una técnica), no un panorama general."
            )

        projects = "\n".join(
            f"- {p.title} (slug: {p.slug}) · {p.summary} · Tecnologías: {', '.join(p.techs) or 'sin datos'}"
            f" · Resultados publicados: {p.outcome or 'ninguno'} · URL: {p.url or 'https://mateogs.tech'}"
            for p in profile.projects
        ) or "- (el perfil no trae proyectos: anclá el artículo en el stack real)"

        blocks = [
            topic_block,
            f"""CONTEXTO DEL AUTOR:
- Nombre: {profile.name}
- Rol: {profile.role}
- Ubicación: {profile.location}
- Stack principal: {', '.join(profile.tech_stack[:15]) or 'sin datos'}""",
        ]
        if profile.engineering_philosophy:
            blocks.append(f"FILOSOFÍA DE INGENIERÍA DE MATEO:\n{profile.engineering_philosophy}")
        blocks.append(f"PROYECTOS REALES (los únicos que podés citar):\n{projects}")

        if project:
            blocks.append(f"""PROYECTO DE REFERENCIA (el artículo se ancla en este; "project_slug" es "{project.slug}"):
- Nombre: {project.title}
- Resumen: {project.summary}
- Tecnologías: {', '.join(project.techs)}
- Resultados publicados: {project.outcome or 'ninguno (no des números)'}
- URL: {project.url or 'https://mateogs.tech'}""")

        if trend:
            blocks.append(f"""TENDENCIA DEL RADAR (punto de partida, no el centro: el centro es lo que Mateo hizo o haría):
- Título: {trend.title}
- Referencia original: {trend.url} (podés enlazarla)
- Síntesis: {trend.summary}
- Ángulo de ingeniería: {trend.engineering_angle}
- Tags: {', '.join(trend.tags) or 'sin tags'}""")

        if request.angle:
            blocks.append(f"ÁNGULO PEDIDO POR EL AUTOR (tiene prioridad):\n{request.angle}")

        if request.avoid_titles:
            titles = "\n".join(f"- {t}" for t in request.avoid_titles)
            blocks.append(f"ARTÍCULOS YA PUBLICADOS (no repitas ninguno de estos temas ni escribas un título parecido):\n{titles}")

        blocks.append("""Generá un JSON con esta estructura exacta:
{
  "topic": "El tema en una frase corta",
  "title": "Título del artículo (máximo 160 caracteres, sin emojis)",
  "summary": "Resumen de una o dos frases (máximo 400 caracteres)",
  "tags": ["nuxt", "postgres"],
  "project_slug": "slug del proyecto real en el que se ancla, o null",
  "markdown": "Cuerpo completo en Markdown, de 900 a 1500 palabras, empezando con un párrafo (sin título #)"
}""")
        return "\n\n".join(blocks)

    def _build_translation_prompt(self, spanish: ArticleVersion) -> str:
        original = json.dumps(
            {"title": spanish.title, "summary": spanish.summary, "markdown": spanish.markdown},
            ensure_ascii=False,
            indent=2,
        )
        return f"""Translate this article into English.

ORIGINAL (Spanish, JSON):
{original}

Return a JSON object with this exact structure:
{{
  "title": "English title (max 160 characters)",
  "summary": "English summary (max 400 characters)",
  "markdown": "Full English body in Markdown, same structure as the original"
}}"""
