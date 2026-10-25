"""Módulo de resolución automática de correos de selección laboral."""

import asyncio
import logging
import re
import socket
import unicodedata
import urllib.parse
from typing import Any

import httpx

from eros.config import Settings, get_settings
from eros.hunter.filters import extract_contact_email

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

    def infer_domain_from_company(self, company: str) -> str | None:
        """Infiere el dominio corporativo probable a partir del nombre de la empresa."""
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
        if not compact:
            return None

        if compact in KNOWN_COMPANY_DOMAINS:
            return KNOWN_COMPANY_DOMAINS[compact]

        return f"{compact}.com"

    def generate_candidate_emails(
        self, domain: str, recruiter_name: str | None = None
    ) -> list[str]:
        """Genera candidatos de correos para postulaciones, incluyendo reclutador y alias genéricos."""
        generic_candidates = [
            f"jobs@{domain}",
            f"careers@{domain}",
            f"talent@{domain}",
            f"hiring@{domain}",
            f"rrhh@{domain}",
        ]

        recruiter_candidates: list[str] = []
        if recruiter_name and recruiter_name.strip():
            norm = (
                unicodedata.normalize("NFKD", recruiter_name)
                .encode("ASCII", "ignore")
                .decode("utf-8")
                .lower()
                .strip()
            )
            parts = [p for p in re.split(r"[^a-z]", norm) if p]
            if parts:
                first = parts[0]
                last = parts[-1] if len(parts) > 1 else ""
                if last:
                    recruiter_candidates.extend([
                        f"{first}.{last}@{domain}",
                        f"{first[0]}{last}@{domain}",
                    ])
                else:
                    recruiter_candidates.append(f"{first}@{domain}")

        return recruiter_candidates + generic_candidates

    async def check_dns_resolution(self, domain: str) -> bool:
        """Verifica la existencia y resolución de DNS básica del dominio."""
        if not domain:
            return False
        try:
            await asyncio.wait_for(
                asyncio.to_thread(socket.gethostbyname, domain),
                timeout=2.0,
            )
            return True
        except Exception:
            return False

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

        Retorna:
            (email, source) donde source puede ser:
            - "description"
            - "hunter_io"
            - "domain_guessing"
            - "mx_inference"
            - None
        """
        # 1. Extracción directa de la descripción
        if description:
            direct_email = extract_contact_email(description)
            if direct_email:
                return direct_email, "description"

        # 2. Deducción de dominio
        domain = self.extract_domain_from_url(job_url)
        if not domain and company:
            domain = self.infer_domain_from_company(company)

        if not domain:
            return None, None

        # 3. Consulta a Hunter.io API (si api_key está configurado)
        if self.settings.hunter_io_api_key:
            hunter_email = await self.query_hunter_io(domain, recruiter_name=recruiter_name)
            if hunter_email:
                return hunter_email, "hunter_io"

        # 4. Inferencia de alias corporativos / Guessing inteligente
        resolves = await self.check_dns_resolution(domain)
        if resolves:
            # Selecciona el candidato de mayor probabilidad (jobs@{domain} o careers@{domain})
            selected_email = f"jobs@{domain}"
            return selected_email, "domain_guessing"

        return None, None
