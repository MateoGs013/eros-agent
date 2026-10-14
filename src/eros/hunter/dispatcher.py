import asyncio
import json
import logging
from datetime import datetime, timezone
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any
import httpx
from eros.config import get_settings
from eros.db.storage import JobStorage
from eros.hunter.cv_generator import CVGenerator
from eros.hunter.pitch import PitchGenerator
from eros.models import JobOffer, JobStatus, ProfileContext

logger = logging.getLogger(__name__)


class JobApplicationDispatcher:
    """Despachador automatizado de postulaciones laborales vía n8n, SMTP o webhook."""

    def __init__(self, storage: JobStorage | None = None):
        self.storage = storage or JobStorage()
        self.settings = get_settings()
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

        return {
            "ok": True,
            "job_id": job.id,
            "job_title": job.title,
            "company": job.company,
            "contact_email": job.contact_email or "",
            "subject": subject,
            "body": body,
            "cv_html_url": cv_html_url,
            "is_english": is_en,
            "status": job.status.value,
            "applied_at": job.applied_at,
        }

    async def dispatch_application(
        self,
        job_id: str,
        to_email: str | None = None,
        custom_subject: str | None = None,
        custom_body: str | None = None,
        channel: str = "auto"
    ) -> dict[str, Any]:
        """Despacha la postulación al destinatario vía n8n o SMTP."""
        job = await self.storage.get_job(job_id)
        if not job:
            return {"ok": False, "error": f"Vacante {job_id} no encontrada"}

        preview = await self.get_application_preview(job_id)
        if not preview.get("ok"):
            return preview

        recipient_email = (to_email or job.contact_email or "").strip().lower()
        if not recipient_email:
            return {
                "ok": False,
                "error": "No hay un correo de contacto registrado para esta vacante. Por favor especificá uno."
            }

        final_subject = custom_subject or preview["subject"]
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
            logger.info(f"Despachando postulación para '{job.title}' ({recipient_email}) vía SMTP directo...")
            try:
                def _send_sync_smtp():
                    msg = MIMEMultipart("alternative")
                    msg["Subject"] = final_subject
                    msg["From"] = self.settings.smtp_from
                    msg["To"] = recipient_email
                    msg.attach(MIMEText(final_body, "plain", "utf-8"))

                    with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=15) as server:
                        server.starttls()
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
