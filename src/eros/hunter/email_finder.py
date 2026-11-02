"""Módulo de resolución automática de correos de selección laboral."""

import logging
import re
import unicodedata
import urllib.parse
from typing import Any

import httpx

from eros.config import Settings, get_settings
from eros.hunter.filters import extract_contact_email
from eros.hunter.normalize import is_placeholder_company

logger = logging.getLogger(__name__)

# Portales de empleo, ATS y agregadores cuyo dominio NO pertenece a la empresa empleadora
GENERIC_PORTAL_DOMAINS = {
    "linkedin.com",
    "getonboard.com",
    "computrabajo.com",
    "computrabajo.com.ar",
    "computrabajo.com.mx",
    "computrabajo.com.co",
    "computrabajo.cl",
    "computrabajo.pe",
    "remoteok.com",
    "remoteok.io",
    "weworkremotely.com",
    "remotive.com",
    "remotive.io",
    "ycombinator.com",
    "news.ycombinator.com",
    "glassdoor.com",
    "indeed.com",
    "join.com",
    "lever.co",
    "greenhouse.io",
    "workable.com",
    "breezy.hr",
    "smartrecruiters.com",
    "ashbyhq.com",
    "talent.com",
    "ziprecruiter.com",
    "monster.com",
    "wellfound.com",
    "angellist.com",
    "bamboohr.com",
    "workday.com",
    "jobvite.com",
}

# Mapeo curado de empresas reconocidas a sus dominios corporativos principales
KNOWN_COMPANY_DOMAINS: dict[str, str] = {
    "mercadolibre": "mercadolibre.com",
    "uala": "uala.com.ar",
    "globant": "globant.com",
    "auth0": "auth0.com",
    "despegar": "despegar.com",
    "rappi": "rappi.com",
    "pedidosya": "pedidosya.com",
    "nubank": "nubank.com.br",
    "dlocal": "dlocal.com",
    "lemoncash": "lemon.me",
    "lemon": "lemon.me",
    "tiendanube": "tiendanube.com",
    "prismamp": "prismamp.com",
    "prisma": "prismamp.com",
    "coderhouse": "coderhouse.com",
    "platzi": "platzi.com",
    "belo": "belo.app",
    "ripio": "ripio.com",
    "muun": "muun.com",
}

EMPLOYMENT_PREFIXES = (
    "jobs",
    "careers",
    "talent",
    "hiring",
    "rrhh",
    "people",
    "recruiting",
    "selection",
)

HR_DEPARTMENTS = (
    "hr",
    "recruiting",
    "human_resources",
    "talent",
    "people",
)

# Fuentes válidas de un correo de contacto (columna jobs.contact_email_source).
# Nunca hay una fuente "adivinada": un correo que no salió de un lugar real no se guarda.
EMAIL_SOURCE_POSTING = "posting"          # Publicado en el aviso
EMAIL_SOURCE_COMPANY_SITE = "company_site"  # Publicado en el sitio de la empresa
EMAIL_SOURCE_HUNTER = "hunter"            # Encontrado por Hunter.io (con su puntaje de confianza)
EMAIL_SOURCE_MANUAL = "manual"            # Escrito a mano por Mateo
EMAIL_SOURCE_UNKNOWN = "unknown"          # Correo heredado de antes de registrar la fuente
EMAIL_SOURCES = (
    EMAIL_SOURCE_POSTING,
    EMAIL_SOURCE_COMPANY_SITE,
    EMAIL_SOURCE_HUNTER,
    EMAIL_SOURCE_MANUAL,
    EMAIL_SOURCE_UNKNOWN,
)
# Fuentes donde la dirección fue publicada o escrita por una persona (no inferida).
VERIFIED_EMAIL_SOURCES = (EMAIL_SOURCE_POSTING, EMAIL_SOURCE_COMPANY_SITE, EMAIL_SOURCE_MANUAL)



