import math
import logging
from eros.models import JobOffer, ProfileContext

logger = logging.getLogger(__name__)


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Calcula la similitud del coseno entre dos vectores numéricos."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0

    dot = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / (norm_a * norm_b)


def normalize_semantic_score(cos_sim: float) -> int:
    """
    Normaliza la similitud del coseno (que en gemini-embedding-001 suele situarse entre 0.70 y 0.92)
    a un puntaje intuitivo de 0 a 100%.
    - >= 0.89: 90% - 100% (Match sobresaliente: Full Stack / Vue / TS / Node)
    - 0.82 - 0.88: 70% - 88% (Match alto: Web dev, React, Backend relacionado)
    - 0.75 - 0.81: 45% - 69% (Match medio: Stack adyacente o híbrido)
    - < 0.75: < 40% (Match bajo / incompatible: Security, DevOps puro, Outsystems, no tech)
    """
    if cos_sim <= 0.0:
        return 0

    base_min = 0.70
    base_max = 0.92

    if cos_sim < base_min:
        # Debajo del piso tecnológico general
        ratio = max(0.0, cos_sim / base_min)
        return int(ratio * 30)

    ratio = (cos_sim - base_min) / (base_max - base_min)
    score = int(30 + ratio * 70)
    return max(0, min(100, score))


def build_profile_vector_text(profile: ProfileContext) -> str:
    """Construye un texto semántico representativo del perfil de Mateo para vectorización."""
    lines = [
        f"Profesional: {profile.name} — {profile.role} (Seniority: Mid-Level / Semi-Senior, 3+ años)",
        f"Ubicación y Modalidad: {profile.location} (UTC-3). Modalidad Remota Internacional Contractor B2B o Híbrida/Presencial en Neuquén/Río Negro.",
        f"Stack Tecnológico Principal: {', '.join(profile.tech_stack)}.",
        "Competencias Clave: Desarrollo Full Stack, arquitectura de APIs REST, interfaces reactivas y creativas, bases de datos relacionales, optimización web.",
    ]

    if profile.projects:
        project_summaries = []
        for p in profile.projects[:6]:
            techs = getattr(p, "techs", getattr(p, "tech_stack", []))
            tech_str = ", ".join(techs) if techs else ""
            summary_str = getattr(p, "summary", "")
            project_summaries.append(f"{p.title}: {summary_str} ({tech_str})")
        lines.append(f"Proyectos Shipped en Producción: {'; '.join(project_summaries)}.")

    return "\n".join(lines)


def build_job_vector_text(job: JobOffer) -> str:
    """Construye un texto semántico representativo de la vacante para vectorización."""
    tags_str = ", ".join(job.tags) if job.tags else "General"
    country_str = job.country or "Global"
    remote_str = "Remoto" if job.is_remote else "Presencial/Híbrido"

    desc_clean = " ".join((job.description or "").split())[:1500]

    return (
        f"Vacante: {job.title} en {job.company}.\n"
        f"Modalidad: {remote_str} ({country_str}). Tags: {tags_str}.\n"
        f"Requisitos y Alcance: {desc_clean}"
    )
