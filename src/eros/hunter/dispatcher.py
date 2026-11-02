import asyncio
import base64
import email.utils
import json
import logging
import socket
import ssl
from datetime import datetime, timezone
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any
import httpx
from eros.config import get_settings
from eros.db.storage import JobStorage
from eros.hunter.cv_generator import CVGenerator
from eros.hunter.email_finder import (
    EMAIL_SOURCE_MANUAL,
    EMAIL_SOURCE_POSTING,
    EMAIL_SOURCE_UNKNOWN,
    VERIFIED_EMAIL_SOURCES,
    EmailFinder,
)
from eros.hunter.pitch import PitchGenerator
from eros.integrations.llm import LLMOutputError, LLMUnavailableError
from eros.models import JobOffer, JobStatus, ProfileContext, TailoredCV
from eros.security import cv_public_url

logger = logging.getLogger(__name__)

APPLY_CHANNELS = ("auto", "n8n", "smtp")

# Errores de SMTP que garantizan que el correo NO salió (se puede reintentar sin duplicar)
_SMTP_DEFINITE_FAILURES = (
    smtplib.SMTPAuthenticationError,
    smtplib.SMTPSenderRefused,
    smtplib.SMTPRecipientsRefused,
    smtplib.SMTPHeloError,
    smtplib.SMTPNotSupportedError,
    smtplib.SMTPConnectError,
    ConnectionRefusedError,
    socket.gaierror,
)


