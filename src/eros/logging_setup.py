"""Configuración de logging compartida por la API (uvicorn) y la CLI.

- Uvicorn no configura los loggers de la app: sin esto, los `logger.info` de Eros no
  aparecen en los logs de producción.
- httpx loguea cada URL pedida; las de Telegram llevan el token del bot en la ruta.
  Se baja httpx a WARNING y además se tapa cualquier token que aparezca en un mensaje.
"""

import logging
import re

from eros.config import get_settings

_TELEGRAM_TOKEN_RE = re.compile(r"bot\d{5,}:[A-Za-z0-9_-]{20,}")
_CONFIGURED = False


class RedactSecretsFilter(logging.Filter):
    """Reemplaza tokens de Telegram y claves configuradas por [REDACTED] en los mensajes."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        redacted = _TELEGRAM_TOKEN_RE.sub("bot[REDACTED]", message)
        settings = get_settings()
        for secret in (
            settings.telegram_bot_token,
            settings.eros_api_key,
            settings.gemini_api_key,
            settings.n8n_webhook_secret,
            settings.smtp_pass,
            settings.hunter_io_api_key,
        ):
            if secret and len(secret) >= 8 and secret in redacted:
                redacted = redacted.replace(secret, "[REDACTED]")
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


def configure_logging() -> None:
    """Configura el logging raíz una sola vez (idempotente)."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    level = getattr(logging, (get_settings().log_level or "INFO").upper(), logging.INFO)
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        root.addHandler(handler)
    root.setLevel(level)

    redact = RedactSecretsFilter()
    for handler in root.handlers:
        handler.addFilter(redact)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(name).handlers:
            handler.addFilter(redact)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
