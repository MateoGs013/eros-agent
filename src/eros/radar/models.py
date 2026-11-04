from enum import Enum
from pydantic import BaseModel, Field


class TrendSource(str, Enum):
    HACKER_NEWS = "HACKER_NEWS"
    DEVTO = "DEVTO"
    GITHUB = "GITHUB"
    TECH_RSS = "TECH_RSS"


class TrendStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    # Ya se escribió un artículo a partir de esta tendencia (POST /api/articles/generate con trend_id)
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
    # Post de la vieja publicación omnicanal: solo lo tienen tendencias anteriores a los artículos
    post_id: str | None = None


class TrendScanResponse(BaseModel):
    total_found: int
    new_trends: int
    trends: list[TrendItem]
