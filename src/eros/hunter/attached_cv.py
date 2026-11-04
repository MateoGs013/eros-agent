"""El CV que adjunta una postulación: siempre el que arma el portafolio desde su base.

Eros no adjunta un CV propio. El admin del portafolio compone el CV Harvard ATS de la vacante,
lo imprime a PDF (una página A4 dentro de la cota de 248–265 mm) y lo manda en el pedido de
`apply-email` como `cv`. Acá se valida tal cual llegó; si falta o no es válido, no se envía nada.
"""

import base64
import binascii
import hashlib
import re
from dataclasses import dataclass
from typing import Any

MAX_PDF_BYTES = 2 * 1024 * 1024
MAX_TEXT_CHARS = 20_000
_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,150}\.pdf$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class AttachedCVError(ValueError):
    """El pedido no trae un CV usable. `code` es el `error_code` de la respuesta."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class AttachedCV:
    filename: str
    pdf_bytes: bytes
    text: str
    sha256: str
    lang: str | None = None
    height_mm: float | None = None

    @property
    def pdf_base64(self) -> str:
        return base64.b64encode(self.pdf_bytes).decode("ascii")


def _invalid(message: str) -> AttachedCVError:
    return AttachedCVError("invalid_cv", message)


def parse_attached_cv(raw: Any) -> AttachedCV:
    """Valida el `cv` del pedido. Lanza AttachedCVError con `cv_required` o `invalid_cv`."""
    if raw is None:
        raise AttachedCVError(
            "cv_required",
            "Falta el CV: Eros solo adjunta el CV que arma el portafolio desde su base. Postulá desde el admin.",
        )
    if not isinstance(raw, dict):
        raise _invalid("El CV tiene que ser un objeto con filename, pdf_base64, text y sha256.")

    filename = raw.get("filename")
    if not isinstance(filename, str) or not _FILENAME_RE.match(filename):
        raise _invalid("El nombre del PDF del CV no es válido (letras, números, punto, guion y .pdf).")

    encoded = raw.get("pdf_base64")
    if not isinstance(encoded, str) or not encoded:
        raise _invalid("Falta el PDF del CV (pdf_base64).")
    # Un tope antes de decodificar: base64 ocupa 4/3 de los bytes.
    if len(encoded) > (MAX_PDF_BYTES * 4) // 3 + 4:
        raise _invalid("El PDF del CV pesa más de 2 MB.")
    try:
        pdf_bytes = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise _invalid("El PDF del CV no es base64 válido.") from None
    if not pdf_bytes.startswith(b"%PDF-"):
        raise _invalid("El adjunto del CV no es un PDF.")
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise _invalid("El PDF del CV pesa más de 2 MB.")

    sha = raw.get("sha256")
    if not isinstance(sha, str) or not _SHA256_RE.match(sha.lower()):
        raise _invalid("Falta el sha256 del PDF del CV.")
    if hashlib.sha256(pdf_bytes).hexdigest() != sha.lower():
        raise _invalid("El sha256 no coincide con el PDF del CV: llegó distinto de como salió.")

    text = raw.get("text")
    if not isinstance(text, str) or not text.strip():
        raise _invalid("Falta el CV en texto plano.")
    if len(text) > MAX_TEXT_CHARS:
        raise _invalid("El CV en texto plano es demasiado largo.")

    lang = raw.get("lang")
    height = raw.get("height_mm")
    return AttachedCV(
        filename=filename,
        pdf_bytes=pdf_bytes,
        text=text,
        sha256=sha.lower(),
        lang=lang if lang in ("es", "en") else None,
        height_mm=float(height) if isinstance(height, (int, float)) and not isinstance(height, bool) else None,
    )
