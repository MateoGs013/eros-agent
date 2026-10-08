import asyncio
import json
import logging
from eros.config import get_settings
from eros.db.storage import JobStorage
from eros.hunter.cv_generator import CVGenerator
from eros.hunter.filters import check_job_qualification
from eros.hunter.matcher import JobMatcher
from eros.hunter.pitch import PitchGenerator
from eros.hunter.sources.base import BaseJobSource
from eros.hunter.sources.getonboard import GetOnBoardSource
from eros.hunter.sources.hackernews import HackerNewsHiringSource
from eros.hunter.sources.linkedin import LinkedInJobsSource
from eros.hunter.sources.remoteok import RemoteOKSource
from eros.hunter.sources.remotive import RemotiveSource
from eros.hunter.sources.weworkremotely import WeWorkRemotelySource
from eros.integrations.portfolio import PortfolioClient
from eros.models import (
    JobOffer,
    JobStatus,
    MatchResult,
    PitchDraft,
    ProfileContext,
    TailoredCV,
)

logger = logging.getLogger(__name__)


class HunterEngine:
    """Orquestador central del ciclo de búsqueda, deduplicación y scoring de vacantes."""

    def __init__(self, storage: JobStorage | None = None):
        self.settings = get_settings()
        self.storage = storage or JobStorage()
        self.portfolio_client = PortfolioClient()
        self.matcher = JobMatcher()
        self.pitch_gen = PitchGenerator()
        self.cv_gen = CVGenerator()
        self.sources: list[BaseJobSource] = [
            RemotiveSource(),
            WeWorkRemotelySource(),
            LinkedInJobsSource(),
            GetOnBoardSource(),
            RemoteOKSource(),
            HackerNewsHiringSource(),
        ]

    async def initialize(self) -> None:
        """Inicializa la base de datos y sincroniza el perfil inicial si no existe."""
        await self.storage.init_db()
        await self.clean_existing_unqualified_jobs()
        cached = await self.storage.get_profile_cache()
        if not cached:
            await self.sync_profile()

    async def clean_existing_unqualified_jobs(self) -> int:
        """Purga o marca como descartadas vacantes previas incompatibles (US-only, etc.)."""
        purged = 0
        try:
            all_jobs = await self.storage.list_matched_jobs(min_score=0, limit=500)
            for j in all_jobs:
                qual = check_job_qualification(
                    title=j.title,
                    description=j.description,
                    country=j.country,
                    tags=j.tags,
                )
                if not qual.qualified or (j.match_score is not None and j.match_score <= 35):
                    await self.storage.update_job_status(j.id, JobStatus.DISCARDED)
                    purged += 1
            if purged > 0:
                logger.info(f"Limpieza de base: se marcaron {purged} vacantes obsoletas/incompatibles como DESCARTADAS.")
        except Exception as e:
            logger.warning(f"Error durante limpieza de vacantes obsoletas: {e}")
        return purged

    async def sync_profile(self) -> ProfileContext:
        """Actualiza y guarda en caché el perfil más reciente de Mateo desde la API."""
        logger.info("Sincronizando perfil desde la API del portafolio...")
        profile = await self.portfolio_client.fetch_profile()
        await self.storage.save_profile_cache(profile)
        logger.info(f"Perfil sincronizado: {profile.name} con {len(profile.projects)} proyectos y {len(profile.tech_stack)} tecnologías.")
        return profile

    async def get_active_profile(self) -> ProfileContext:
        """Devuelve el perfil activo (de caché o API viva)."""
        cached = await self.storage.get_profile_cache()
        if cached:
            return cached
        return await self.sync_profile()

    async def run_scan(self) -> dict[str, int]:
        """Ejecuta una búsqueda en todas las fuentes curadas y guarda únicamente las ofertas calificadas."""
        await self.initialize()
        total_found = 0
        new_jobs = 0

        # Correr todas las fuentes concurrentemente
        tasks = [source.fetch_jobs() for source in self.sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_offers: list[JobOffer] = []
        for res in results:
            if isinstance(res, list):
                all_offers.extend(res)
            elif isinstance(res, Exception):
                logger.error(f"Falla en conector de ofertas: {res}")

        total_found = len(all_offers)
        for job in all_offers:
            # Filtro adicional de calidad antes de persistir
            qual = check_job_qualification(
                title=job.title,
                description=job.description,
                country=job.country,
                tags=job.tags,
            )
            if not qual.qualified:
                logger.debug(f"Descartada antes de guardar '{job.title}': {qual.reason}")
                continue

            is_new = await self.storage.save_job(job)
            if is_new:
                new_jobs += 1

        logger.info(f"Escaneo finalizado: {total_found} ofertas evaluadas, {new_jobs} nuevas ingresadas a la base.")
        return {"total_found": total_found, "new_jobs": new_jobs}

    async def evaluate_pending_jobs(self, limit: int = 25) -> list[tuple[JobOffer, MatchResult]]:
        """Evalúa las vacantes pendientes con el modelo de IA aplicando criterios estrictos."""
        profile = await self.get_active_profile()
        unseen = await self.storage.list_unseen_jobs()
        evaluated_matches: list[tuple[JobOffer, MatchResult]] = []

        batch = unseen[:limit]
        for job in batch:
            logger.info(f"Evaluando compatibilidad: {job.title} en {job.company}...")
            match = await self.matcher.evaluate(job, profile)
            
            job.match_score = match.score
            job.match_analysis = json.dumps(match.model_dump())

            # Si el modelo determinó DESCARTAR o incompatibilidad legal/geográfica
            if match.score <= 35 or match.verdict == "DESCARTAR":
                job.status = JobStatus.DISCARDED
            elif match.score < self.settings.match_min_score:
                job.status = JobStatus.EVALUATED
            else:
                job.status = JobStatus.SAVED

            await self.storage.save_job(job)
            evaluated_matches.append((job, match))

        return evaluated_matches

    async def generate_pitch_for_job(self, job_id: str) -> PitchDraft | None:
        """Genera un pitch personalizado para una vacante específica."""
        job = await self.storage.get_job(job_id)
        if not job:
            return None

        profile = await self.get_active_profile()
        match = None
        if job.match_analysis:
            try:
                match = MatchResult.model_validate_json(job.match_analysis)
            except Exception:
                pass

        pitch = await self.pitch_gen.generate_pitch(job, profile, match)
        job.pitch_draft = json.dumps(pitch.model_dump())
        await self.storage.save_job(job)
        return pitch

    async def generate_cv_for_job(self, job_id: str) -> tuple[TailoredCV, str] | None:
        """Genera un CV adaptado en formato Harvard ATS para la vacante."""
        job = await self.storage.get_job(job_id)
        if not job:
            return None

        profile = await self.get_active_profile()
        match = None
        if job.match_analysis:
            try:
                match = MatchResult.model_validate_json(job.match_analysis)
            except Exception:
                pass

        tailored_cv = await self.cv_gen.generate_tailored_cv(job, profile, match)
        html = self.cv_gen.render_harvard_html(tailored_cv)
        job.tailored_cv = json.dumps(tailored_cv.model_dump())
        await self.storage.save_job(job)
        return tailored_cv, html

    async def get_cv_html_for_job(self, job_id: str) -> str | None:
        """Obtiene o renderiza el HTML imprimible del CV de una vacante."""
        job = await self.storage.get_job(job_id)
        if not job:
            return None

        if job.tailored_cv:
            try:
                cv_data = TailoredCV.model_validate_json(job.tailored_cv)
                return self.cv_gen.render_harvard_html(cv_data)
            except Exception:
                pass

        res = await self.generate_cv_for_job(job_id)
        return res[1] if res else None
