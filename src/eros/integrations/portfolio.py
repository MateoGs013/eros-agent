import logging
import httpx
from eros.config import get_settings
from eros.models import ProfileContext, ProjectSummary

logger = logging.getLogger(__name__)


class PortfolioClient:
    """Cliente HTTP asíncrono para consumir la API oficial del portafolio."""

    def __init__(self, base_url: str | None = None):
        settings = get_settings()
        self.base_url = (base_url or settings.portfolio_api_url).rstrip("/")

    async def fetch_profile(self) -> ProfileContext:
        """Obtiene y normaliza el perfil completo de Mateo desde la API viva."""
        profile = ProfileContext()
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 1. Documento About
            try:
                resp = await client.get(f"{self.base_url}/docs/about")
                if resp.status_code == 200:
                    payload = resp.json()
                    data = payload.get("data", {})
                    fields = {f["name"]: f.get("value", "") for f in data.get("fields", [])}

                    if "name" in fields:
                        profile.name = fields["name"]
                    if "role" in fields:
                        profile.role = fields["role"]
                    if "location" in fields:
                        profile.location = fields["location"]
                    if "timezone" in fields:
                        profile.timezone = fields["timezone"]
                    if "languages" in fields:
                        profile.languages = fields["languages"]
                    if "core_competencies" in fields:
                        profile.core_competencies = fields["core_competencies"]
                    if "engineering_philosophy" in fields:
                        profile.engineering_philosophy = fields["engineering_philosophy"]
            except Exception as e:
                logger.warning(f"No se pudo consultar /docs/about: {e}. Usando datos base.")

            # 2. Proyectos Reales
            try:
                resp = await client.get(f"{self.base_url}/projects")
                if resp.status_code == 200:
                    payload = resp.json()
                    projects_raw = payload.get("data", [])
                    projects = []
                    for p in projects_raw:
                        # Extraer techs
                        techs = []
                        if isinstance(p.get("techs"), list):
                            for t in p["techs"]:
                                if isinstance(t, dict):
                                    techs.append(t.get("slug") or t.get("name", ""))
                                elif isinstance(t, str):
                                    techs.append(t)

                        projects.append(ProjectSummary(
                            slug=p.get("slug", ""),
                            title=p.get("title", ""),
                            summary=p.get("summary", ""),
                            techs=techs,
                            outcome=p.get("outcome"),
                            url=p.get("url") or p.get("repo")
                        ))
                    profile.projects = projects
            except Exception as e:
                logger.warning(f"No se pudo consultar /projects: {e}.")

            # 3. Stack Tecnológico
            try:
                resp = await client.get(f"{self.base_url}/stack")
                if resp.status_code == 200:
                    payload = resp.json()
                    stack_raw = payload.get("data", [])
                    techs = [s.get("name") or s.get("slug", "") for s in stack_raw if s]
                    profile.tech_stack = list(set(techs))
            except Exception as e:
                logger.warning(f"No se pudo consultar /stack: {e}.")

        # Si el stack vino vacío de la API, asegurar las tecnologías nucleares conocidas
        if not profile.tech_stack:
            profile.tech_stack = [
                "Vue 3", "Nuxt 4", "TypeScript", "Node.js", "Express",
                "PostgreSQL", "Tailwind CSS", "GSAP", "Docker", "Python"
            ]

        return profile
