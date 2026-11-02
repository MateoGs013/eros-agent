from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Any
import aiosqlite
from eros.config import get_settings
from eros.hunter.normalize import job_dedup_key
from eros.models import JobOffer, JobStatus, ProfileContext

logger = logging.getLogger(__name__)

# Un envío marcado "sending" más viejo que esto se considera cortado (no sabemos si salió).
STALE_SEND_MINUTES = 10

_JOB_COLUMNS = (
    "id, source, external_id, title, company, url, description, "
    "tags, salary, country, is_remote, published_at, found_at, "
    "status, match_score, match_analysis, pitch_draft, tailored_cv, "
    "semantic_score, embedding, hiring_manager_name, hiring_manager_title, "
    "hiring_manager_url, connection_note, contact_email, applied_at, scored_by, "
    "contact_email_source, dedup_key"
)
_INSERT_JOB_SQL = f"INSERT INTO jobs ({_JOB_COLUMNS}) VALUES ({', '.join('?' for _ in _JOB_COLUMNS.split(','))})"


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
                "scored_by TEXT",
                "contact_email_source TEXT",
                "send_state TEXT",
                "send_started_at TEXT",
                "send_key TEXT",
                "dedup_key TEXT",
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

            # Vacantes borradas a mano: el escaneo no las vuelve a traer como nuevas.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS seen_jobs (
                    id TEXT PRIMARY KEY,
                    dedup_key TEXT,
                    reason TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_score ON jobs(match_score)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_jobs_dedup ON jobs(dedup_key)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_seen_jobs_dedup ON seen_jobs(dedup_key)")

            await self._backfill_dedup_keys(db)
            await self._migrate_legacy_contact_emails(db)
            await db.commit()

    async def _backfill_dedup_keys(self, db: aiosqlite.Connection) -> None:
        async with db.execute("SELECT id, company, title, source FROM jobs WHERE dedup_key IS NULL") as cursor:
            rows = await cursor.fetchall()
        for job_id, company, title, source in rows:
            await db.execute(
                "UPDATE jobs SET dedup_key = ? WHERE id = ?",
                (job_dedup_key(company, title, source), job_id),
            )

    async def _migrate_legacy_contact_emails(self, db: aiosqlite.Connection) -> None:
        """Asigna fuente a los correos guardados antes de registrarla y borra los adivinados.

        Antes Eros guardaba `jobs@<dominio>` armado a partir del nombre de la empresa o de la URL.
        - Si el correo aparece en el aviso: fuente "posting".
        - Si tiene la forma exacta de un correo adivinado y la vacante no fue postulada: se borra.
        - Cualquier otro (no se sabe de dónde salió): fuente "unknown", que no se usa para
          enviar sin que Mateo escriba la dirección.
        """
        from eros.hunter.email_finder import EmailFinder

        async with db.execute("""
            SELECT id, company, url, description, contact_email, status, applied_at
            FROM jobs
            WHERE contact_email IS NOT NULL AND contact_email != '' AND contact_email_source IS NULL
        """) as cursor:
            rows = await cursor.fetchall()
        if not rows:
            return

        finder = EmailFinder()
        guessed_prefixes = {"jobs", "careers", "talent", "hiring", "rrhh"}
        for job_id, company, url, description, email, status, applied_at in rows:
            email_l = (email or "").strip().lower()
            if email_l in (description or "").lower():
                await db.execute("UPDATE jobs SET contact_email_source = 'posting' WHERE id = ?", (job_id,))
                continue

            prefix, _, domain = email_l.partition("@")
            guessed_domains = {
                finder.extract_domain_from_url(url or ""),
                finder.infer_domain_from_company(company or "", allow_placeholder=True),
            }
            looks_guessed = prefix in guessed_prefixes and domain in guessed_domains
            was_applied = status == JobStatus.APPLIED.value or bool(applied_at)
            if looks_guessed and not was_applied:
                logger.info(f"Borrando correo adivinado heredado de la vacante {job_id}: {email_l}")
                await db.execute("UPDATE jobs SET contact_email = NULL WHERE id = ?", (job_id,))
            else:
                await db.execute("UPDATE jobs SET contact_email_source = 'unknown' WHERE id = ?", (job_id,))

    @staticmethod
    def _insert_params(job: JobOffer) -> tuple:
        email_source = None
        if job.contact_email:
            in_posting = job.contact_email.lower() in (job.description or "").lower()
            email_source = job.contact_email_source or ("posting" if in_posting else "unknown")
        return (
            job.id, job.source, job.external_id, job.title, job.company, job.url,
            job.description, json.dumps(job.tags), job.salary, job.country,
            1 if job.is_remote else 0, job.published_at, job.found_at,
            job.status.value, job.match_score, job.match_analysis, job.pitch_draft,
            job.tailored_cv, job.semantic_score, json.dumps(job.embedding) if job.embedding else None,
            job.hiring_manager_name, job.hiring_manager_title,
            job.hiring_manager_url, job.connection_note, job.contact_email,
            job.applied_at, job.scored_by,
            email_source,
            job_dedup_key(job.company, job.title, job.source),
        )

    async def save_job(self, job: JobOffer) -> bool:
        """Guarda o actualiza una vacante. Devuelve True si es nueva.

        Preserva status y campos evaluados previos si la actualización intenta
        resetear a 'new' o pasar valores nulos.
        """
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT id, status FROM jobs WHERE id = ?", (job.id,)) as cursor:
                row = await cursor.fetchone()
                exists = row is not None

            embedding_json = json.dumps(job.embedding) if job.embedding else None
            if not exists:
                await db.execute(_INSERT_JOB_SQL, self._insert_params(job))
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
                        contact_email_source = CASE
                            WHEN ? IS NOT NULL AND ? IS NOT NULL THEN ?
                            ELSE contact_email_source END,
                        contact_email = COALESCE(?, contact_email),
                        applied_at = COALESCE(?, applied_at),
                        scored_by = COALESCE(?, scored_by)
                    WHERE id = ?
                """, (
                    job.status.value, job.status.value,
                    job.match_score, job.match_analysis, job.pitch_draft,
                    job.tailored_cv, job.salary, job.semantic_score, embedding_json,
                    job.hiring_manager_name, job.hiring_manager_title,
                    job.hiring_manager_url, job.connection_note,
                    job.contact_email, job.contact_email_source, job.contact_email_source,
                    job.contact_email,
                    job.applied_at, job.scored_by, job.id
                ))

            await db.commit()
            return not exists

    async def save_scraped_job(self, job: JobOffer) -> bool:
        """Guarda una vacante obtenida por escaneo continuo. Devuelve True si es nueva.

        - Si el id fue borrado antes (seen_jobs), no la vuelve a traer.
        - Si ya existe la misma vacante (empresa + título normalizados) desde otra fuente,
          no la duplica.
        Si la vacante ya existía en la base de datos:
        - NO modifica ni resetea el status (preserva SAVED, APPLIED, DISCARDED, EVALUATED, etc.).
        - NO sobreescribe ni borra match_score, match_analysis, pitch_draft, tailored_cv,
          semantic_score, embedding ni scored_by.
        - Actualiza de forma segura únicamente los datos descriptivos del anuncio (título, descripción,
          salario si viene informado, modalidad, tags y contact_email si no tenía).
        """
        dedup_key = job_dedup_key(job.company, job.title, job.source)
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT id FROM jobs WHERE id = ?", (job.id,)) as cursor:
                exists = await cursor.fetchone() is not None

            if not exists:
                async with db.execute(
                    "SELECT 1 FROM seen_jobs WHERE id = ? OR dedup_key = ? LIMIT 1", (job.id, dedup_key)
                ) as cursor:
                    if await cursor.fetchone():
                        return False
                async with db.execute("SELECT 1 FROM jobs WHERE dedup_key = ? LIMIT 1", (dedup_key,)) as cursor:
                    if await cursor.fetchone():
                        logger.debug(f"Vacante duplicada entre fuentes omitida: '{job.title}' en {job.company} ({job.source})")
                        return False
                await db.execute(_INSERT_JOB_SQL, self._insert_params(job))
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
                        contact_email_source = CASE
                            WHEN contact_email IS NULL AND ? IS NOT NULL THEN ?
                            ELSE contact_email_source END,
                        contact_email = COALESCE(contact_email, ?)
                    WHERE id = ?
                """, (
                    job.title,
                    job.company,
                    job.url,
                    job.description,
                    json.dumps(job.tags),
                    job.salary,
                    job.country,
                    1 if job.is_remote else 0,
                    job.contact_email, job.contact_email_source or "posting",
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

    async def count_jobs(self, high_match_min_score: int = 75) -> dict[str, int]:
        """Cuenta las vacantes por estado (cada vacante una sola vez) y las de puntaje alto."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status") as cursor:
                by_status = {row[0]: row[1] for row in await cursor.fetchall()}
            async with db.execute(
                "SELECT COUNT(*) FROM jobs WHERE match_score >= ? AND status != ?",
                (high_match_min_score, JobStatus.DISCARDED.value),
            ) as cursor:
                high = (await cursor.fetchone())[0]
        return {
            "total": sum(by_status.values()),
            "high_match": high,
            **{s.value: by_status.get(s.value, 0) for s in JobStatus},
        }

    async def update_job_status(self, job_id: str, status: JobStatus) -> None:
        """Actualiza el estado de una vacante (ej: aplicada, descartada)."""
        now_iso = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            if status == JobStatus.APPLIED:
                await db.execute(
                    "UPDATE jobs SET status = ?, applied_at = COALESCE(applied_at, ?), send_state = NULL WHERE id = ?",
                    (status.value, now_iso, job_id)
                )
            else:
                await db.execute("UPDATE jobs SET status = ? WHERE id = ?", (status.value, job_id))
            await db.commit()

    async def update_job_contact_email(self, job_id: str, contact_email: str | None, source: str | None = "manual") -> None:
        """Actualiza el correo de contacto de una vacante junto con su fuente."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE jobs SET contact_email = ?, contact_email_source = ? WHERE id = ?",
                (contact_email, source if contact_email else None, job_id),
            )
            await db.commit()

    async def claim_send(self, job_id: str, send_key: str, force_retry: bool = False) -> str:
        """Marca de forma atómica que la postulación se está enviando.

        Devuelve "claimed" si este llamado ganó el derecho a enviar. Si no:
        "applied" (ya se postuló), "sending" (otro envío en curso), "unknown"
        (un envío anterior se cortó sin saber si salió; reintentar exige force_retry)
        o "missing" (la vacante no existe).
        """
        now = datetime.now(timezone.utc)
        stale_cutoff = (now - timedelta(minutes=STALE_SEND_MINUTES)).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                UPDATE jobs SET send_state = 'sending', send_started_at = ?, send_key = ?
                WHERE id = ?
                  AND applied_at IS NULL
                  AND status != ?
                  AND (
                    send_state IS NULL
                    OR (? = 1 AND send_state = 'unknown')
                    OR (? = 1 AND send_state = 'sending' AND send_started_at < ?)
                  )
            """, (
                now.isoformat(), send_key, job_id, JobStatus.APPLIED.value,
                1 if force_retry else 0, 1 if force_retry else 0, stale_cutoff,
            ))
            await db.commit()
            if cursor.rowcount == 1:
                return "claimed"

            async with db.execute(
                "SELECT status, applied_at, send_state, send_started_at FROM jobs WHERE id = ?", (job_id,)
            ) as cur:
                row = await cur.fetchone()
        if not row:
            return "missing"
        status, applied_at, send_state, send_started_at = row
        if status == JobStatus.APPLIED.value or applied_at:
            return "applied"
        if send_state == "sending" and (send_started_at or "") >= stale_cutoff:
            return "sending"
        return "unknown"

    async def release_send(self, job_id: str) -> None:
        """Libera la marca de envío cuando el proveedor rechazó el envío (seguro que no salió)."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE jobs SET send_state = NULL, send_started_at = NULL WHERE id = ? AND send_state = 'sending'",
                (job_id,),
            )
            await db.commit()

    async def mark_send_unknown(self, job_id: str) -> None:
        """Deja constancia de que un envío se cortó y no sabemos si salió."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE jobs SET send_state = 'unknown' WHERE id = ? AND send_state = 'sending'", (job_id,))
            await db.commit()

    async def record_application(
        self, job_id: str, contact_email: str | None = None, contact_email_source: str | None = None
    ) -> None:
        """Marca una vacante como postulada con fecha y correo de envío."""
        now_iso = datetime.now(timezone.utc).isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE jobs SET
                    status = ?,
                    applied_at = ?,
                    send_state = NULL,
                    contact_email_source = CASE WHEN ? IS NOT NULL THEN COALESCE(?, contact_email_source) ELSE contact_email_source END,
                    contact_email = COALESCE(?, contact_email)
                WHERE id = ?
            """, (
                JobStatus.APPLIED.value, now_iso,
                contact_email, contact_email_source,
                contact_email, job_id,
            ))
            await db.commit()

    async def _remember_deleted(self, db: aiosqlite.Connection, where: str, params: tuple, reason: str) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        await db.execute(f"""
            INSERT OR IGNORE INTO seen_jobs (id, dedup_key, reason, created_at)
            SELECT id, dedup_key, ?, ? FROM jobs WHERE {where}
        """, (reason, now_iso, *params))

    async def delete_job(self, job_id: str) -> None:
        """Elimina una vacante y recuerda su id para que el escaneo no la traiga de vuelta."""
        async with aiosqlite.connect(self.db_path) as db:
            await self._remember_deleted(db, "id = ?", (job_id,), "deleted")
            await db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            await db.commit()

    async def discard_jobs(self, ids: list[str]) -> int:
        """Marca como descartadas (sin borrarlas) las vacantes indicadas. Nunca toca las postuladas."""
        if not ids:
            return 0
        async with aiosqlite.connect(self.db_path) as db:
            placeholders = ",".join("?" for _ in ids)
            cursor = await db.execute(
                f"UPDATE jobs SET status = ? WHERE id IN ({placeholders}) AND status NOT IN (?, ?) AND applied_at IS NULL",
                (JobStatus.DISCARDED.value, *ids, JobStatus.APPLIED.value, JobStatus.DISCARDED.value),
            )
            await db.commit()
            return cursor.rowcount

    async def delete_all_discarded_jobs(self) -> int:
        """Elimina las vacantes descartadas recordando sus ids para que no vuelvan como nuevas."""
        async with aiosqlite.connect(self.db_path) as db:
            await self._remember_deleted(db, "status = ?", (JobStatus.DISCARDED.value,), "deleted")
            cursor = await db.execute("DELETE FROM jobs WHERE status = ?", (JobStatus.DISCARDED.value,))
            await db.commit()
            return cursor.rowcount

    async def delete_all_jobs(self) -> int:
        """Elimina las vacantes no postuladas, recordando sus ids. Las postuladas son historial y quedan."""
        where = "status != ? AND applied_at IS NULL"
        params = (JobStatus.APPLIED.value,)
        async with aiosqlite.connect(self.db_path) as db:
            await self._remember_deleted(db, where, params, "deleted_all")
            cursor = await db.execute(f"DELETE FROM jobs WHERE {where}", params)
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

    async def ping(self) -> bool:
        """Comprueba que la base responde (para el healthcheck)."""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute("SELECT 1") as cursor:
                    return (await cursor.fetchone())[0] == 1
        except Exception as e:
            logger.error(f"La base SQLite no responde: {e}")
            return False

    def _row_to_job(self, row: aiosqlite.Row) -> JobOffer:
        tags = []
        if row["tags"]:
            try:
                tags = json.loads(row["tags"])
            except Exception:
                pass

        keys = row.keys() if hasattr(row, "keys") else []

        def col(name: str) -> Any:
            return row[name] if name in keys else None

        embedding = None
        if col("embedding"):
            try:
                embedding = json.loads(row["embedding"])
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
            tailored_cv=col("tailored_cv"),
            semantic_score=col("semantic_score"),
            embedding=embedding,
            hiring_manager_name=col("hiring_manager_name"),
            hiring_manager_title=col("hiring_manager_title"),
            hiring_manager_url=col("hiring_manager_url"),
            connection_note=col("connection_note"),
            contact_email=col("contact_email"),
            contact_email_source=col("contact_email_source"),
            applied_at=col("applied_at"),
            scored_by=col("scored_by"),
            send_state=col("send_state"),
            send_started_at=col("send_started_at"),
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
