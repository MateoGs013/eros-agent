"""El `cv` que manda el portafolio en `apply-email`, para las pruebas (no es un test: no empieza con test_).

Un PDF mínimo de una página, hecho a mano, distinto de cualquiera que arme Eros: si un envío
adjunta otro PDF, las pruebas lo notan comparando bytes y sha256.
"""

import base64
import hashlib

PORTFOLIO_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n"
    b"%%EOF CV del portafolio\n"
)
PORTFOLIO_FILENAME = "CV_Mateo_Sonzogni_Frontend_Engineer_Example_Labs.pdf"
PORTFOLIO_TEXT = "MATEO GABRIEL SONZOGNI\nFull Stack Developer\n\nPERFIL PROFESIONAL\nCV armado desde la base del portafolio."


def portfolio_cv(**overrides) -> dict:
    cv = {
        "filename": PORTFOLIO_FILENAME,
        "pdf_base64": base64.b64encode(PORTFOLIO_PDF).decode("ascii"),
        "text": PORTFOLIO_TEXT,
        "sha256": hashlib.sha256(PORTFOLIO_PDF).hexdigest(),
        "lang": "es",
        "height_mm": 256.4,
    }
    cv.update(overrides)
    return cv