def _error(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error_code": code, "error": message, **extra}


class JobApplicationDispatcher:
    """Despachador de postulaciones por correo vía el webhook de postulaciones de n8n o SMTP.

    Garantías:
    - Solo usa correos con fuente real (aviso, sitio de la empresa, Hunter.io o escrito a mano).
    - Marca «enviando» de forma atómica antes de enviar: dos pedidos simultáneos no mandan dos correos.
    - Manda una clave de idempotencia estable por vacante (header Idempotency-Key) a n8n.
    - Sin proveedor configurado no registra la postulación ni responde ok.
    - Nunca usa el webhook de contenido para postulaciones.
    """

    def __init__(self, storage: JobStorage | None = None, engine: Any = None):
        self.storage = storage or JobStorage()
        self.settings = get_settings()
        self.engine = engine
        self.email_finder = EmailFinder(self.settings)
        self.cv_gen = CVGenerator()
        self.pitch_gen = PitchGenerator()

    async def _get_profile(self) -> ProfileContext:
        """Obtiene el perfil de Mateo desde la caché local o un valor base."""
        cached = await self.storage.get_profile_cache()
        if cached:
            return cached
        # Perfil base de respaldo si aún no sincronizó
        return ProfileContext(
            name=self.settings.candidate_name,
            role="Full Stack Software Engineer",
            tech_stack=["Vue 3", "Nuxt 4", "Node.js", "Express 5", "TypeScript", "PostgreSQL", "Docker", "Python", "FastAPI"],
            location="Neuquén / Río Negro, Patagonia Argentina",
        )

    def _is_english(self, job: JobOffer) -> bool:
        """Determina si la vacante está redactada en inglés."""
        text = f"{job.title} {job.description}".lower()
        es_keywords = [
            "requisitos", "experiencia", "conocimientos", "puesto", "remoto",
            "presencial", "desarrollador", "empresa", "trabajo", "habilidades",
            "argentina", "postularse", "ingeniero", "sistemas", "beneficios"
        ]
        return not any(w in text for w in es_keywords)

    def _default_subject(self, job: JobOffer, is_en: bool) -> str:
        if is_en:
            return f"Application: {job.title} — Mateo Sonzogni"
        return f"Postulación: {job.title} — Mateo Gabriel Sonzogni"

    @staticmethod
    def idempotency_key(job_id: str) -> str:
        """Clave estable por vacante: un mismo aviso se postula una sola vez."""
        return f"apply-{job_id}"

    async def get_application_preview(self, job_id: str) -> dict[str, Any]:
        """Genera una vista previa completa del asunto, cuerpo y enlaces de la postulación."""
        job = await self.storage.get_job(job_id)
        if not job:
            return {"ok": False, "error": f"Vacante {job_id} no encontrada"}

        # Si la vacante no tiene contact_email, buscar uno real (nunca adivinado) antes de responder
        if not job.contact_email:
            finder = getattr(self.engine, "email_finder", self.email_finder)
            if finder:
                found_email, source = await finder.resolve_contact_email(
                    company=job.company,
                    job_url=job.url,
                    recruiter_name=job.hiring_manager_name,
                    description=job.description,
                )
                if found_email:
                    job.contact_email = found_email
                    job.contact_email_source = source
                    await self.storage.update_job_contact_email(job.id, found_email, source=source)
                    logger.info(
                        f"Email resuelto al vuelo en preview para '{job.company}': {found_email} (fuente: {source})"
                    )

        profile = await self._get_profile()
        is_en = self._is_english(job)
        subject = self._default_subject(job, is_en)

        # Pitch: el guardado, uno nuevo de la IA, o (sin IA) una frase genérica marcada como plantilla
        pitch_content = ""
        pitch_source = "stored"
        if job.pitch_draft:
            try:
                pitch_json = json.loads(job.pitch_draft)
                pitch_content = pitch_json.get("cover_letter") or pitch_json.get("elevator_pitch", "")
            except Exception:
                pitch_content = job.pitch_draft
        else:
            try:
                draft = await self.pitch_gen.generate_pitch(job, profile)
                pitch_content = draft.cover_letter or draft.elevator_pitch
                pitch_source = "llm"
            except (LLMUnavailableError, LLMOutputError) as e:
                logger.warning(f"Sin pitch de IA para preview ({e}); usando plantilla genérica.")
                pitch_source = "template"
                pitch_content = (
                    "I am writing to apply for this position. "
                    "You can find my production work and the details of each project in my portfolio."
                    if is_en else
                    "Les escribo para postularme a la búsqueda. "
                    "En mi portafolio están los proyectos en producción y el detalle de cada uno."
                )

        cv_html_url = cv_public_url(job.id, "html") if job.tailored_cv else None
        cv_line_en = f"ATS Resume (Harvard Single-Page Format):\n{cv_html_url}\n\n" if cv_html_url else ""
        cv_line_es = f"Currículum Vitae (Formato Harvard ATS):\n{cv_html_url}\n\n" if cv_html_url else ""

        if is_en:
            body = (
                f"Dear Hiring Team at {job.company},\n\n"
                f"{pitch_content}\n\n"
                f"I have attached my tailored single-page ATS Resume (PDF) for your review.\n\n"
                f"Featured production work & engineering portfolio:\n"
                f"• Live Portfolio: {self.settings.candidate_portfolio_url}\n"
                f"• LinkedIn: {self.settings.candidate_linkedin_url}\n"
                f"• GitHub: {self.settings.candidate_github_url}\n\n"
                f"{cv_line_en}"
                f"I welcome the opportunity to discuss how my technical experience can add value to your team.\n\n"
                f"Best regards,\n\n"
                f"{self.settings.candidate_name}\n"
                f"Full Stack & Backend Software Engineer\n"
                f"{self.settings.smtp_from} | {self.settings.candidate_portfolio_url}"
            )
        else:
            body = (
                f"Estimado equipo de selección de {job.company},\n\n"
                f"{pitch_content}\n\n"
                f"Adjunto mi Currículum Vitae en formato Harvard ATS (PDF de 1 página) para su revisión.\n\n"
                f"Proyectos en producción y portafolio de ingeniería:\n"
                f"• Portafolio en vivo: {self.settings.candidate_portfolio_url}\n"
                f"• LinkedIn: {self.settings.candidate_linkedin_url}\n"
                f"• GitHub: {self.settings.candidate_github_url}\n\n"
                f"{cv_line_es}"
                f"Quedo a su disposición para coordinar una breve conversación técnica.\n\n"
                f"Saludos cordiales,\n\n"
                f"{self.settings.candidate_name}\n"
                f"Full Stack & Backend Software Engineer\n"
                f"{self.settings.smtp_from} | {self.settings.candidate_portfolio_url}"
            )

        source = job.contact_email_source if job.contact_email else None
        return {
            "ok": True,
            "job_id": job.id,
            "job_title": job.title,
            "company": job.company,
            "contact_email": job.contact_email or "",
            "contact_email_source": source,
            # Verificado = publicado en el aviso o en el sitio de la empresa, o escrito a mano.
            "contact_email_verified": source in VERIFIED_EMAIL_SOURCES,
            "is_email_extracted": source == EMAIL_SOURCE_POSTING,
            # Sin correo o con uno de origen desconocido, hay que escribir la dirección a mano.
            "requires_manual_email": not job.contact_email or source == EMAIL_SOURCE_UNKNOWN,
            "subject": subject,
            "body": body,
            "pitch_source": pitch_source,
            "cv_filename": "CV_Mateo_Sonzogni.pdf",
            "has_pdf_attachment": True,
            "cv_html_url": cv_html_url,
            "is_english": is_en,
            "status": job.status.value,
            "applied_at": job.applied_at,
            "send_state": job.send_state,
            "idempotency_key": self.idempotency_key(job.id),
        }

    def _pick_provider(self, channel: str) -> str | None:
        """Elige el proveedor real de envío. None si el canal pedido no está configurado."""
        app_webhook_url = (self.settings.n8n_application_webhook_url or "").strip()
        smtp_host = (self.settings.smtp_host or "").strip()
        if channel == "n8n":
            return "n8n" if app_webhook_url else None
        if channel == "smtp":
            return "smtp" if smtp_host else None
        if app_webhook_url:
            return "n8n"
        if smtp_host:
            return "smtp"
        return None

    async def _load_or_build_cv(self, job: JobOffer, profile: ProfileContext) -> TailoredCV:
        # El adjunto sigue siendo el CV de Eros (el contrato con el CV de la base del portfolio
        # está pendiente). Si la vacante no tiene uno adaptado, va el CV base escrito a mano.
        if job.tailored_cv:
            try:
                return TailoredCV.model_validate_json(job.tailored_cv)
            except Exception:
                pass
        tailored_cv = self.cv_gen._build_fallback_cv(profile, job)
        try:
            job.tailored_cv = json.dumps(tailored_cv.model_dump())
            await self.storage.save_job(job)
        except Exception as e:
            logger.warning(f"No se pudo persistir tailored_cv generado en storage: {e}")
        return tailored_cv

    async def dispatch_application(
        self,
        job_id: str,
        to_email: str | None = None,
        custom_subject: str | None = None,
        custom_body: str | None = None,
        channel: str = "auto",
        confirmed: bool = False,
        force_retry: bool = False,
    ) -> dict[str, Any]:
        """Despacha la postulación al destinatario vía n8n o SMTP.

        Devuelve ok=True solo si un proveedor aceptó el envío. Los errores llevan
        `error_code`: job_not_found, already_applied, send_in_progress,
        send_outcome_unknown, missing_email, unverified_email, invalid_email,
        requires_confirmation, invalid_channel, no_provider, provider_rejected.
        """
        job = await self.storage.get_job(job_id)
        if not job:
            return _error("job_not_found", f"Vacante {job_id} no encontrada")

        if job.status == JobStatus.APPLIED or job.applied_at:
            return _error(
                "already_applied",
                f"Postulación bloqueada: La vacante '{job.title}' ya fue postulada previamente ({job.applied_at or 'estado APPLIED'}). Evitando envío duplicado."
            )

        channel = (channel or "auto").strip().lower()
        if channel not in APPLY_CHANNELS:
            return _error("invalid_channel", f"Canal de envío inválido: '{channel}'. Opciones: {', '.join(APPLY_CHANNELS)}.")

        # 1. Destinatario y su fuente
        explicit = (to_email or "").strip()
        stored = (job.contact_email or "").strip()
        raw_recipient = explicit or stored
        if not raw_recipient:
            return _error("missing_email", "No hay un correo de contacto registrado para esta vacante. Por favor especificá uno.")

        _, parsed_addr = email.utils.parseaddr(raw_recipient)
        if not parsed_addr or "@" not in parsed_addr or "." not in parsed_addr.split("@")[-1]:
            return _error("invalid_email", f"El correo destinatario '{raw_recipient}' no tiene un formato válido.")
        recipient_email = parsed_addr.lower()

        # Una dirección escrita en el pedido (to_email) es manual aunque coincida con la guardada.
        if explicit:
            recipient_source = EMAIL_SOURCE_MANUAL
        else:
            recipient_source = job.contact_email_source or EMAIL_SOURCE_UNKNOWN

        if recipient_source == EMAIL_SOURCE_UNKNOWN:
            return _error(
                "unverified_email",
                f"No se sabe de dónde salió el correo '{recipient_email}'. Escribí la dirección a mano (to_email) para enviar.",
                contact_email_source=recipient_source,
            )

        # Un correo encontrado automáticamente (aviso, sitio, Hunter.io) se usa solo con confirmación explícita.
        if recipient_source != EMAIL_SOURCE_MANUAL and not confirmed:
            return _error(
                "requires_confirmation",
                f"El correo '{recipient_email}' se encontró automáticamente (fuente: {recipient_source}). Requiere confirmación explícita antes de enviar (confirmed=True).",
                requires_confirmation=True,
                contact_email_source=recipient_source,
            )

        is_previewed = bool(custom_subject and custom_body)
        if not confirmed and not is_previewed:
            return _error(
                "requires_confirmation",
                "El envío de postulación requiere confirmación explícita previa o previsualización del contenido.",
                requires_confirmation=True,
            )

        # 2. Proveedor real (sin proveedor no se registra nada)
        provider = self._pick_provider(channel)
        if provider is None:
            return _error(
                "no_provider",
                "No hay proveedor de envío configurado para este canal (N8N_APPLICATION_WEBHOOK_URL o SMTP_HOST). "
                "No se envió nada ni se marcó como postulada.",
            )

        # 3. Contenido (todo lo que puede fallar va antes de marcar «enviando»)
        is_en = self._is_english(job)
        preview = await self.get_application_preview(job_id)
        if not preview.get("ok"):
            return _error("job_not_found", preview.get("error", "Vacante no encontrada"))
        raw_subject = (custom_subject or preview.get("subject") or self._default_subject(job, is_en)).strip()
        final_subject = raw_subject.replace("\r", " ").replace("\n", " ").strip()
        final_body = (custom_body or preview.get("body", "")).strip()

        profile = await self._get_profile()
        tailored_cv = await self._load_or_build_cv(job, profile)
        cv_html_url = cv_public_url(job.id, "html")
        cv_plain_text = self.cv_gen.render_plain_text(tailored_cv)
        pdf_bytes = self.cv_gen.render_pdf(tailored_cv)
        pdf_base64 = base64.b64encode(pdf_bytes).decode("ascii") if pdf_bytes else ""
        idem_key = self.idempotency_key(job.id)

        # 4. Marca atómica «enviando»: si otro pedido ya la tomó, este no envía.
        claim = await self.storage.claim_send(job.id, idem_key, force_retry=force_retry)
        if claim != "claimed":
            messages = {
                "applied": ("already_applied", "La vacante ya fue postulada. Evitando envío duplicado."),
                "sending": ("send_in_progress", "Ya hay un envío en curso para esta vacante. Esperá el resultado antes de reintentar."),
                "unknown": (
                    "send_outcome_unknown",
                    "Un envío anterior se cortó y no sabemos si salió. Revisá «Enviados» en Gmail: si salió, "
                    "marcala como postulada; si no, reintentá con force_retry=true.",
                ),
                "missing": ("job_not_found", f"Vacante {job_id} no encontrada"),
            }
            code, msg = messages[claim]
            return _error(code, msg, send_state=claim)

        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            if provider == "n8n":
                outcome, detail = await self._send_via_n8n(job, recipient_email, final_subject, final_body,
                                                           pdf_base64, cv_plain_text, tailored_cv,
                                                           cv_html_url, idem_key, now_iso)
            else:
                outcome, detail = await self._send_via_smtp(recipient_email, final_subject, final_body, pdf_bytes)
        except Exception as e:  # Cualquier sorpresa después de empezar a enviar: no sabemos si salió
            logger.error(f"Error inesperado enviando la postulación de '{job.title}': {e}")
            outcome, detail = "unknown", str(e)

        if outcome == "sent":
            warning = None
            try:
                await self.storage.record_application(job.id, recipient_email, recipient_source)
            except Exception as e:
                # El correo salió: no se responde error. La marca «sending» pasa a «unknown»
                # sola a los 10 minutos y bloquea reenvíos; queda marcarla a mano como postulada.
                logger.error(f"Postulación enviada pero no se pudo registrar en la base ({job.id}): {e}")
                warning = "Se envió, pero no se pudo registrar como postulada. Marcala a mano."
            return {
                "warning": warning,
                "ok": True,
                "job_id": job.id,
                "dispatched_to": recipient_email,
                "contact_email_source": recipient_source,
                "provider": provider,
                "status": JobStatus.APPLIED.value,
                "applied_at": now_iso,
                "idempotency_key": idem_key,
                "message": f"Postulación enviada a {recipient_email} vía {provider.upper()}.",
            }

        if outcome == "failed":
            await self.storage.release_send(job.id)
            return _error("provider_rejected", f"No se envió: {detail}", provider=provider, send_state=None)

        await self.storage.mark_send_unknown(job.id)
        return _error(
            "send_outcome_unknown",
            f"El envío se cortó y no sabemos si salió ({detail}). Revisá «Enviados» antes de reintentar.",
            provider=provider,
            send_state="unknown",
        )

    async def _send_via_n8n(
        self,
        job: JobOffer,
        recipient_email: str,
        subject: str,
        body: str,
        pdf_base64: str,
        cv_plain_text: str,
        tailored_cv: TailoredCV,
        cv_html_url: str | None,
        idem_key: str,
        now_iso: str,
    ) -> tuple[str, str]:
        """Devuelve ("sent" | "failed" | "unknown", detalle)."""
        url = self.settings.n8n_application_webhook_url.strip()
        payload = {
            "event": "job.application",
            "idempotency_key": idem_key,
            "job_id": job.id,
            "job_title": job.title,
            "company": job.company,
            "job_url": job.url,
            "recipient_email": recipient_email,
            "subject": subject,
            "body": body,
            "candidate": {
                "name": self.settings.candidate_name,
                "email": self.settings.smtp_from,
                "portfolio": self.settings.candidate_portfolio_url,
                "linkedin": self.settings.candidate_linkedin_url,
                "github": self.settings.candidate_github_url,
            },
            "cv_filename": "CV_Mateo_Sonzogni.pdf",
            "cv_pdf_base64": pdf_base64,
            "cv_html_url": cv_html_url,
            "cv_text": cv_plain_text,
            "cv_data": tailored_cv.model_dump(),
            "applied_at": now_iso,
        }
        headers = {"Idempotency-Key": idem_key}
        if self.settings.n8n_webhook_secret:
            headers["X-N8N-Secret"] = self.settings.n8n_webhook_secret
        logger.info(f"Despachando postulación para '{job.title}' ({recipient_email}) al webhook de postulaciones de n8n.")
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            return "failed", f"no se pudo conectar con n8n: {e}"
        except httpx.HTTPError as e:
            return "unknown", f"n8n no respondió a tiempo: {e}"

        if resp.status_code in (200, 201, 202, 204):
            return "sent", f"HTTP {resp.status_code}"
        logger.error(f"n8n respondió HTTP {resp.status_code}: {resp.text[:200]}")
        if 400 <= resp.status_code < 500:
            return "failed", f"n8n rechazó el pedido (HTTP {resp.status_code}): {resp.text[:150]}"
        # Un 5xx puede llegar después de que el nodo de Gmail ya envió
        return "unknown", f"n8n respondió HTTP {resp.status_code}: {resp.text[:150]}"

    async def _send_via_smtp(self, recipient_email: str, subject: str, body: str, pdf_bytes: bytes | None) -> tuple[str, str]:
        """Devuelve ("sent" | "failed" | "unknown", detalle)."""
        def _send_sync_smtp():
            msg = MIMEMultipart()
            msg["Subject"] = subject
            msg["From"] = self.settings.smtp_from
            msg["To"] = recipient_email
            msg.attach(MIMEText(body, "plain", "utf-8"))

            if pdf_bytes:
                pdf_part = MIMEApplication(pdf_bytes, _subtype="pdf")
                pdf_part.add_header("Content-Disposition", "attachment", filename="CV_Mateo_Sonzogni.pdf")
                msg.attach(pdf_part)

            ssl_ctx = ssl.create_default_context()
            if self.settings.smtp_port == 465:
                with smtplib.SMTP_SSL(self.settings.smtp_host, self.settings.smtp_port, context=ssl_ctx, timeout=15) as server:
                    if self.settings.smtp_user and self.settings.smtp_pass:
                        server.login(self.settings.smtp_user, self.settings.smtp_pass)
                    server.sendmail(self.settings.smtp_from, [recipient_email], msg.as_string())
            else:
                with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=15) as server:
                    server.starttls(context=ssl_ctx)
                    if self.settings.smtp_user and self.settings.smtp_pass:
                        server.login(self.settings.smtp_user, self.settings.smtp_pass)
                    server.sendmail(self.settings.smtp_from, [recipient_email], msg.as_string())

        logger.info(f"Despachando postulación a {recipient_email} vía SMTP directo con adjunto PDF...")
        try:
            await asyncio.to_thread(_send_sync_smtp)
            return "sent", "SMTP"
        except _SMTP_DEFINITE_FAILURES as e:
            logger.error(f"SMTP rechazó el envío: {e}")
            return "failed", f"SMTP rechazó el envío: {e}"
        except Exception as e:
            logger.error(f"Falla de SMTP a mitad del envío: {e}")
            return "unknown", f"falla de SMTP a mitad del envío: {e}"
