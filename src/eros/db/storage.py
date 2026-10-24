from datetime import datetime, timezone
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
            await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA busy_timeout=5000;")
            await db.execute("PRAGMA synchronous=NORMAL;")
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
                    tailored_cv TEXT,
                    semantic_score INTEGER,
                    embedding TEXT
                )
            """)

            # Migraciones idempotentes para bases de datos existentes
            try:
                await db.execute("ALTER TABLE jobs ADD COLUMN tailored_cv TEXT")
            except Exception:
                pass

            try:
                await db.execute("ALTER TABLE jobs ADD COLUMN semantic_score INTEGER")
            except Exception:
                pass

            try:
                await db.execute("ALTER TABLE jobs ADD COLUMN embedding TEXT")
            except Exception:
                pass

            # Migraciones para Detective de Hiring Manager & Nota de Conexión
            for col in [
                "hiring_manager_name TEXT",
                "hiring_manager_title TEXT",
                "hiring_manager_url TEXT",
                "connection_note TEXT",
                "contact_email TEXT",
                "applied_at TEXT",
                "scored_by TEXT"
            ]:
                try:
                    await db.execute(f"ALTER TABLE jobs ADD COLUMN {col}")
                except Exception:
                    pass

            await db.execute("""
                CREATE TABLE IF NOT EXISTS vector_cache (
                    key TEXT PRIMARY KEY,
                    embedding TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS profile_cache (
                    key TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS agent_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(match_score)")
            await db.commit()

    async def save_job(self, job: JobOffer) -> bool:
        """Guarda o actualiza una vacante. Devuelve True si es nueva.
        
        Preserva status y campos evaluados previos si la actualización intenta
        resetear a 'new' o pasar valores nulos.
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT id, status FROM jobs WHERE id = ?", (job.id,)) as cursor:
                row = await cursor.fetchone()
                exists = row is not None

            tags_json = json.dumps(job.tags)
            embedding_json = json.dumps(job.embedding) if job.embedding else None
            if not exists:
                await db.execute("""
                    INSERT INTO jobs (
                        id, source, external_id, title, company, url, description,
                        tags, salary, country, is_remote, published_at, found_at,
                        status, match_score, match_analysis, pitch_draft, tailored_cv,
                        semantic_score, embedding, hiring_manager_name, hiring_manager_title,
                        hiring_manager_url, connection_note, contact_email, applied_at, scored_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job.id, job.source, job.external_id, job.title, job.company, job.url,
                    job.description, tags_json, job.salary, job.country,
                    1 if job.is_remote else 0, job.published_at, job.found_at,
                    job.status.value, job.match_score, job.match_analysis, job.pitch_draft,
                    job.tailored_cv, job.semantic_score, embedding_json,
                    job.hiring_manager_name, job.hiring_manager_title,
                    job.hiring_manager_url, job.connection_note, job.contact_email,
                    job.applied_at, job.scored_by
                ))
            else:
                await db.execute("""
                    UPDATE jobs SET
                        status = CASE WHEN jobs.status != 'new' AND ? = 'new' THEN jobs.status ELSE ? END,
                        match_score = COALESCE(?, match_score),
                        match_analysis = COALESCE(?, match_analysis),
                        pitch_draft = COALESCE(?, pitch_draft),
                        tailored_cv = COALESCE(?, tailored_cv),
                        salary = COALESCE(?, salary),
                        semantic_score = COALESCE(?, semantic_score),
                        embedding = COALESCE(?, embedding),
                        hiring_manager_name = COALESCE(?, hiring_manager_name),
                        hiring_manager_title = COALESCE(?, hiring_manager_title),
                        hiring_manager_url = COALESCE(?, hiring_manager_url),
                        connection_note = COALESCE(?, connection_note),
                        contact_email = COALESCE(?, contact_email),
                        applied_at = COALESCE(?, applied_at),
                        scored_by = COALESCE(?, scored_by)
                    WHERE id = ?
                """, (
                    job.status.value, job.status.value,
                    job.match_score, job.match_analysis, job.pitch_draft,
                    job.tailored_cv, job.salary, job.semantic_score, embedding_json,
                    job.hiring_manager_name, job.hiring_manager_title,
                    job.hiring_manager_url, job.connection_note, job.contact_email,
                    job.applied_at, job.scored_by, job.id
                ))

            await db.commit()
            return not exists

    async def save_scraped_job(self, job: JobOffer) -> bool:
        """Guarda una vacante obtenida por escaneo continuo. Devuelve True si es nueva.

        Si la vacante ya existía en la base de datos:
        - NO modifica ni resetea el status (preserva SAVED, APPLIED, DISCARDED, EVALUATED, etc.).
        - NO sobreescribe ni borra match_score, match_analysis, pitch_draft, tailored_cv,
          semantic_score, embedding ni scored_by.
        - Actualiza de forma segura únicamente los datos descriptivos del anuncio (título, descripción,
          salario si viene informado, modalidad, tags y contact_email).
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT id FROM jobs WHERE id = ?", (job.id,)) as cursor:
                exists = await cursor.fetchone() is not None

            tags_json = json.dumps(job.tags)
            embedding_json = json.dumps(job.embedding) if job.embedding else None
            if not exists:
                await db.execute("""
                    INSERT INTO jobs (
                        id, source, external_id, title, company, url, description,
                        tags, salary, country, is_remote, published_at, found_at,
                        status, match_score, match_analysis, pitch_draft, tailored_cv,
                        semantic_score, embedding, hiring_manager_name, hiring_manager_title,
                        hiring_manager_url, connection_note, contact_email, applied_at, scored_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job.id, job.source, job.external_id, job.title, job.company, job.url,
                    job.description, tags_json, job.salary, job.country,
                    1 if job.is_remote else 0, job.published_at, job.found_at,
                    job.status.value, job.match_score, job.match_analysis, job.pitch_draft,
                    job.tailored_cv, job.semantic_score, embedding_json,
                    job.hiring_manager_name, job.hiring_manager_title,
                    job.hiring_manager_url, job.connection_note, job.contact_email,
                    job.applied_at, job.scored_by
                ))
            else:
                await db.execute("""
                    UPDATE jobs SET
                        title = ?,
                        company = ?,
                        url = ?,
                        description = ?,
                        tags = ?,
                        salary = COALESCE(?, salary),
                        country = COALESCE(?, country),
                        is_remote = ?,
                        contact_email = COALESCE(?, contact_email)
                    WHERE id = ?
                """, (
                    job.title,
                    job.company,
                    job.url,
                    job.description,
                    tags_json,
                    job.salary,
                    job.country,
                    1 if job.is_remote else 0,
                    job.contact_email,
                    job.id
                ))

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
        """Devuelve las vacantes con match superior a un puntaje (incluye pendientes si min_score=0)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if min_score == 0:
                query = """
                    SELECT * FROM jobs
                    WHERE status != ?
                    ORDER BY COALESCE(match_score, 0) DESC, found_at DESC
                    LIMIT ?
                """
                params = (JobStatus.DISCARDED.value, limit)
            else:
                query = """
                    SELECT * FROM jobs
                    WHERE match_score >= ? AND status != ?
                    ORDER BY match_score DESC, found_at DESC
                    LIMIT ?
                """
                params = (min_score, JobStatus.DISCARDED.value, limit)

            async with db.execute(query, params) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_job(r) for r in rows]

    async def list_all_jobs(self, status: str | None = None, min_score: int = 0, limit: int = 200) -> list[JobOffer]:
        """Devuelve todas las vacantes guardadas en la base de datos sin excluir estados salvo que se pida."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            conditions: list[str] = []
            params: list[Any] = []

            if status:
                conditions.append("status = ?")
                params.append(status)
            elif min_score > 0:
                conditions.append("match_score >= ? AND status != ?")
                params.extend([min_score, JobStatus.DISCARDED.value])

            where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            query = f"""
                SELECT * FROM jobs
                {where_clause}
                ORDER BY COALESCE(match_score, 0) DESC, found_at DESC
                LIMIT ?
            """
            params.append(limit)

            async with db.execute(query, tuple(params)) as cursor:
                rows = await cursor.fetchall()
                return [self._row_to_job(r) for r in rows]

    async def update_job_status(self, job_id: str, status: JobStatus) -> None:
        """Actualiza el estado de una vacante (ej: aplicada, descartada)."""
        now_iso = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            if status == JobStatus.APPLIED:
                await db.execute(
                    "UPDATE jobs SET status = ?, applied_at = COALESCE(applied_at, ?) WHERE id = ?",
                    (status.value, now_iso, job_id)
                )
            else:
                await db.execute("UPDATE jobs SET status = ? WHERE id = ?", (status.value, job_id))
            await db.commit()

    async def update_job_contact_email(self, job_id: str, contact_email: str | None) -> None:
        """Actualiza el correo de contacto para postulación de una vacante."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE jobs SET contact_email = ? WHERE id = ?", (contact_email, job_id))
            await db.commit()

    async def record_application(self, job_id: str, contact_email: str | None = None) -> None:
        """Marca una vacante como postulada con fecha y correo de envío."""
        now_iso = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE jobs SET
                    status = ?,
                    applied_at = ?,
                    contact_email = COALESCE(?, contact_email)
                WHERE id = ?
            """, (JobStatus.APPLIED.value, now_iso, contact_email, job_id))
            await db.commit()

    async def delete_job(self, job_id: str) -> None:
        """Elimina físicamente una vacante de la base de datos."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            await db.commit()

    async def purge_unqualified_and_discarded_jobs(self, ids: list[str]) -> int:
        """Elimina físicamente una lista de vacantes por ID de la base de datos."""
        if not ids:
            return 0
        async with aiosqlite.connect(self.db_path) as db:
            placeholders = ",".join("?" for _ in ids)
            cursor = await db.execute(f"DELETE FROM jobs WHERE id IN ({placeholders})", tuple(ids))
            await db.commit()
            return cursor.rowcount

    async def delete_all_discarded_jobs(self) -> int:
        """Elimina físicamente todas las vacantes en estado descartado."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("DELETE FROM jobs WHERE status = ?", (JobStatus.DISCARDED.value,))
            await db.commit()
            return cursor.rowcount

    async def delete_all_jobs(self) -> int:
        """Elimina físicamente todas las vacantes escaneadas de la base de datos."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("DELETE FROM jobs")
            await db.commit()
            return cursor.rowcount

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

        keys = row.keys() if hasattr(row, "keys") else []
        tailored_cv = row["tailored_cv"] if "tailored_cv" in keys else None
        semantic_score = row["semantic_score"] if "semantic_score" in keys else None
        embedding = None
        if "embedding" in keys and row["embedding"]:
            try:
                embedding = json.loads(row["embedding"])
            except Exception:
                pass

        hiring_manager_name = row["hiring_manager_name"] if "hiring_manager_name" in keys else None
        hiring_manager_title = row["hiring_manager_title"] if "hiring_manager_title" in keys else None
        hiring_manager_url = row["hiring_manager_url"] if "hiring_manager_url" in keys else None
        connection_note = row["connection_note"] if "connection_note" in keys else None
        contact_email = row["contact_email"] if "contact_email" in keys else None
        applied_at = row["applied_at"] if "applied_at" in keys else None
        scored_by = row["scored_by"] if "scored_by" in keys else None

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
            tailored_cv=tailored_cv,
            semantic_score=semantic_score,
            embedding=embedding,
            hiring_manager_name=hiring_manager_name,
            hiring_manager_title=hiring_manager_title,
            hiring_manager_url=hiring_manager_url,
            connection_note=connection_note,
            contact_email=contact_email,
            applied_at=applied_at,
            scored_by=scored_by,
        )

    async def update_job_embedding(self, job_id: str, embedding: list[float], semantic_score: int) -> None:
        """Actualiza el vector embedding y score semántico de una vacante."""
        emb_json = json.dumps(embedding)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE jobs SET embedding = ?, semantic_score = ? WHERE id = ?",
                (emb_json, semantic_score, job_id)
            )
            await db.commit()

    async def save_profile_vector(self, embedding: list[float]) -> None:
        """Guarda en caché el vector del perfil de Mateo."""
        emb_json = json.dumps(embedding)
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS vector_cache (
                    key TEXT PRIMARY KEY,
                    embedding TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            await db.execute(
                "INSERT INTO vector_cache (key, embedding, updated_at) VALUES ('profile_vector', ?, ?) ON CONFLICT(key) DO UPDATE SET embedding = ?, updated_at = ?",
                (emb_json, now, emb_json, now)
            )
            await db.commit()

    async def get_profile_vector(self) -> list[float] | None:
        """Recupera el vector de perfil en caché si existe."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS vector_cache (
                        key TEXT PRIMARY KEY,
                        embedding TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """)
                async with db.execute("SELECT embedding FROM vector_cache WHERE key = 'profile_vector'") as cursor:
                    row = await cursor.fetchone()
                    if row and row[0]:
                        return json.loads(row[0])
        except Exception:
            pass
        return None

    async def get_setting(self, key: str, default: str | None = None) -> str | None:
        """Obtiene un valor de configuración persistente del agente."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute("SELECT value FROM agent_settings WHERE key = ?", (key,)) as cursor:
                    row = await cursor.fetchone()
                    return row[0] if row else default
        except Exception:
            return default

    async def set_setting(self, key: str, value: str) -> None:
        """Guarda o actualiza un valor de configuración persistente del agente."""
        now = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS agent_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            await db.execute(
                "INSERT INTO agent_settings (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?",
                (key, value, now, value, now),
            )
            await db.commit()

    async def get_all_settings(self) -> dict[str, str]:
        """Obtiene todos los valores de configuración persistentes."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute("SELECT key, value FROM agent_settings") as cursor:
                    rows = await cursor.fetchall()
                    return {r[0]: r[1] for r in rows}
        except Exception:
            return {}
