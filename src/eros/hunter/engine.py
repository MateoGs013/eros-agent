import asyncio
import json
import logging
from eros.config import get_settings
from eros.db.storage import JobStorage
from eros.hunter.cv_generator import CVGenerator
from eros.hunter.email_finder import EMAIL_SOURCE_POSTING, EmailFinder
from eros.hunter.filters import check_job_qualification, extract_contact_email
from eros.hunter.dispatcher import JobApplicationDispatcher
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


class ScanInProgressError(RuntimeError):
    """Ya hay un escaneo (o una evaluación en lote) corriendo en este proceso."""
    pass


class HunterEngine:
    """Orquestador central del ciclo de búsqueda, deduplicación y scoring de vacantes."""

    def __init__(self, storage: JobStorage | None = None):
        self.settings = get_settings()
        self.storage = storage or JobStorage()
        self.portfolio_client = PortfolioClient()
        self.matcher = JobMatcher()
        self.pitch_gen = PitchGenerator()
        self.cv_gen = CVGenerator()
        self.email_finder = EmailFinder(self.settings)
        # Exclusión de escaneos/evaluaciones simultáneos (chequeo y marca sin await en el medio)
        self._scan_running = False
        self._evaluation_running = False
        self.app_dispatcher = JobApplicationDispatcher(storage=self.storage, engine=self)
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
        """Inicializa la base de datos y sincroniza el perfil inicial si no existe.

        No borra ni descarta vacantes: el historial (descartadas, postuladas) se conserva.
        """
        await self.storage.init_db()
        await self.backfill_missing_contact_emails()
        cached = await self.storage.get_profile_cache()
        if not cached:
            await self.sync_profile()

    async def backfill_missing_contact_emails(self, limit: int = 500) -> int:
        """Completa el correo de contacto de vacantes que lo tienen publicado en el aviso."""
        all_jobs = await self.storage.list_all_jobs(limit=limit)
        updated = 0
        for j in all_jobs:
            if not j.contact_email and j.description:
                email = extract_contact_email(j.description)
                if email:
                    j.contact_email = email
                    await self.storage.update_job_contact_email(j.id, email, source=EMAIL_SOURCE_POSTING)
                    updated += 1
        if updated > 0:
            logger.info(f"Se detectaron y actualizaron {updated} correos de contacto en vacantes existentes.")
        return updated

    async def discard_incompatible_jobs(self) -> int:
        """Marca como descartadas (sin borrarlas) las vacantes que no pasan los filtros actuales.

        Nunca toca las postuladas. Las descartadas siguen en la base para que un nuevo
        escaneo no las traiga de vuelta como nuevas.
        """
        try:
            all_jobs = await self.storage.list_all_jobs(limit=5000)
            ids_to_discard: list[str] = []
            for j in all_jobs:
                if j.status in (JobStatus.DISCARDED, JobStatus.APPLIED) or j.applied_at:
                    continue
                qual = check_job_qualification(
                    title=j.title,
                    description=j.description,
                    country=j.country,
                    tags=j.tags,
                )
                if not qual.qualified or (j.match_score is not None and j.match_score <= 35):
                    ids_to_discard.append(j.id)
            discarded = await self.storage.discard_jobs(ids_to_discard)
            if discarded:
                logger.info(f"{discarded} vacantes incompatibles marcadas como descartadas.")
            return discarded
        except Exception as e:
            logger.warning(f"Error al descartar vacantes incompatibles: {e}")
            return 0

    async def clean_existing_unqualified_jobs(self) -> int:
        """Alias histórico de discard_incompatible_jobs (ya no borra físicamente)."""
        return await self.discard_incompatible_jobs()

    async def clear_all_jobs(self) -> int:
        """Elimina las vacantes no postuladas recordando sus ids (no vuelven como nuevas)."""
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

    @property
    def scan_in_progress(self) -> bool:
        return self._scan_running

    @property
    def evaluation_in_progress(self) -> bool:
        return self._evaluation_running

    async def run_scan(self) -> dict[str, int]:
        """Ejecuta una búsqueda en todas las fuentes curadas y guarda únicamente las ofertas calificadas.

        Lanza ScanInProgressError si ya hay un escaneo corriendo.
        """
        if self._scan_running:
            raise ScanInProgressError("Ya hay un escaneo en curso.")
        self._scan_running = True
        try:
            return await self._run_scan()
        finally:
            self._scan_running = False

    async def _run_scan(self) -> dict[str, int]:
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

            # Extraer correo de contacto laboral si está presente en la descripción
            if not job.contact_email and job.description:
                job.contact_email = extract_contact_email(job.description)
            if job.contact_email:
                job.contact_email_source = job.contact_email_source or EMAIL_SOURCE_POSTING

            is_new = await self.storage.save_scraped_job(job)
            if is_new:
                new_jobs += 1
                newly_saved_jobs.append(job)

        # Vectorizar y calcular score semántico en batch para las nuevas ofertas
        if newly_saved_jobs:
            await self.vectorize_and_score_jobs(newly_saved_jobs)

        logger.info(f"Escaneo finalizado: {total_found} ofertas evaluadas, {new_jobs} nuevas ingresadas a la base.")
        return {"total_found": total_found, "new_jobs": new_jobs}

    async def _min_score(self) -> int:
        min_score_str = await self.storage.get_setting("match_min_score", str(self.settings.match_min_score))
        try:
            return int(min_score_str) if min_score_str else self.settings.match_min_score
        except ValueError:
            return self.settings.match_min_score

    async def _resolve_contact_email(self, job: JobOffer) -> None:
        """Busca un correo real (aviso, sitio de la empresa o Hunter.io) si la vacante no tiene."""
        if job.contact_email:
            return
        found_email, source = await self.email_finder.resolve_contact_email(
            company=job.company,
            job_url=job.url,
            recruiter_name=job.hiring_manager_name,
            description=job.description,
        )
        if found_email:
            job.contact_email = found_email
            job.contact_email_source = source
            logger.info(f"Email de contacto resuelto para '{job.company}': {found_email} (fuente: {source})")

    def _apply_match(self, job: JobOffer, match: MatchResult, min_score: int) -> None:
        """Vuelca el resultado de la evaluación en la vacante y decide su estado.

        Una estimación heurística (sin IA) nunca deja la vacante en SAVED: queda en
        EVALUATED para revisarla a mano, o DISCARDED si hubo una incompatibilidad explícita.
        """
        heuristic = getattr(match, "scored_by", "gemini") == "heuristic"
        job.match_score = match.score
        job.match_analysis = json.dumps(match.model_dump())
        job.scored_by = getattr(match, "scored_by", "gemini")
        if not heuristic and (not job.salary or not job.salary.strip()) and match.salary_estimate:
            job.salary = match.salary_estimate

        # Persistir detective de hiring manager y nota de conexión LinkedIn
        if match.recruiter_note and not heuristic:
            job.connection_note = match.recruiter_note
        if match.hiring_manager_name and not job.hiring_manager_name:
            job.hiring_manager_name = match.hiring_manager_name
        if match.hiring_manager_title and not job.hiring_manager_title:
            job.hiring_manager_title = match.hiring_manager_title
        if match.hiring_manager_url and not job.hiring_manager_url:
            job.hiring_manager_url = match.hiring_manager_url

        if match.verdict == "DESCARTAR" or (not heuristic and match.score <= 35):
            job.status = JobStatus.DISCARDED
        elif heuristic or match.score < min_score:
            job.status = JobStatus.EVALUATED
        else:
            job.status = JobStatus.SAVED

    async def evaluate_pending_jobs(self, limit: int = 25) -> list[tuple[JobOffer, MatchResult]]:
        """Evalúa las vacantes pendientes con el modelo de IA aplicando criterios estrictos.

        Lanza ScanInProgressError si ya hay una evaluación en lote corriendo.
        """
        if self._evaluation_running:
            raise ScanInProgressError("Ya hay una evaluación en curso.")
        self._evaluation_running = True
        try:
            return await self._evaluate_pending_jobs(limit)
        finally:
            self._evaluation_running = False

    async def _evaluate_pending_jobs(self, limit: int) -> list[tuple[JobOffer, MatchResult]]:
        profile = await self.get_active_profile()
        unseen = await self.storage.list_unseen_jobs()
        evaluated_matches: list[tuple[JobOffer, MatchResult]] = []

        # Asegurar que las vacantes pendientes estén vectorizadas
        unembedded = [j for j in unseen[:limit] if not j.embedding or len(j.embedding) == 0]
        if unembedded:
            await self.vectorize_and_score_jobs(unembedded)

        min_score = await self._min_score()

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
            self._apply_match(job, match, min_score)
            await self._resolve_contact_email(job)
            await self.storage.save_job(job)
            evaluated_matches.append((job, match))

        return evaluated_matches

    async def evaluate_single_job(self, job_id: str) -> tuple[JobOffer, MatchResult] | None:
        """Evalúa una única vacante específica con el modelo LLM bajo demanda."""
        job = await self.storage.get_job(job_id)
        if not job:
            return None

        profile = await self.get_active_profile()
        min_score = await self._min_score()

        logger.info(f"Evaluando vacante individual: {job.title} en {job.company}...")
        match = await self.matcher.evaluate(job, profile)
        self._apply_match(job, match, min_score)
        await self._resolve_contact_email(job)
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

    def _stored_cv(self, job: JobOffer) -> TailoredCV | None:
        if not job.tailored_cv:
            return None
        try:
            return TailoredCV.model_validate_json(job.tailored_cv)
        except Exception as e:
            logger.error(f"CV guardado ilegible para la vacante {job.id}: {e}")
            return None

    async def get_cv_html_for_job(self, job_id: str) -> str | None:
        """Renderiza el HTML imprimible del CV ya guardado de una vacante (nunca lo genera)."""
        job = await self.storage.get_job(job_id)
        cv_data = self._stored_cv(job) if job else None
        return self.cv_gen.render_harvard_html(cv_data) if cv_data else None

    async def get_cv_pdf_for_job(self, job_id: str) -> bytes | None:
        """Renderiza el PDF (1 página A4 Harvard ATS) del CV ya guardado de una vacante (nunca lo genera)."""
        job = await self.storage.get_job(job_id)
        cv_data = self._stored_cv(job) if job else None
        return self.cv_gen.render_pdf(cv_data) if cv_data else None
