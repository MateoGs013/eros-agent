from enum import Enum
from typing import Any
from pydantic import BaseModel, Field, field_validator
from eros.content.models import ContentPillar


class TrendSource(str, Enum):
    HACKER_NEWS = "HACKER_NEWS"
    DEVTO = "DEVTO"
    GITHUB = "GITHUB"
    TECH_RSS = "TECH_RSS"


class TrendStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    GENERATED = "GENERATED"
    DISCARDED = "DISCARDED"


class TrendItem(BaseModel):
    id: str
    title: str
    url: str
    source: TrendSource
    summary: str
    relevance_score: int = Field(ge=0, le=100)
    engineering_angle: str
    tags: list[str] = Field(default_factory=list)
    detected_at: str
    status: TrendStatus = TrendStatus.DISCOVERED
    post_id: str | None = None


class TrendScanResponse(BaseModel):
    total_found: int
    new_trends: int
    trends: list[TrendItem]


class TrendGenerateRequest(BaseModel):
    pillar: ContentPillar = ContentPillar.ARCHITECTURE
    project_slug: str | None = None
    custom_angle: str | None = None
    key_points: list[str] = Field(default_factory=list)
    custom_instructions: str | None = None

    @field_validator("pillar", mode="before")
    @classmethod
    def default_pillar(cls, v: Any) -> Any:
        # null o vacío → enfoque por defecto; acepta mayúsculas ("ARCHITECTURE")
        if v is None or (isinstance(v, str) and not v.strip()):
            return ContentPillar.ARCHITECTURE
        return v.strip().lower() if isinstance(v, str) else v
