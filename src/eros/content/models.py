from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Any
from pydantic import BaseModel, Field, field_validator


class ContentPostStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    PUBLISHED = "published"
    REJECTED = "rejected"


# Canales que el workflow de n8n publica. Dev.to no tiene publicación automática todavía:
# se rechaza en vez de responder "despachado" y que nunca salga.
PUBLISH_CHANNELS = ("all", "linkedin", "twitter")


class ContentPillar(str, Enum):
    ARCHITECTURE = "architecture"
    PRODUCTION_LESSONS = "production_lessons"
    PERFORMANCE_OPTIMIZATION = "performance_optimization"
    AI_AGENT_OPS = "ai_agent_ops"
    FULLSTACK_ENGINEERING = "fullstack_engineering"


class SlideItem(BaseModel):
    index: int
    title: str
    subtitle: str
    bullets: list[str] = Field(default_factory=list)
    metric_badge: str | None = None
    code_snippet: str | None = None
    footer: str | None = None


class DevToArticle(BaseModel):
    title: str
    tags: list[str] = Field(default_factory=list)
    markdown_body: str


class ContentPost(BaseModel):
    id: str
    title: str
    topic: str
    pillar: ContentPillar
    project_slug: str | None = None
    hook: str
    linkedin_text: str
    first_comment: str
    twitter_thread: list[str] = Field(default_factory=list)
    devto: DevToArticle
    carousel_slides: list[SlideItem] = Field(default_factory=list)
    status: ContentPostStatus = ContentPostStatus.DRAFT
    n8n_published_at: str | None = None
    n8n_response: str | None = None
    # Canales ya despachados a n8n (esperando o con confirmación) y cuándo se despachó
    dispatched_channels: list[str] = Field(default_factory=list)
    dispatched_at: str | None = None
    # Canales que n8n confirmó como publicados (callback)
    published_channels: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ContentGenerateRequest(BaseModel):
    topic: str | None = None
    pillar: ContentPillar | None = None
    project_slug: str | None = None
    custom_instructions: str | None = None
    key_points: list[str] = Field(default_factory=list)


class ContentPublishRequest(BaseModel):
    channel: str = "all"


class ContentStatusUpdateRequest(BaseModel):
    status: ContentPostStatus


# ──────────────────────────────────────────────────────────────────────────────
# Artículos para el portafolio (mateogs.tech). Eros solo los escribe y los devuelve;
# la API del portafolio es la que los publica.
# ──────────────────────────────────────────────────────────────────────────────

ARTICLE_TITLE_MAX = 160
ARTICLE_SUMMARY_MAX = 400
ARTICLE_MARKDOWN_MAX = 60000


class ArticleGenerateRequest(BaseModel):
    """Cuerpo de POST /api/articles/generate. Todo es opcional: sin tema, Eros elige uno."""
    topic: str | None = Field(default=None, max_length=300)
    project_slug: str | None = None
    trend_id: str | None = None
    angle: str | None = Field(default=None, max_length=1000)
    # Títulos ya publicados en el portafolio: el tema nuevo no puede repetirlos
    avoid_titles: list[Annotated[str, Field(max_length=200)]] = Field(default_factory=list, max_length=300)

    @field_validator("topic", "project_slug", "trend_id", "angle", mode="after")
    @classmethod
    def blank_is_none(cls, v: str | None) -> str | None:
        if v is None:
            return None
        return v.strip() or None

    @field_validator("avoid_titles", mode="before")
    @classmethod
    def null_is_empty(cls, v: Any) -> Any:
        return [] if v is None else v

    @field_validator("avoid_titles", mode="after")
    @classmethod
    def drop_blank_titles(cls, v: list[str]) -> list[str]:
        return [t.strip() for t in v if t and t.strip()]


class ArticleVersion(BaseModel):
    title: str
    summary: str
    markdown: str


class ArticleResult(BaseModel):
    """`result` de la tarea "article" en GET /api/tasks/{id} (contrato con el portafolio)."""
    topic: str
    project_slug: str | None = None
    trend_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    es: ArticleVersion
    en: ArticleVersion
    model: str
