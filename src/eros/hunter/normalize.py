"""Normalización de nombres de empresa y títulos para deduplicar vacantes entre fuentes."""

import re
import unicodedata

# Nombres de empresa que no identifican a nadie: de ellos no se infiere ningún dominio
# ni se deduplica entre fuentes (dos "Empresa Confidencial" no son la misma empresa).
PLACEHOLDER_COMPANY_NAMES = {
    "empresaconfidencial",
    "confidencial",
    "confidential",
    "confidentialcompany",
    "companyconfidential",
    "empresa",
    "company",
    "empresaanonima",
    "anonymous",
    "anonymouscompany",
    "anonima",
    "stealth",
    "stealthstartup",
    "stealthmode",
    "undisclosed",
    "private",
    "privatecompany",
    "hidden",
    "importanteempresa",
    "reconocidaempresa",
    "importanteempresadelsector",
    "na",
    "nd",
    "unknown",
    "desconocida",
    "empresaremota",
    "remotecompany",
}

_PLACEHOLDER_WORDS = ("confidencial", "confidential", "stealth", "undisclosed")

_LEGAL_SUFFIXES = re.compile(
    r"\b(s\.?a\.?s?|s\.?r\.?l\.?|inc|llc|corp|corporation|ltd|limited|gmbh|co)\b\.?",
    flags=re.IGNORECASE,
)

# Ruido habitual en títulos que cambia según el portal pero no el puesto
_TITLE_NOISE = re.compile(
    r"\((?:remote|remoto|hybrid|h[ií]brido|full[- ]?time|part[- ]?time|contract|contractor)[^)]*\)"
    r"|\b(remote|remoto|100%|full[- ]?time)\b",
    flags=re.IGNORECASE,
)


def _ascii_lower(text: str) -> str:
    return (
        unicodedata.normalize("NFKD", text or "")
        .encode("ASCII", "ignore")
        .decode("utf-8")
        .lower()
    )


def is_placeholder_company(company: str | None) -> bool:
    """True si el nombre de la empresa es un genérico ("Empresa Confidencial", "Stealth", etc.)."""
    if not company or not company.strip():
        return True
    normalized = _ascii_lower(company)
    compact = re.sub(r"[^a-z0-9]", "", normalized)
    if not compact or compact in PLACEHOLDER_COMPANY_NAMES:
        return True
    return any(w in normalized for w in _PLACEHOLDER_WORDS)


def normalize_company(company: str | None) -> str:
    cleaned = _LEGAL_SUFFIXES.sub(" ", _ascii_lower(company or ""))
    return re.sub(r"[^a-z0-9]", "", cleaned)


def normalize_title(title: str | None) -> str:
    cleaned = _TITLE_NOISE.sub(" ", _ascii_lower(title or ""))
    cleaned = cleaned.replace("sr.", "senior").replace("ssr", "semi senior").replace("jr.", "junior")
    return re.sub(r"[^a-z0-9]", "", cleaned)


def job_dedup_key(company: str | None, title: str | None, source: str | None = None) -> str | None:
    """Clave para detectar la misma vacante publicada en varias fuentes.

    Empresa + título normalizados. Si la empresa es un genérico ("Empresa Confidencial",
    "Empresa Remota") devuelve None: esos avisos solo se deduplican por id, porque
    no hay forma de saber si dos de ellos son la misma empresa.
    """
    if is_placeholder_company(company):
        return None
    company_key = normalize_company(company)
    title_key = normalize_title(title)
    if not company_key or not title_key:
        return None
    return f"{company_key}|{title_key}"
