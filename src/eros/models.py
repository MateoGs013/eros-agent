from datetime import datetime, timezone
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class JobStatus(str, Enum):
    NEW = "new"
    EVALUATED = "evaluated"
    SAVED = "saved"
    APPLIED = "applied"
    DISCARDED = "discarded"


class JobOffer(BaseModel):
    """Modelo normalizado para vacantes de cualquier fuente."""
    id: str  # Hash único basado en source + external_id o url
    source: str  # 'getonboard', 'remoteok', 'hackernews', etc.
    external_id: str
    title: str
    company: str
    url: str
    description: str
    tags: list[str] = Field(default_factory=list)
    salary: str | None = None
    country: str | None = None
    is_remote: bool = True
    published_at: str | int | None = None
    found_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: JobStatus = JobStatus.NEW

    # Resultados de análisis
    match_score: int | None = None
    match_analysis: str | None = None
    pitch_draft: str | None = None
    tailored_cv: str | None = None


class CVProject(BaseModel):
    title: str
    role: str
    period: str
    location: str = "Remote"
    bullets: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)


class CVEducation(BaseModel):
    institution: str
    degree: str
    period: str
    details: str = ""


class TailoredCV(BaseModel):
    name: str = "MATEO GABRIEL SONZOGNI"
    title: str
    location: str = "Río Negro, Patagonia Argentina (UTC-3)"
    email: str = "mateogabus@gmail.com"
    github: str = "https://github.com/MateoGs013"
    linkedin: str = "https://www.linkedin.com/in/mateo-sonzogni"
    portfolio: str = "https://mateogs.tech"
    summary: str
    skills: dict[str, list[str]] = Field(default_factory=dict)
    experience: list[CVProject] = Field(default_factory=list)
    education: list[CVEducation] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    methodologies: list[str] = Field(default_factory=list)
    language: str = "en"


class MatchResult(BaseModel):
    """Resultado del análisis de compatibilidad semántica con el LLM."""
    score: int  # 0 a 100
    verdict: str  # 'EXCELENTE_MATCH', 'BUEN_MATCH', 'REGULAR', 'DESCARTAR'
    summary: str
    pros: list[str] = Field(default_factory=list)
    cons: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    matching_projects: list[str] = Field(default_factory=list)


class PitchDraft(BaseModel):
    """Propuesta de presentación generada para la vacante."""
    subject_or_hook: str
    cover_letter: str
    elevator_pitch: str
    suggested_projects: list[str] = Field(default_factory=list)


class ProjectSummary(BaseModel):
    slug: str
    title: str
    summary: str
    techs: list[str] = Field(default_factory=list)
    outcome: str | None = None
    url: str | None = None


class ProfileContext(BaseModel):
    """Contexto dinámico de Mateo obtenido desde su portafolio."""
    name: str = "Mateo Gabriel Sonzogni"
    role: str = "Desarrollador Frontend & Full Stack · Creative Developer"
    location: str = "Río Negro, Patagonia Argentina"
    timezone: str = "UTC-3"
    languages: str = "Español (Nativo) · Inglés (B2 Profesional Técnico)"
    education: str = "Técnico Superior en Diseño y Programación Web (Escuela Da Vinci, 2024–2026) · Técnico en Programación (CET 30, 2017–2023)"
    core_competencies: str = ""
    engineering_philosophy: str = ""
    projects: list[ProjectSummary] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
