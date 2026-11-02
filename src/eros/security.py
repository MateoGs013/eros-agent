"""Firmas para los enlaces públicos que Eros incluye en correos (CV por vacante)."""

import hashlib
import hmac
import secrets

from eros.config import get_settings


def _cv_secret() -> bytes | None:
    settings = get_settings()
    raw = (settings.cv_link_secret or "").strip() or (settings.eros_api_key or "").strip()
    if not raw:
        return None
    return hashlib.sha256(f"eros-cv-link:{raw}".encode()).digest()


def sign_cv_token(job_id: str) -> str | None:
    """Token del enlace público al CV de una vacante. None si no hay secreto configurado."""
    secret = _cv_secret()
    if secret is None:
        return None
    return hmac.new(secret, job_id.encode(), hashlib.sha256).hexdigest()[:32]


def verify_cv_token(job_id: str, token: str | None) -> bool:
    expected = sign_cv_token(job_id)
    if not expected or not token:
        return False
    return secrets.compare_digest(expected, token.strip())


def cv_public_url(job_id: str, fmt: str = "html") -> str | None:
    """Enlace público y firmado al CV guardado de la vacante (html o pdf)."""
    token = sign_cv_token(job_id)
    if token is None:
        return None
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/api/jobs/{job_id}/cv/{fmt}?token={token}"
