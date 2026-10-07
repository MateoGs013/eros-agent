import json
import logging
from typing import Any
import aiosqlite
from eros.config import get_settings
from eros.models import JobOffer, JobStatus, ProfileContext

logger = logging.getLogger(__name__)


class JobStorage:
    """Almacén asíncrono SQLite para vacantes e historial de matching."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(get_settings().db_file_path)

    async def init_db(self) -> None:
        """Crea las tablas necesarias si no existen."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    url TEXT NOT NULL,
                    description TEXT,
                    tags TEXT,
                    salary TEXT,
                    country TEXT,
                    is_remote INTEGER DEFAULT 1,
                    published_at TEXT,
                    found_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    match_score INTEGER,
                    match_analysis TEXT,
                    pitch_draft TEXT,
                    tailored_cv TEXT
                )
            """)

            # Migración idempotente para bases de datos existentes
            try:
                await db.execute("ALTER TABLE jobs ADD COLUMN tailored_cv TEXT")
            except Exception:
                pass

            await db.execute("""
                CREATE TABLE IF NOT EXISTS profile_cache (
                    key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(match_score)")
            await db.commit()

    async def save_job(self, job: JobOffer) -> bool:
        """Guarda o actualiza una vacante. Devuelve True si es nueva."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT id FROM jobs WHERE id = ?", (job.id,)) as cursor:
                exists = await cursor.fetchone() is not None

            tags_json = json.dumps(job.tags)
            if not exists:
                await db.execute("""
                    INSERT INTO jobs (
                        id, source, external_id, title, company, url, description,
                        tags, salary, country, is_remote, published_at, found_at,
                        status, match_score, match_analysis, pitch_draft, tailored_cv
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job.id, job.source, job.external_id, job.title, job.company, job.url,
                    job.description, tags_json, job.salary, job.country,
                    1 if job.is_remote else 0, job.published_at, job.found_at,
                    job.status.value, job.match_score, job.match_analysis, job.pitch_draft,
                    job.tailored_cv
                ))
            else:
                await db.execute("""
                    UPDATE jobs SET
                        status = ?, match_score = ?, match_analysis = ?, pitch_draft = ?, tailored_cv = ?
                    WHERE id = ?
                """, (job.status.value, job.match_score, job.match_analysis, job.pitch_draft, job.tailored_cv, job.id))

            await db.commit()
            return not exists

    async def get_job(self, job_id: str) -> JobOffer | None:
        """Obtiene una vacante por su ID."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return None
                return self._row_to_job(row)

    async def list_unseen_jobs(self) -> list[JobOffer]:
        """Devuelve las vacantes que aún no fueron evaluadas."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM jobs WHERE status = ? ORDER BY found_at DESC", (JobStatus.NEW.value,)) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_job(r) for r in rows]

    async def list_matched_jobs(self, min_score: int = 70, limit: int = 20) -> list[JobOffer]:
        """Devuelve las vacantes con match superior a un puntaje."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM jobs
                WHERE match_score >= ? AND status != ?
                ORDER BY match_score DESC, found_at DESC
                LIMIT ?
            """, (min_score, JobStatus.DISCARDED.value, limit)) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_job(r) for r in rows]

    async def update_job_status(self, job_id: str, status: JobStatus) -> None:
        """Actualiza el estado de una vacante (ej: aplicada, descartada)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE jobs SET status = ? WHERE id = ?", (status.value, job_id))
            await db.commit()

    async def save_profile_cache(self, profile: ProfileContext) -> None:
        """Guarda el perfil de Mateo en caché local."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                INSERT OR REPLACE INTO profile_cache (key, data, updated_at)
                VALUES ('main', ?, ?)
            """, (profile.model_dump_json(), profile.updated_at))
            await db.commit()

    async def get_profile_cache(self) -> ProfileContext | None:
        """Obtiene el perfil en caché local si existe."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT data FROM profile_cache WHERE key = 'main'") as cursor:
                row = await cursor.fetchone()
                if row:
                    return ProfileContext.model_validate_json(row[0])
                return None

    def _row_to_job(self, row: aiosqlite.Row) -> JobOffer:
        tags = []
        if row["tags"]:
            try:
                tags = json.loads(row["tags"])
            except Exception:
                pass
        return JobOffer(
            id=row["id"],
            source=row["source"],
            external_id=row["external_id"],
            title=row["title"],
            company=row["company"],
            url=row["url"],
            description=row["description"] or "",
            tags=tags,
            salary=row["salary"],
            country=row["country"],
            is_remote=bool(row["is_remote"]),
            published_at=row["published_at"],
            found_at=row["found_at"],
            status=JobStatus(row["status"]),
            match_score=row["match_score"],
            match_analysis=row["match_analysis"],
            pitch_draft=row["pitch_draft"],
            tailored_cv=row["tailored_cv"] if "tailored_cv" in row.keys() else None
        )
