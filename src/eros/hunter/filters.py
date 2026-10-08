"""Filtros heurísticos y reglas de negocio para calificar ofertas laborales.
Descarta de raíz ofertas con incompatibilidad geográfica (W2/US Only),
seniority desmedido (Staff/Principal/+8 años) o stacks irrelevantes.
"""

import logging
import re
from typing import NamedTuple

logger = logging.getLogger(__name__)


class QualificationResult(NamedTuple):
    qualified: bool
    reason: str


# ─── EXCLUSIONES GEOGRÁFICAS / LEGALES ────────────────────────────────────────

GEO_EXCLUSIONS = [
    # Requisitos de ciudadanía o autorización sin sponsoreo en EE.UU.
    re.compile(r"\b(u\.?s\.?|usa|united states)\s+(only|citizens?\s+only|residents?\s+only|based\s+only)\b", re.I),
    re.compile(r"\bmust\s+reside\s+in\s+(the\s+)?(u\.?s\.?|united states|canada|uk|europe|eu)\b", re.I),
    re.compile(r"\b(candidates?\s+must\s+be\s+located\s+in|only\s+open\s+to\s+candidates\s+in)\s+(the\s+)?(u\.?s\.?|united states|canada|eu|uk)\b", re.I),
    re.compile(r"\b(green\s+card|w-?2\s+only|w2\s+contract\s+only)\b", re.I),
    re.compile(r"\b(security\s+clearance|polygraph|ts/sci|secret\s+clearance)\b", re.I),
    re.compile(r"\b(requires?\s+(us|u\.s\.)\s+citizenship)\b", re.I),
    re.compile(r"\b(authorized\s+to\s+work\s+in\s+the\s+(us|united states)\s+without\s+(visa\s+)?sponsorship)\b", re.I),
    re.compile(r"\bno\s+c2c\b|\bno\s+corp-?to-?corp\b", re.I),
    re.compile(r"\b(uk|eu|european\s+union)\s+(residents?|citizens?)\s+only\b", re.I),
    re.compile(r"\bpresencial\s+(en\s+)?(españa|madrid|barcelona|méxico|chile|colombia|ee\.?uu\.?)\b", re.I),
]

GEO_EXCEPTIONS = [
    re.compile(r"\b(latam|latin\s+america|argentina|worldwide|anywhere|global|international|w-8ben|contractor|remote\s+anywhere)\b", re.I),
]


# ─── EXCLUSIONES DE SENIORITY ────────────────────────────────────────────────

SENIORITY_EXCLUSIONS_TITLE = [
    re.compile(r"\b(staff|principal|director|vp\s+of|vice\s+president|head\s+of|chief|c-level|lead\s+architect)\b", re.I),
    re.compile(r"\b(enterprise\s+architect|cloud\s+architect\s+lead)\b", re.I),
]

SENIORITY_EXCLUSIONS_DESC = [
    re.compile(r"\b(8\+|9\+|10\+|12\+|15\+)\s*(years|yrs|años)\s+(of\s+experience|de\s+experiencia)\b", re.I),
    re.compile(r"\bminimum\s+(8|9|10|12|15)\s+years\b", re.I),
]


# ─── EXCLUSIONES DE STACK TECNOLÓGICO ────────────────────────────────────────

STACK_EXCLUSIONS_TITLE = [
    re.compile(r"\b(wordpress|drupal|magento|shopify\s+liquid|salesforce|sap|cobol|abap)\b", re.I),
    re.compile(r"\b(embedded|firmware|hardware\s+engineer|verilog|vhdl|fpga)\b", re.I),
    re.compile(r"\b(c\+\+\s+audio|game\s+engine\s+c\+\+|unreal\s+engine)\b", re.I),
    re.compile(r"\b(data\s+engineer|data\s+scientist|machine\s+learning\s+engineer|mlops)\b", re.I),
    re.compile(r"\b(ios\s+developer|android\s+developer|flutter\s+developer|swift\s+developer)\b", re.I),
]


# ─── PALABRAS CLAVE POSITIVAS DE RELEVANCIA ──────────────────────────────────

RELEVANT_TITLE_KEYWORDS = [
    "frontend", "front-end", "front end",
    "fullstack", "full stack", "full-stack",
    "vue", "nuxt", "react", "next",
    "typescript", "javascript", "web developer",
    "creative developer", "ui engineer", "software engineer",
    "desarrollador", "ingeniero de software",
]


def check_job_qualification(
    title: str,
    description: str = "",
    country: str | None = None,
    tags: list[str] | None = None,
) -> QualificationResult:
    """Evalúa de forma rápida y determinista si una vacante pasa el filtro inicial.
    
    Descarta puestos US-Only / W2, Staff / +8 años o stacks incompatibles.
    """
    title_clean = title.strip()
    title_lower = title_clean.lower()
    desc_clean = description.strip()
    country_clean = (country or "").lower()
    all_tags = [t.lower() for t in (tags or [])]
    tag_str = " ".join(all_tags)

    # 1. Filtro de Relevancia de Rol
    has_role_match = any(kw in title_lower for kw in RELEVANT_TITLE_KEYWORDS)
    if not has_role_match and not any(kw in tag_str for kw in ["frontend", "fullstack", "vue", "react", "typescript"]):
        return QualificationResult(False, "Rol fuera de foco (no es Frontend/Fullstack/Web)")

    # 2. Exclusiones de Stack en Título
    for pat in STACK_EXCLUSIONS_TITLE:
        if pat.search(title_lower):
            return QualificationResult(False, f"Stack no deseado en título: {pat.pattern}")

    # 3. Exclusiones de Seniority en Título
    for pat in SENIORITY_EXCLUSIONS_TITLE:
        if pat.search(title_lower):
            return QualificationResult(False, f"Seniority excesivo en título (Staff/Principal/Director): {pat.pattern}")

    # 4. Exclusiones de Seniority en Descripción (+8 a +15 años)
    if desc_clean:
        for pat in SENIORITY_EXCLUSIONS_DESC:
            if pat.search(desc_clean):
                return QualificationResult(False, "Exige +8 años de experiencia (Seniority incompatible)")

    # 5. Exclusiones Geográficas / Legales
    # Si la ubicación explícita dice 'US Only' o ciudades de EE.UU. sin especificar remoto abierto
    combined_geo_text = f"{country_clean} {desc_clean[:1500]}"
    
    # Revisar excepciones que habilitan LATAM o Worldwide
    has_override = any(pat.search(combined_geo_text) for pat in GEO_EXCEPTIONS)
    
    if not has_override:
        for pat in GEO_EXCLUSIONS:
            if pat.search(combined_geo_text):
                return QualificationResult(False, "Incompatibilidad geográfica/legal (Exclusivo EE.UU./Europa, Clearance o W-2)")

    return QualificationResult(True, "Calificada")