class EmailFinder:
    """Servicio de resolución automática en cascada de correos corporativos para selección."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def extract_domain_from_url(self, job_url: str) -> str | None:
        """Extrae el dominio corporativo de una URL si no corresponde a un portal genérico."""
        if not job_url:
            return None

        cleaned_url = job_url.strip()
        if not cleaned_url:
            return None

        try:
            parsed = urllib.parse.urlparse(cleaned_url)
            netloc = parsed.netloc.lower()
            if not netloc:
                parsed = urllib.parse.urlparse(f"https://{cleaned_url}")
                netloc = parsed.netloc.lower()

            if ":" in netloc:
                netloc = netloc.split(":")[0]

            if netloc.startswith("www."):
                netloc = netloc[4:]

            if not netloc or "." not in netloc:
                return None

            # Descartar portales genéricos conocidos y sus subdominios
            for portal in GENERIC_PORTAL_DOMAINS:
                if netloc == portal or netloc.endswith("." + portal):
                    return None

            # Manejar subdominios (ej. careers.spotify.com -> spotify.com o jobs.uala.com.ar -> uala.com.ar)
            parts = netloc.split(".")
            if len(parts) > 2:
                # ccTLDs de dos niveles (ej. .com.ar, .co.uk, .com.mx)
                if len(parts) >= 4 and parts[-2] in {"com", "co", "org", "net", "gob", "edu"}:
                    return ".".join(parts[-3:])
                elif parts[-2] not in {"com", "co", "org", "net", "gob", "edu"} and len(parts) >= 3:
                    return ".".join(parts[-2:])

            return netloc
        except Exception:
            return None

    @staticmethod
    def is_placeholder_company(company: str | None) -> bool:
        """True si el nombre de la empresa es un genérico ("Empresa Confidencial", "Stealth", etc.)."""
        return is_placeholder_company(company)

    def infer_domain_from_company(self, company: str, allow_placeholder: bool = False) -> str | None:
        """Infiere el dominio corporativo probable a partir del nombre de la empresa.

        Solo se usa como dominio de consulta para Hunter.io, nunca para armar un correo.
        Devuelve None si la empresa es un genérico ("Empresa Confidencial"), salvo
        allow_placeholder=True (solo para reconocer correos adivinados heredados).
        """
        if not company or not company.strip():
            return None

        # Quitar diacríticos/acentos
        normalized = (
            unicodedata.normalize("NFKD", company)
            .encode("ASCII", "ignore")
            .decode("utf-8")
            .lower()
            .strip()
        )

        # Quitar sufijos legales y formas societarias comunes
        cleaned = re.sub(
            r"\b(s\.?a\.?|s\.?r\.?l\.?|inc\.?|llc\.?|corp\.?|corporation|ltd\.?|limited|technologies|technology|group|holdings|gmbh|co\.?)\b",
            "",
            normalized,
            flags=re.IGNORECASE,
        )

        # Quitar signos de puntuación y espacios
        compact = re.sub(r"[^a-z0-9]", "", cleaned)
        if not compact or (not allow_placeholder and self.is_placeholder_company(company)):
            return None

        if compact in KNOWN_COMPANY_DOMAINS:
            return KNOWN_COMPANY_DOMAINS[compact]

        return f"{compact}.com"

    async def fetch_company_site_email(self, job_url: str, domain: str) -> str | None:
        """Busca un correo publicado en la página del aviso cuando vive en el sitio de la empresa.

        Solo acepta direcciones del mismo dominio que la página: un correo de terceros
        que aparezca en el sitio no es el contacto de selección de la empresa.
        """
        if not job_url or not domain:
            return None
        try:
            async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
                resp = await client.get(job_url, headers={"User-Agent": "Mozilla/5.0 (ErosAgent)"})
            if resp.status_code != 200:
                return None
            email = extract_contact_email(resp.text[:200_000])
        except Exception as e:
            logger.info(f"No se pudo leer el sitio de la empresa '{job_url}': {e}")
            return None
        if not email:
            return None
        email_domain = email.rsplit("@", 1)[-1].lower()
        if email_domain == domain or email_domain.endswith("." + domain):
            return email
        return None

    async def query_hunter_io(
        self, domain: str, recruiter_name: str | None = None
    ) -> str | None:
        """Consulta la API de Hunter.io en busca del correo del reclutador o de selección."""
        api_key = (self.settings.hunter_io_api_key or "").strip()
        if not api_key:
            return None

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                # 1. Prioridad Máxima: Si hay reclutador/hiring lead, buscar su correo personal
                if recruiter_name and recruiter_name.strip():
                    url = "https://api.hunter.io/v2/email-finder"
                    params: dict[str, Any] = {
                        "domain": domain,
                        "full_name": recruiter_name.strip(),
                        "api_key": api_key,
                    }
                    parts = recruiter_name.strip().split()
                    if len(parts) >= 2:
                        params["first_name"] = parts[0]
                        params["last_name"] = parts[-1]

                    resp = await client.get(url, params=params)
                    if resp.status_code == 200:
                        data = resp.json().get("data", {})
                        email = data.get("email")
                        score = data.get("score") or data.get("confidence") or 0
                        position = (data.get("position") or "").lower()
                        if email:
                            is_hr = any(h in position for h in HR_DEPARTMENTS)
                            if score >= 50 or is_hr:
                                return email

                # 2. Prioridad Alta: Buscar personas reales del departamento de Talento / HR en /domain-search (type=personal)
                url = "https://api.hunter.io/v2/domain-search"
                params = {
                    "domain": domain,
                    "api_key": api_key,
                    "department": "human_resources",
                    "type": "personal",
                    "limit": 5,
                }
                resp = await client.get(url, params=params)
                if resp.status_code == 200:
                    data = resp.json().get("data", {})
                    emails = data.get("emails", [])
                    # Buscar la persona de HR con mayor score
                    for item in emails:
                        val = (item.get("value") or item.get("email") or "").strip().lower()
                        if not val or "@" not in val:
                            continue
                        score = item.get("confidence") or item.get("score") or 0
                        if score >= 60:
                            logger.info(f"Hunter.io encontró recruiter personal para '{domain}': {val} (score: {score}%)")
                            return val

                # 3. Prioridad Media: Si no hay nadie específico de HR en Hunter.io, buscar cualquier correo de empleo con prefijo oficial
                params_generic = {
                    "domain": domain,
                    "api_key": api_key,
                    "type": "generic",
                }
                resp_gen = await client.get(url, params=params_generic)
                if resp_gen.status_code == 200:
                    data = resp_gen.json().get("data", {})
                    emails = data.get("emails", [])
                    for item in emails:
                        val = (item.get("value") or item.get("email") or "").strip().lower()
                        if not val or "@" not in val:
                            continue
                        prefix = val.split("@")[0]
                        if prefix in EMPLOYMENT_PREFIXES:
                            return val
        except Exception as e:
            logger.warning(f"Error al consultar Hunter.io para dominio '{domain}': {e}")
            return None

        return None

    async def resolve_contact_email(
        self,
        company: str,
        job_url: str = "",
        recruiter_name: str | None = None,
        description: str = "",
    ) -> tuple[str | None, str | None]:
        """Resuelve en cascada el correo de selección para una vacante laboral.

        Solo devuelve direcciones que aparecen publicadas en algún lado o que
        Hunter.io encontró; nunca arma una dirección a partir del dominio.

        Retorna:
            (email, source) donde source es "posting", "company_site", "hunter" o None.
        """
        # 1. Publicado en el aviso
        if description:
            direct_email = extract_contact_email(description)
            if direct_email:
                return direct_email, EMAIL_SOURCE_POSTING

        # 2. Publicado en el sitio de la empresa (solo si el aviso vive en su dominio)
        site_domain = self.extract_domain_from_url(job_url)
        if site_domain:
            site_email = await self.fetch_company_site_email(job_url, site_domain)
            if site_email:
                return site_email, EMAIL_SOURCE_COMPANY_SITE

        # 3. Hunter.io (si está configurado): dominio del sitio o inferido del nombre real
        if self.settings.hunter_io_api_key:
            domain = site_domain or self.infer_domain_from_company(company)
            if domain:
                hunter_email = await self.query_hunter_io(domain, recruiter_name=recruiter_name)
                if hunter_email:
                    return hunter_email, EMAIL_SOURCE_HUNTER

        return None, None
