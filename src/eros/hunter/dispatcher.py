import asyncio
import base64
import email.utils
import json
import logging
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
from eros.hunter.email_finder import EmailFinder
from eros.hunter.pitch import PitchGenerator
from eros.models import JobOffer, JobStatus, ProfileContext

logger = logging.getLogger(__name__)


class JobApplicationDispatcher:
    """Despachador automatizado de postulaciones laborales vía n8n, SMTP o webhook."""

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

    async def get_application_preview(self, job_id: str) -> dict[str, Any]:
        """Genera una vista previa completa del asunto, cuerpo y enlaces de la postulación."""
        job = await self.storage.get_job(job_id)
        if not job:
            return {"ok": False, "error": f"Vacante {job_id} no encontrada"}

        # Si la vacante no tiene contact_email, intentar resolverlo al vuelo antes de responder
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
                    await self.storage.update_job_contact_email(job.id, found_email)
                    logger.info(
                        f"Email resuelto al vuelo en preview para '{job.company}': {found_email} (fuente: {source})"
                    )

        profile = await self._get_profile()
        is_en = self._is_english(job)

        # 1. Asunto predeterminado
        if is_en:
            subject = f"Application: {job.title} — Mateo Sonzogni"
        else:
            subject = f"Postulación: {job.title} — Mateo Gabriel Sonzogni"

        # 2. Obtener o generar Pitch / Elevator pitch
        pitch_content = ""
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
            except Exception as e:
                logger.warning(f"Error generando pitch para preview: {e}")
                pitch_content = (
                    "I am writing to express my strong interest in the open position. "
                    "My background in full stack web development and robust backend systems "
                    "aligns closely with your technical requirements."
                    if is_en else
                    "Me pongo en contacto para presentar mi postulación a la búsqueda. "
                    "Mi perfil en desarrollo full stack y arquitectura backend en producción "
                    "se alinea de forma directa con los desafíos del puesto."
                )

        cv_html_url = f"https://eros.mateogs.tech/api/jobs/{job.id}/cv/html"

        # 3. Construir cuerpo profesional de correo
        if is_en:
            body = (
                f"Dear Hiring Team at {job.company},\n\n"
                f"{pitch_content}\n\n"
                f"I have attached my tailored single-page ATS Resume (PDF) for your review.\n\n"
                f"Featured production work & engineering portfolio:\n"
                f"• Live Portfolio: {self.settings.candidate_portfolio_url}\n"
                f"• LinkedIn: {self.settings.candidate_linkedin_url}\n"
                f"• GitHub: {self.settings.candidate_github_url}\n\n"
                f"ATS Resume (Harvard Single-Page Format):\n"
                f"{cv_html_url}\n\n"
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
                f"Currículum Vitae (Formato Harvard ATS):\n"
                f"{cv_html_url}\n\n"
                f"Quedo a su disposición para coordinar una breve conversación técnica.\n\n"
                f"Saludos cordiales,\n\n"
                f"{self.settings.candidate_name}\n"
                f"Full Stack & Backend Software Engineer\n"
                f"{self.settings.smtp_from} | {self.settings.candidate_portfolio_url}"
            )

        is_extracted = bool(
            job.contact_email
            and job.description
            and job.contact_email.lower() in job.description.lower()
        )

        return {
            "ok": True,
            "job_id": job.id,
            "job_title": job.title,
            "company": job.company,
            "contact_email": job.contact_email or "",
            "subject": subject,
            "body": body,
            "cv_filename": "CV_Mateo_Sonzogni.pdf",
            "has_pdf_attachment": True,
            "cv_html_url": cv_html_url,
            "is_english": is_en,
            "status": job.status.value,
            "applied_at": job.applied_at,
            "contact_email_verified": not is_extracted,
            "is_email_extracted": is_extracted,
        }

    async def dispatch_application(
        self,
        job_id: str,
        to_email: str | None = None,
        custom_subject: str | None = None,
        custom_body: str | None = None,
        channel: str = "auto",
        confirmed: bool = False,
    ) -> dict[str, Any]:
        """Despacha la postulación al destinatario vía n8n o SMTP."""
        job = await self.storage.get_job(job_id)
        if not job:
            return {"ok": False, "error": f"Vacante {job_id} no encontrada"}

        # 1. Bloquear postulación si ya está aplicada o tiene applied_at (evitar duplicados)
        if job.status == JobStatus.APPLIED or job.applied_at:
            return {
                "ok": False,
                "error": f"Postulación bloqueada: La vacante '{job.title}' ya fue postulada previamente ({job.applied_at or 'estado APPLIED'}). Evitando envío duplicado."
            }

        preview = await self.get_application_preview(job_id)
        if not preview.get("ok"):
            return preview

        raw_recipient = (to_email or job.contact_email or "").strip()
        if not raw_recipient:
            return {
                "ok": False,
                "error": "No hay un correo de contacto registrado para esta vacante. Por favor especificá uno."
            }

        # 2. Validar destinatario con email.utils.parseaddr
        _, parsed_addr = email.utils.parseaddr(raw_recipient)
        if not parsed_addr or "@" not in parsed_addr or "." not in parsed_addr.split("@")[-1]:
            return {
                "ok": False,
                "error": f"El correo destinatario '{raw_recipient}' no tiene un formato válido."
            }
        recipient_email = parsed_addr.lower()

        # 3. Marcar el email extraído de la descripción como no verificado y requerir confirmación
        is_extracted = bool(
            not to_email
            and job.contact_email
            and job.description
            and job.contact_email.lower() in job.description.lower()
        )
        if is_extracted and not confirmed:
            return {
                "ok": False,
                "requires_confirmation": True,
                "error": f"El correo '{recipient_email}' fue extraído automáticamente de la descripción y no está verificado. Requiere confirmación explícita antes de enviar (confirmed=True)."
            }

        # 4. Requerir confirmación explícita si no está previsualizado
        is_previewed = bool(custom_subject and custom_body)
        if not confirmed and not is_previewed:
            return {
                "ok": False,
                "requires_confirmation": True,
                "error": "El envío de postulación requiere confirmación explícita previa o previsualización del contenido."
            }

        # 5. Sanitizar final_subject quitando \r\n
        raw_subject = custom_subject or preview["subject"]
        final_subject = raw_subject.replace("\r", " ").replace("\n", " ").strip()
        final_body = custom_body or preview["body"]
        now_iso = datetime.now(timezone.utc).isoformat()

        # Generar o cargar CV en texto plano para el payload
        profile = await self._get_profile()
        tailored_cv = None
        if job.tailored_cv:
            try:
                from eros.models import TailoredCV
                tailored_cv = TailoredCV.model_validate_json(job.tailored_cv)
            except Exception:
                pass
        if not tailored_cv:
            tailored_cv = self.cv_gen._build_fallback_cv(profile, job)

        cv_plain_text = self.cv_gen.render_plain_text(tailored_cv)
        pdf_bytes = self.cv_gen.render_pdf(tailored_cv)
        pdf_base64 = base64.b64encode(pdf_bytes).decode("ascii") if pdf_bytes else ""

        payload_n8n = {
            "event": "job.application",
            "job_id": job.id,
            "job_title": job.title,
            "company": job.company,
            "job_url": job.url,
            "recipient_email": recipient_email,
            "subject": final_subject,
            "body": final_body,
            "candidate": {
                "name": self.settings.candidate_name,
                "email": self.settings.smtp_from,
                "portfolio": self.settings.candidate_portfolio_url,
                "linkedin": self.settings.candidate_linkedin_url,
                "github": self.settings.candidate_github_url,
            },
            "cv_filename": "CV_Mateo_Sonzogni.pdf",
            "cv_pdf_base64": pdf_base64,
            "cv_html_url": preview["cv_html_url"],
            "cv_text": cv_plain_text,
            "cv_data": tailored_cv.model_dump(),
            "applied_at": now_iso,
        }

        webhook_url = (self.settings.n8n_application_webhook_url or self.settings.n8n_webhook_url).strip()
        provider = "local"

        # 1. Opción A: Webhook de n8n
        if channel in ["auto", "n8n"] and webhook_url:
            logger.info(f"Despachando postulación para '{job.title}' ({recipient_email}) a n8n: {webhook_url}")
            async with httpx.AsyncClient(timeout=25.0) as client:
                try:
                    resp = await client.post(webhook_url, json=payload_n8n)
                    if resp.status_code in [200, 201, 202, 204]:
                        provider = "n8n"
                    else:
                        logger.error(f"n8n respondió HTTP {resp.status_code}: {resp.text[:200]}")
                        return {
                            "ok": False,
                            "error": f"Fallo al despachar en n8n (HTTP {resp.status_code}): {resp.text[:150]}"
                        }
                except Exception as e:
                    logger.error(f"Error de conexión con n8n al postular: {e}")
                    return {"ok": False, "error": f"Error de red al conectar con n8n: {str(e)}"}

        # 2. Opción B: SMTP Directo
        elif channel in ["auto", "smtp"] and self.settings.smtp_host:
            logger.info(f"Despachando postulación para '{job.title}' ({recipient_email}) vía SMTP directo con adjunto PDF...")
            try:
                def _send_sync_smtp():
                    msg = MIMEMultipart()
                    msg["Subject"] = final_subject
                    msg["From"] = self.settings.smtp_from
                    msg["To"] = recipient_email
                    msg.attach(MIMEText(final_body, "plain", "utf-8"))

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

                await asyncio.to_thread(_send_sync_smtp)
                provider = "smtp"
            except Exception as e:
                logger.error(f"Falla al enviar correo vía SMTP: {e}")
                return {"ok": False, "error": f"Falla de conexión SMTP: {str(e)}"}

        else:
            # Modo local / simulación si no hay proveedores de envío activos
            logger.info(
                f"Modo local: Ni N8N_APPLICATION_WEBHOOK_URL ni SMTP_HOST configurados. "
                f"Registrando postulación en base de datos para '{job.title}' ({recipient_email})."
            )
            provider = "local_registered"

        # Registrar la postulación en SQLite
        await self.storage.record_application(job.id, recipient_email)

        return {
            "ok": True,
            "job_id": job.id,
            "dispatched_to": recipient_email,
            "provider": provider,
            "status": JobStatus.APPLIED.value,
            "applied_at": now_iso,
            "message": (
                f"Postulación enviada exitosamente a {recipient_email} vía {provider.upper()}."
                if provider != "local_registered" else
                f"Postulación registrada en base de datos para {recipient_email}. "
                "Para envío de correos reales, configurá N8N_APPLICATION_WEBHOOK_URL o credenciales SMTP en .env."
            )
        }
