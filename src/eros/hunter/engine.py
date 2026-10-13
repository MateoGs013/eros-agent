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
from eros.hunter.sources.computrabajo import ComputrabajoSource
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
from eros.hunter.embeddings import (
    build_job_vector_text,
    build_profile_vector_text,
    cosine_similarity,
    normalize_semantic_score,
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
            ComputrabajoSource(),
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

    async def purge_incompatible_and_discarded_jobs(self) -> int:
        """Purga y elimina físicamente de la base de datos las vacantes incompatibles y descartadas."""
        deleted_count = 0
        try:
            all_jobs = await self.storage.list_all_jobs(limit=1000)
            ids_to_purge: set[str] = set()

            for j in all_jobs:
                # 1. Ya en estado descartado
                if j.status == JobStatus.DISCARDED:
                    ids_to_purge.add(j.id)
                    continue

                # 2. Incompatible por filtros geográficos o stack
                qual = check_job_qualification(
                    title=j.title,
                    description=j.description,
                    country=j.country,
                    tags=j.tags,
                )
                if not qual.qualified:
                    ids_to_purge.add(j.id)
                    continue

                # 3. Match score evaluado muy bajo (<= 35%)
                if j.match_score is not None and j.match_score <= 35:
                    ids_to_purge.add(j.id)
                    continue

            if ids_to_purge:
                deleted_count = await self.storage.purge_unqualified_and_discarded_jobs(list(ids_to_purge))
                logger.info(f"Purga física ejecutada: {deleted_count} vacantes incompatibles/descartadas eliminadas de SQLite.")
        except Exception as e:
            logger.warning(f"Error durante purga de vacantes incompatibles: {e}")
        return deleted_count

    async def clean_existing_unqualified_jobs(self) -> int:
        """Alias para purga completa de vacantes no calificadas/descartadas."""
        return await self.purge_incompatible_and_discarded_jobs()

    async def clear_all_jobs(self) -> int:
        """Elimina todas las vacantes escaneadas de la base de datos para escanear desde cero."""
        deleted = await self.storage.delete_all_jobs()
        logger.info(f"Todas las vacantes escaneadas ({deleted}) fueron eliminadas.")
        return deleted

    async def get_or_create_profile_vector(self, force_refresh: bool = False) -> list[float]:
        """Obtiene el vector embedding del perfil de Mateo, generándolo si no existe."""
        if not force_refresh:
            cached_vec = await self.storage.get_profile_vector()
            if cached_vec and len(cached_vec) > 0:
                return cached_vec

        profile = await self.get_active_profile()
        profile_text = build_profile_vector_text(profile)
        vec = await self.matcher.llm.embed_text(profile_text)
        if vec:
            await self.storage.save_profile_vector(vec)
            logger.info("Vector semántico del perfil de Mateo generado y guardado en SQLite.")
        return vec

    async def sync_profile(self) -> ProfileContext:
        """Actualiza y guarda en caché el perfil más reciente de Mateo desde la API."""
        logger.info("Sincronizando perfil desde la API del portafolio...")
        profile = await self.portfolio_client.fetch_profile()
        await self.storage.save_profile_cache(profile)
        logger.info(f"Perfil sincronizado: {profile.name} con {len(profile.projects)} proyectos y {len(profile.tech_stack)} tecnologías.")
        # Regenerar vector del perfil actualizado
        await self.get_or_create_profile_vector(force_refresh=True)
        return profile

    async def get_active_profile(self) -> ProfileContext:
        """Devuelve el perfil activo (de caché o API viva)."""
        cached = await self.storage.get_profile_cache()
        if cached:
            return cached
        return await self.sync_profile()

    async def vectorize_and_score_jobs(self, jobs: list[JobOffer]) -> int:
        """Genera embeddings y calcula el puntaje semántico en batch para una lista de ofertas."""
        if not jobs:
            return 0

        profile_vec = await self.get_or_create_profile_vector()
        if not profile_vec:
            logger.warning("No se pudo obtener el vector del perfil; omitiendo scoring vectorial.")
            return 0

        texts = [build_job_vector_text(j) for j in jobs]
        embeddings = await self.matcher.llm.batch_embed_texts(texts)

        updated_count = 0
        for j, emb in zip(jobs, embeddings):
            if emb:
                cos_sim = cosine_similarity(profile_vec, emb)
                semantic_score = normalize_semantic_score(cos_sim)
                j.embedding = emb
                j.semantic_score = semantic_score
                await self.storage.update_job_embedding(j.id, emb, semantic_score)
                updated_count += 1

        logger.info(f"Vectorización completada: {updated_count}/{len(jobs)} vacantes vectorizadas con éxito.")
        return updated_count

    async def backfill_missing_embeddings(self, limit: int = 100) -> int:
        """Vectoriza vacantes existentes en la base que aún no tengan embedding."""
        all_jobs = await self.storage.list_all_jobs(limit=1000)
        unembedded = [j for j in all_jobs if not j.embedding or len(j.embedding) == 0][:limit]
        if not unembedded:
            return 0
        logger.info(f"Iniciando vectorización retroactiva de {len(unembedded)} vacantes...")
        return await self.vectorize_and_score_jobs(unembedded)

    async def semantic_search(self, query: str, limit: int = 30) -> list[JobOffer]:
        """Realiza una búsqueda semántica de vacantes ordenadas por similitud con la consulta."""
        if not query or not query.strip():
            return await self.storage.list_all_jobs(limit=limit)

        query_vec = await self.matcher.llm.embed_text(query.strip())
        if not query_vec:
            return []

        all_jobs = await self.storage.list_all_jobs(limit=500)
        jobs_with_scores: list[tuple[JobOffer, float]] = []

        for j in all_jobs:
            if j.embedding and len(j.embedding) > 0:
                sim = cosine_similarity(query_vec, j.embedding)
                jobs_with_scores.append((j, sim))

        jobs_with_scores.sort(key=lambda x: x[1], reverse=True)
        return [j for j, _ in jobs_with_scores[:limit]]

    async def run_scan(self) -> dict[str, int]:
        """Ejecuta una búsqueda en todas las fuentes curadas y guarda únicamente las ofertas calificadas."""
        await self.initialize()
        total_found = 0
        new_jobs = 0

        # Filtrar fuentes según configuración dinámica
        enabled_sources_json = await self.storage.get_setting("sources_enabled")
        active_sources = self.sources
        if enabled_sources_json:
            try:
                enabled_map = json.loads(enabled_sources_json)
                active_sources = [s for s in self.sources if enabled_map.get(s.name, True)]
            except Exception as e:
                logger.warning(f"Error parseando sources_enabled: {e}")

        # Filtro de modalidad remota
        remote_only_val = await self.storage.get_setting("remote_only", "1")
        remote_only = remote_only_val == "1"

        # Correr las fuentes activas concurrentemente
        tasks = [source.fetch_jobs() for source in active_sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_offers: list[JobOffer] = []
        for res in results:
            if isinstance(res, list):
                all_offers.extend(res)
            elif isinstance(res, Exception):
                logger.error(f"Falla en conector de ofertas: {res}")

        total_found = len(all_offers)
        newly_saved_jobs: list[JobOffer] = []
        for job in all_offers:
            if remote_only and not job.is_remote:
                continue

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
                newly_saved_jobs.append(job)

        # Vectorizar y calcular score semántico en batch para las nuevas ofertas
        if newly_saved_jobs:
            await self.vectorize_and_score_jobs(newly_saved_jobs)

        logger.info(f"Escaneo finalizado: {total_found} ofertas evaluadas, {new_jobs} nuevas ingresadas a la base.")
        return {"total_found": total_found, "new_jobs": new_jobs}

    async def evaluate_pending_jobs(self, limit: int = 25) -> list[tuple[JobOffer, MatchResult]]:
        """Evalúa las vacantes pendientes con el modelo de IA aplicando criterios estrictos."""
        profile = await self.get_active_profile()
        unseen = await self.storage.list_unseen_jobs()
        evaluated_matches: list[tuple[JobOffer, MatchResult]] = []

        # Asegurar que las vacantes pendientes estén vectorizadas
        unembedded = [j for j in unseen[:limit] if not j.embedding or len(j.embedding) == 0]
        if unembedded:
            await self.vectorize_and_score_jobs(unembedded)

        # Obtener umbral dinámico de la base de datos
        min_score_str = await self.storage.get_setting("match_min_score", str(self.settings.match_min_score))
        try:
            min_score = int(min_score_str) if min_score_str else self.settings.match_min_score
        except ValueError:
            min_score = self.settings.match_min_score

        # Ordenar vacantes pendientes por afinidad semántica descendente (las mejores primero)
        batch = sorted(unseen[:limit], key=lambda j: (j.semantic_score or 0), reverse=True)
        for job in batch:
            # Pre-filtro semántico: Si el score vectorial es muy bajo (< 35%), descartar de inmediato sin gastar llamadas
            if job.semantic_score is not None and job.semantic_score < 35:
                logger.info(f"Descarte semántico automático (<35%): {job.title} ({job.semantic_score}%)")
                job.status = JobStatus.DISCARDED
                await self.storage.save_job(job)
                continue

            logger.info(f"Evaluando compatibilidad: {job.title} en {job.company} (Semántico: {job.semantic_score or 0}%)...")
            match = await self.matcher.evaluate(job, profile)
            
            job.match_score = match.score
            job.match_analysis = json.dumps(match.model_dump())
            if (not job.salary or not job.salary.strip()) and match.salary_estimate:
                job.salary = match.salary_estimate

            # Persistir detective de hiring manager y nota de conexión LinkedIn
            if match.recruiter_note:
                job.connection_note = match.recruiter_note
            if match.hiring_manager_name and not job.hiring_manager_name:
                job.hiring_manager_name = match.hiring_manager_name
            if match.hiring_manager_title and not job.hiring_manager_title:
                job.hiring_manager_title = match.hiring_manager_title
            if match.hiring_manager_url and not job.hiring_manager_url:
                job.hiring_manager_url = match.hiring_manager_url

            # Si el modelo determinó DESCARTAR o incompatibilidad legal/geográfica
            if match.score <= 35 or match.verdict == "DESCARTAR":
                job.status = JobStatus.DISCARDED
            elif match.score < min_score:
                job.status = JobStatus.EVALUATED
            else:
                job.status = JobStatus.SAVED

            await self.storage.save_job(job)
            evaluated_matches.append((job, match))

        return evaluated_matches

    async def evaluate_single_job(self, job_id: str) -> tuple[JobOffer, MatchResult] | None:
        """Evalúa una única vacante específica con el modelo LLM bajo demanda."""
        job = await self.storage.get_job(job_id)
        if not job:
            return None

        profile = await self.get_active_profile()
        min_score_str = await self.storage.get_setting("match_min_score", str(self.settings.match_min_score))
        try:
            min_score = int(min_score_str) if min_score_str else self.settings.match_min_score
        except ValueError:
            min_score = self.settings.match_min_score

        logger.info(f"Evaluando vacante individual: {job.title} en {job.company}...")
        match = await self.matcher.evaluate(job, profile)
        job.match_score = match.score
        job.match_analysis = json.dumps(match.model_dump())
        if (not job.salary or not job.salary.strip()) and match.salary_estimate:
            job.salary = match.salary_estimate

        # Persistir detective de hiring manager y nota de conexión LinkedIn
        if match.recruiter_note:
            job.connection_note = match.recruiter_note
        if match.hiring_manager_name and not job.hiring_manager_name:
            job.hiring_manager_name = match.hiring_manager_name
        if match.hiring_manager_title and not job.hiring_manager_title:
            job.hiring_manager_title = match.hiring_manager_title
        if match.hiring_manager_url and not job.hiring_manager_url:
            job.hiring_manager_url = match.hiring_manager_url

        if match.score <= 35 or match.verdict == "DESCARTAR":
            job.status = JobStatus.DISCARDED
        elif match.score < min_score:
            job.status = JobStatus.EVALUATED
        else:
            job.status = JobStatus.SAVED

        await self.storage.save_job(job)
        return job, match

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
