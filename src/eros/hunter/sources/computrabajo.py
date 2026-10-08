"""Conector para Computrabajo Argentina enfocado en Neuquén y Alto Valle."""

import asyncio
import logging
import httpx
from bs4 import BeautifulSoup
from eros.hunter.filters import check_job_qualification
from eros.hunter.sources.base import BaseJobSource
from eros.models import JobOffer

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class ComputrabajoSource(BaseJobSource):
    """Conector para Computrabajo Argentina (puestos presenciales e híbridos en Neuquén)."""

    @property
    def name(self) -> str:
        return "computrabajo"

    async def fetch_jobs(self) -> list[JobOffer]:
        queries = [
            "https://ar.computrabajo.com/trabajo-de-informatica-telecomunicaciones-en-neuquen",
            "https://ar.computrabajo.com/trabajo-de-programador-en-neuquen",
            "https://ar.computrabajo.com/trabajo-de-desarrollador-en-neuquen",
        ]
        offers: list[JobOffer] = []
        seen_ids: set[str] = set()
        seen_keys: set[str] = set()

        headers = {
            "User-Agent": USER_AGENT,
            "Accept-Language": "es-ES,es;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        async with httpx.AsyncClient(timeout=15.0, headers=headers, follow_redirects=True) as client:
            for query_url in queries:
                try:
                    resp = await client.get(query_url)
                    if resp.status_code != 200:
                        logger.warning(f"Computrabajo respondió con status {resp.status_code} para {query_url}")
                        continue

                    soup = BeautifulSoup(resp.text, "html.parser")
                    articles = soup.find_all("article", class_="box_offer")

                    for art in articles:
                        job_id_ext = (art.get("data-id") or "").strip()
                        if not job_id_ext or job_id_ext in seen_ids:
                            continue

                        # Título y Enlace
                        title_el = art.find("a", class_="js-o-link") or art.find("h2")
                        title = title_el.get_text(strip=True) if title_el else ""
                        if not title:
                            continue

                        # Limpiar sufijos típicos de Computrabajo ("Postulado", "Vista", etc.)
                        title = title.replace("Postulado", "").replace("Vista", "").strip()

                        # Descartar roles claramente fuera de foco (comercial, ventas, de negocios, etc.)
                        title_lower = title.lower()
                        if any(bad in title_lower for bad in [
                            "de negocios", "negocios", "comercial", "ventas", "repositor", "administrativo",
                            "arenador", "chofer", "médico", "enfermero", "vendedor", "cajero", "seguridad"
                        ]):
                            continue

                        # Título debe pertenecer a tecnología
                        if not any(good in title_lower for good in [
                            "developer", "desarrollador", "programador", "software", "sistemas",
                            "full stack", "fullstack", "frontend", "backend", "it", "devops", "data"
                        ]):
                            continue

                        seen_ids.add(job_id_ext)

                        raw_href = title_el.get("href") if title_el else ""
                        clean_href = raw_href.split("#")[0] if raw_href else ""
                        full_url = f"https://ar.computrabajo.com{clean_href}" if clean_href.startswith("/") else clean_href

                        # Empresa
                        company_el = art.find("p", class_="fs16")
                        company = company_el.get_text(strip=True) if company_el else "Empresa Confidencial (Neuquén)"

                        # Deduplicar avisos repetidos por consultoras
                        job_key = f"{title.lower()}:{company.lower()}"
                        if job_key in seen_keys:
                            continue
                        seen_keys.add(job_key)

                        # Ubicación
                        location = "Neuquén, Argentina"
                        p_tags = art.find_all("p", class_="fs16")
                        if len(p_tags) > 1:
                            location = p_tags[1].get_text(strip=True) or location

                        loc_lower = location.lower()
                        is_neuquen_local = any(c in loc_lower for c in ["neuquén", "neuquen", "cipolletti", "río negro", "rio negro", "plottier", "general roca"])

                        # Breve descripción / snippet del aviso
                        desc_el = art.find("p", class_="w100") or art.find("p", class_="fs14")
                        snippet = desc_el.get_text(strip=True) if desc_el else f"Puesto en Neuquén: {title} en {company}."

                        # Detectar si es remoto o presencial
                        desc_lower = snippet.lower()
                        is_remote = "remoto" in desc_lower or "home office" in desc_lower or "híbrido" in desc_lower or "100% remoto" in title_lower

                        # Si la oferta es presencial y NO es en Neuquén/Río Negro (ej. Computrabajo recomienda CABA), descartar
                        if not is_remote and not is_neuquen_local:
                            continue

                        # Pre-filtro de calificación
                        qual = check_job_qualification(
                            title=title,
                            description=snippet,
                            country=location,
                            tags=["Neuquén", "Computrabajo", "Presencial" if not is_remote else "Remoto/Híbrido"],
                        )
                        if not qual.qualified:
                            logger.debug(f"Computrabajo: '{title}' descartada: {qual.reason}")
                            continue

                        # Intentar obtener la descripción completa si es relevante
                        full_desc = snippet
                        try:
                            await asyncio.sleep(0.3)
                            d_resp = await client.get(full_url)
                            if d_resp.status_code == 200:
                                d_soup = BeautifulSoup(d_resp.text, "html.parser")
                                d_box = d_soup.find("div", class_="box_detail") or d_soup.find("p", class_="mbB")
                                if d_box:
                                    clean_d = d_box.get_text(separator="\n", strip=True)
                                    if len(clean_d) > 80:
                                        full_desc = clean_d
                        except Exception as e:
                            logger.debug(f"No se pudo cargar detalle extendido de Computrabajo {job_id_ext}: {e}")

                        job_offer = JobOffer(
                            id=self.generate_job_id(job_id_ext),
                            source=self.name,
                            external_id=job_id_ext,
                            title=title,
                            company=company,
                            url=full_url,
                            description=full_desc[:3000],
                            tags=["Neuquén", "Presencial/Híbrido", "Computrabajo"],
                            salary=None,
                            country=location,
                            is_remote=is_remote,
                            published_at=None,
                        )
                        offers.append(job_offer)

                        if len(offers) >= 15:
                            break

                except Exception as e:
                    logger.error(f"Error extrayendo ofertas de Computrabajo ({query_url}): {e}")

        logger.info(f"Computrabajo: {len(offers)} vacantes de tecnología en Neuquén encontradas.")
        return offers
