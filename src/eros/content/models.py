from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class ContentPostStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    PUBLISHED = "published"
    REJECTED = "rejected"


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
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ContentGenerateRequest(BaseModel):
    topic: str | None = None
    pillar: ContentPillar | None = None
    project_slug: str | None = None
    custom_instructions: str | None = None


class ContentStatusUpdateRequest(BaseModel):
    status: ContentPostStatus
