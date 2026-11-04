"""Artículos para el portafolio (mateogs.tech). Eros solo los escribe y los devuelve;
la API del portafolio es la que los publica."""

from typing import Annotated, Any
from pydantic import BaseModel, Field, field_validator

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
