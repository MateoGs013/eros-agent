import asyncio
import html
import json
import logging
from typing import Any
import httpx
from eros.config import get_settings
from eros.hunter.engine import HunterEngine
from eros.models import JobOffer, JobStatus, MatchResult
from eros.content.models import (
    ContentGenerateRequest,
    ContentPostStatus,
    ContentPillar,
)
from eros.content.storage import ContentStorage
from eros.content.generator import ContentGenerator
from eros.content.dispatcher import ContentDispatcher

logger = logging.getLogger(__name__)


class TelegramBot:
    """Cliente y servidor de polling asíncrono para el bot privado de Telegram."""

    def __init__(self, engine: HunterEngine | None = None):
        self.settings = get_settings()
        self.engine = engine or HunterEngine()
        self.content_storage = ContentStorage()
        self.content_generator = ContentGenerator(storage=self.content_storage, engine=self.engine)
        self.content_dispatcher = ContentDispatcher(storage=self.content_storage)
        self.token = self.settings.telegram_bot_token
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        self.allowed_user_id = self.settings.telegram_allowed_user_id
        self.running = False

    @property
    def is_configured(self) -> bool:
        return bool(self.token)

    async def send_message(
        self,
        chat_id: int | str,
        text: str,
        reply_markup: dict[str, Any] | None = None,
        parse_mode: str = "HTML"
    ) -> bool:
        """Envía un mensaje de texto con soporte para formato y teclados interactivos."""
        if not self.is_configured:
            logger.warning(f"Telegram no configurado. Mensaje no enviado: {text[:60]}...")
            return False

        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": False
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                resp = await client.post(f"{self.base_url}/sendMessage", json=payload)
                if resp.status_code != 200:
                    logger.error(f"Telegram sendMessage error: {resp.status_code} - {resp.text}")
                    return False
                return True
            except Exception as e:
                logger.error(f"Error comunicando con Telegram: {e}")
                return False

    async def notify_match(self, job: JobOffer, match: MatchResult) -> bool:
        """Notifica proactivamente una vacante con alto puntaje de coincidencia."""
        if not self.allowed_user_id:
            logger.info(f"Nuevo match ({match.score}%): {job.title} en {job.company} (sin TELEGRAM_ALLOWED_USER_ID para notificar).")
            return False

        badge = "[MATCH ALTO]" if match.score >= 85 else "[MATCH]"
        salary_text = f"\n• <b>Salario:</b> {html.escape(job.salary)}" if job.salary else ""
        country_text = f"\n• <b>Ubicación:</b> {html.escape(job.country)}" if job.country else ""

        recruiter_text = ""
        hiring_name = job.hiring_manager_name or match.hiring_manager_name
        hiring_title = job.hiring_manager_title or match.hiring_manager_title
        if hiring_name:
            recruiter_text = f"\n• <b>Hiring Lead:</b> {html.escape(hiring_name)}"
            if hiring_title:
                recruiter_text += f" ({html.escape(hiring_title)})"

        email_text = f"\n• <b>Email Contacto:</b> <code>{html.escape(job.contact_email)}</code>" if job.contact_email else ""

        pros_text = ""
        if match.pros:
            pros_text = "\n\n<b>Puntos destacados:</b>\n" + "\n".join([f"• {html.escape(p)}" for p in match.pros[:3]])

        connection_note = job.connection_note or match.recruiter_note
        note_text = ""
        if connection_note:
            note_text = f"\n\n<b>Nota de conexión LinkedIn (&lt; 280 car.):</b>\n<code>{html.escape(connection_note)}</code>"

        msg = (
            f"<b>{badge} NUEVA VACANTE COMPATIBLE ({match.score}%)</b>\n\n"
            f"<b>Puesto:</b> {html.escape(job.title)}\n"
            f"<b>Empresa:</b> {html.escape(job.company)} ({html.escape(job.source.upper())})"
            f"{country_text}"
            f"{salary_text}"
            f"{recruiter_text}"
            f"{email_text}\n\n"
            f"<b>Análisis:</b> {html.escape(match.summary)}"
            f"{pros_text}"
            f"{note_text}"
        )

        first_row = [
            {"text": "Generar Pitch", "callback_data": f"pitch:{job.id}"},
            {"text": "Ver Oferta", "url": job.url}
        ]
        hiring_url = job.hiring_manager_url or match.hiring_manager_url
        if hiring_url:
            first_row.append({"text": "Ver Recruiter", "url": hiring_url})

        second_row = []
        if job.contact_email:
            second_row.append({"text": "Enviar CV por Email", "callback_data": f"apply_email:{job.id}"})
        second_row.append({"text": "Descartar", "callback_data": f"discard:{job.id}"})

        buttons = [first_row, second_row]
        keyboard = {"inline_keyboard": buttons}

        return await self.send_message(self.allowed_user_id, msg, reply_markup=keyboard)

    async def start_polling(self) -> None:
        """Inicia el bucle de long polling para recibir comandos de Mateo."""
        if not self.is_configured:
            logger.info("Bot de Telegram no iniciado: TELEGRAM_BOT_TOKEN no configurado en .env.")
            return

        logger.info("Iniciando bucle de polling de Telegram...")
        self.running = True
        offset = 0

        async with httpx.AsyncClient(timeout=35.0) as client:
            while self.running:
                try:
                    resp = await client.get(
                        f"{self.base_url}/getUpdates",
                        params={"offset": offset, "timeout": 25}
                    )
                    if resp.status_code != 200:
                        await asyncio.sleep(5)
                        continue

                    data = resp.json()
                    updates = data.get("result", [])
                    for update in updates:
                        offset = update.get("update_id", offset) + 1
                        await self._process_update(update)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Error en polling de Telegram: {e}")
                    await asyncio.sleep(3)

    async def _process_update(self, update: dict[str, Any]) -> None:
        """Procesa mensajes de texto y clics en botones interactivos."""
        # 1. Mensajes de texto normales
        if "message" in update:
            msg = update["message"]
            user_id = msg.get("from", {}).get("id")
            chat_id = msg.get("chat", {}).get("id")
            text = (msg.get("text") or "").strip()

            # Seguridad: responder exclusivamente al usuario autorizado configurado en TELEGRAM_ALLOWED_USER_ID
            if not self.allowed_user_id or user_id != self.allowed_user_id:
                logger.warning(f"Intento de acceso rechazado desde usuario ID {user_id}. TELEGRAM_ALLOWED_USER_ID={self.allowed_user_id}")
                if chat_id and not self.allowed_user_id:
                    await self._send_message(chat_id, f"Bot configurado en modo seguro. Para autorizar tu cuenta, definí TELEGRAM_ALLOWED_USER_ID={user_id} en tu archivo .env.")
                return

            await self._handle_command(chat_id, text, user_id)

        # 2. Clics en botones interactivos (Callback queries)
        elif "callback_query" in update:
            cb = update["callback_query"]
            cb_id = cb.get("id")
            user_id = cb.get("from", {}).get("id")
            chat_id = cb.get("message", {}).get("chat", {}).get("id")
            data = cb.get("data", "")

            if not self.allowed_user_id or user_id != self.allowed_user_id:
                logger.warning(f"Callback query no autorizado rechazado desde usuario ID {user_id}")
                return

            await self._handle_callback(cb_id, chat_id, data)

    async def _handle_command(self, chat_id: int | str, text: str, user_id: int) -> None:
        """Maneja comandos como /start, /post, /pendientes, /buscar, /status, /ofertas."""
        parts = text.split(maxsplit=1) if text else [""]
        cmd = parts[0].lower()
        args = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ["/start", "/ayuda"]:
            welcome = (
                "<b>[EROS CAREER OS] Panel de Control</b>\n\n"
                "Monitoreo de ofertas tech compatibles y generador de contenido técnico omnicanal.\n\n"
                "<b>Contenido y Marca:</b>\n"
                "• <code>/post &lt;tema&gt;</code> → Generar post omnicanal (LinkedIn, X, Dev.to y Carousel 5 slides).\n"
                "• <code>/pendientes</code> → Ver borradores pendientes de aprobación para n8n.\n\n"
                "<b>Búsqueda Laboral (Hunter):</b>\n"
                "• <code>/buscar</code> → Escanear ofertas ahora en todas las fuentes.\n"
                "• <code>/ofertas</code> → Ver mejores vacantes detectadas (≥ 75%).\n"
                "• <code>/status</code> → Resumen del sistema y base de datos.\n"
                "• <code>/perfil</code> → Ver datos sincronizados de tu portafolio.\n"
                "• <code>/sync</code> → Forzar actualización desde mateogs.tech."
            )
            await self.send_message(chat_id, welcome)

        elif cmd == "/post":
            topic = args or "Optimización de arquitectura frontend y rendimiento web con Nuxt 3 y TypeScript"
            await self.send_message(chat_id, f"<i>[GENERANDO] Procesando contenido técnico sobre:</i>\n<b>'{topic}'</b>...")

            try:
                post = await self.content_generator.generate_post(ContentGenerateRequest(topic=topic))
                carousel_url = f"https://eros.mateogs.tech/api/content/carousel/{post.id}/html"

                summary = (
                    f"<b>[NUEVO POST GENERADO] (Borrador)</b>\n\n"
                    f"• <b>Título:</b> {html.escape(post.title)}\n"
                    f"• <b>Pilar:</b> {html.escape(post.pillar.value)}\n"
                    f"• <b>Tweets:</b> {len(post.twitter_thread)} tweets preparados\n"
                    f"• <b>Slides:</b> {len(post.carousel_slides)} diapositivas listas\n\n"
                    f"<b>Hook LinkedIn:</b>\n<i>{html.escape(post.hook)}</i>\n\n"
                    f"<b>Primer comentario:</b>\n<code>{html.escape(post.first_comment)}</code>"
                )

                buttons = [
                    [
                        {"text": "Aprobar y Despachar a n8n", "callback_data": f"pub_post:{post.id}"},
                    ],
                    [
                        {"text": "Ver Carousel Web", "url": carousel_url},
                        {"text": "Descartar", "callback_data": f"del_post:{post.id}"}
                    ]
                ]

                await self.send_message(chat_id, summary, reply_markup={"inline_keyboard": buttons})
            except Exception as e:
                logger.error(f"Error generando post en Telegram: {e}")
                await self.send_message(chat_id, f"[ERROR] No se pudo generar el post: {html.escape(str(e))}")

        elif cmd == "/pendientes":
            drafts = await self.content_storage.list_posts(status=ContentPostStatus.DRAFT, limit=5)
            if not drafts:
                await self.send_message(chat_id, "No hay borradores de contenido pendientes. Podés crear uno con <code>/post &lt;tema&gt;</code>.")
                return

            await self.send_message(chat_id, f"<b>Top {len(drafts)} publicaciones en borrador pendientes:</b>")
            for post in drafts:
                carousel_url = f"https://eros.mateogs.tech/api/content/carousel/{post.id}/html"
                buttons = [
                    [
                        {"text": "Aprobar n8n", "callback_data": f"pub_post:{post.id}"},
                        {"text": "Ver Carousel", "url": carousel_url},
                        {"text": "Descartar", "callback_data": f"del_post:{post.id}"}
                    ]
                ]
                card = f"• <b>{html.escape(post.title)}</b> ({html.escape(post.pillar.value)})\n<i>{html.escape(post.hook[:120])}...</i>"
                await self.send_message(chat_id, card, reply_markup={"inline_keyboard": buttons})

        elif cmd == "/status":
            unseen = await self.engine.storage.list_unseen_jobs()
            matched = await self.engine.storage.list_matched_jobs(min_score=70)
            drafts = await self.content_storage.list_posts(status=ContentPostStatus.DRAFT)
            published = await self.content_storage.list_posts(status=ContentPostStatus.PUBLISHED)
            status_text = (
                "<b>[ESTADO DE EROS AGENT]</b>\n\n"
                f"• <b>Vacantes pendientes:</b> {len(unseen)}\n"
                f"• <b>Vacantes con match ≥ 70%:</b> {len(matched)}\n"
                f"• <b>Posts en borrador:</b> {len(drafts)}\n"
                f"• <b>Posts publicados:</b> {len(published)}\n"
                f"• <b>n8n Webhook:</b> {'Configurado' if self.settings.n8n_webhook_url else 'Pendiente'}\n"
                f"• <b>Tu User ID:</b> <code>{user_id}</code>\n"
            )
            await self.send_message(chat_id, status_text)

        elif cmd == "/perfil":
            profile = await self.engine.get_active_profile()
            perfil_text = (
                f"<b>[PERFIL ACTIVO EN MEMORIA]</b>\n\n"
                f"• <b>Nombre:</b> {profile.name}\n"
                f"• <b>Rol:</b> {profile.role}\n"
                f"• <b>Ubicación:</b> {profile.location} ({profile.timezone})\n"
                f"• <b>Inglés:</b> {profile.languages}\n"
                f"• <b>Stack:</b> {', '.join(profile.tech_stack[:8])}\n"
                f"• <b>Proyectos cargados:</b> {len(profile.projects)}\n"
                f"• <i>Sincronizado desde https://api.mateogs.tech/api</i>"
            )
            await self.send_message(chat_id, perfil_text)

        elif cmd == "/sync":
            await self.send_message(chat_id, "<i>[SINCRONIZANDO] Obteniendo datos desde mateogs.tech...</i>")
            profile = await self.engine.sync_profile()
            await self.send_message(
                chat_id,
                f"<b>[OK] Sincronización completada:</b>\n{len(profile.projects)} proyectos y {len(profile.tech_stack)} tecnologías cargadas."
            )

        elif cmd == "/buscar":
            await self.send_message(chat_id, "<i>[BUSCANDO] Consultando Get on Board, RemoteOK y Hacker News...</i>")
            scan_res = await self.engine.run_scan()
            eval_res = await self.engine.evaluate_pending_jobs(limit=10)

            high_matches = [m for m in eval_res if m[1].score >= self.settings.match_min_score]
            msg = (
                f"<b>[FINALIZADO] Resultados de búsqueda:</b>\n"
                f"• Nuevas ofertas encontradas: {scan_res['new_jobs']}\n"
                f"• Evaluadas en este lote: {len(eval_res)}\n"
                f"• Matches destacados (≥{self.settings.match_min_score}%): {len(high_matches)}"
            )
            await self.send_message(chat_id, msg)

            for job, match in high_matches:
                await self.notify_match(job, match)

        elif cmd == "/ofertas":
            matched = await self.engine.storage.list_matched_jobs(min_score=75, limit=5)
            if not matched:
                await self.send_message(chat_id, "No hay ofertas pendientes con score ≥ 75%. Probá ejecutar <code>/buscar</code>.")
                return

            await self.send_message(chat_id, f"<b>Top {len(matched)} ofertas más compatibles:</b>")
            for job in matched:
                first_row = [
                    {"text": "Pitch", "callback_data": f"pitch:{job.id}"},
                    {"text": "Ver Oferta", "url": job.url}
                ]
                if job.hiring_manager_url:
                    first_row.append({"text": "Recruiter", "url": job.hiring_manager_url})

                buttons = [
                    first_row,
                    [{"text": "Descartar", "callback_data": f"discard:{job.id}"}]
                ]

                recruiter_line = ""
                if job.hiring_manager_name:
                    recruiter_line = f"\n• <b>Lead:</b> {html.escape(job.hiring_manager_name)}"
                    if job.hiring_manager_title:
                        recruiter_line += f" ({html.escape(job.hiring_manager_title)})"

                note_line = ""
                if job.connection_note:
                    note_line = f"\n• <b>Nota de Conexión:</b>\n<code>{html.escape(job.connection_note)}</code>"

                card = f"• <b>Match {job.match_score}%</b>: {html.escape(job.title)} en <b>{html.escape(job.company)}</b> ({html.escape(job.source.upper())}){recruiter_line}{note_line}"
                await self.send_message(chat_id, card, reply_markup={"inline_keyboard": buttons})

    async def _handle_callback(self, cb_id: str, chat_id: int | str, data: str) -> None:
        """Maneja clics en botones inline como 'pitch:<id>', 'discard:<id>', 'pub_post:<id>'."""
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                await client.post(f"{self.base_url}/answerCallbackQuery", json={"callback_query_id": cb_id})
            except Exception:
                pass

        if data.startswith("pub_post:"):
            post_id = data.split("pub_post:")[1]
            await self.send_message(chat_id, f"<i>[DESPACHO] Aprobando y enviando post {post_id} a n8n...</i>")
            res = await self.content_dispatcher.publish_post(post_id)
            if res.get("ok"):
                status_note = "Enviado a n8n para distribución automática." if res.get("status") == "published" else res.get("message")
                await self.send_message(chat_id, f"<b>[APROBADO] Publicación procesada con éxito:</b>\n{status_note}")
            else:
                await self.send_message(chat_id, f"<b>[ERROR] Falla en despacho:</b> {html.escape(str(res.get('error')))}")

        elif data.startswith("del_post:"):
            post_id = data.split("del_post:")[1]
            await self.content_storage.update_status(post_id, ContentPostStatus.REJECTED)
            await self.send_message(chat_id, f"Publicación {post_id} descartada.")

        elif data.startswith("pitch:"):
            job_id = data.split("pitch:")[1]
            await self.send_message(chat_id, "<i>[PITCH] Redactando propuesta con tus proyectos y métricas...</i>")
            pitch = await self.engine.generate_pitch_for_job(job_id)
            if not pitch:
                await self.send_message(chat_id, "No se pudo recuperar la oferta para redactar el pitch.")
                return

            pitch_msg = (
                f"<b>[PITCH PERSONALIZADO PARA LA VACANTE]</b>\n\n"
                f"• <b>Asunto sugerido:</b>\n<code>{html.escape(pitch.subject_or_hook)}</code>\n\n"
                f"• <b>Propuesta directa:</b>\n<pre>{html.escape(pitch.elevator_pitch)}</pre>\n\n"
                f"• <b>Proyectos citados:</b> {html.escape(', '.join(pitch.suggested_projects))}"
            )
            await self.send_message(chat_id, pitch_msg)

        elif data.startswith("discard:"):
            job_id = data.split("discard:")[1]
            await self.engine.storage.update_job_status(job_id, JobStatus.DISCARDED)
            await self.send_message(chat_id, "Vacante descartada de la lista.")

        elif data.startswith("apply_email:"):
            job_id = data.split("apply_email:")[1]
            job = await self.engine.storage.get_job(job_id)
            if not job:
                await self.send_message(chat_id, "Vacante no encontrada.")
                return

            # Bloquear postulación si ya fue enviada
            if job.status == JobStatus.APPLIED or job.applied_at:
                await self.send_message(
                    chat_id,
                    f"<b>[POSTULACIÓN BLOQUEADA]</b>\nLa vacante '{html.escape(job.title)}' ya fue enviada previamente ({job.applied_at or 'estado APPLIED'}). Evitando envío duplicado."
                )
                return

            # Generar previsualización y requerir confirmación explícita
            preview = await self.engine.app_dispatcher.get_application_preview(job_id)
            if not preview.get("ok"):
                await self.send_message(chat_id, f"<b>[ERROR EN PREVIEW]</b>\n{html.escape(str(preview.get('error')))}")
                return

            email_dest = preview.get("contact_email") or "No especificado"
            is_unverified = not preview.get("contact_email_verified", True)
            warn_unverified = (
                "\n⚠️ <i>ATENCIÓN: El correo fue extraído de la descripción y no está verificado manualmente.</i>\n"
                if is_unverified else ""
            )

            preview_msg = (
                f"<b>[CONFIRMACIÓN DE POSTULACIÓN]</b>\n\n"
                f"• <b>Puesto:</b> {html.escape(job.title)}\n"
                f"• <b>Empresa:</b> {html.escape(job.company)}\n"
                f"• <b>Destinatario:</b> <code>{html.escape(email_dest)}</code>"
                f"{warn_unverified}\n"
                f"• <b>Asunto:</b> <code>{html.escape(preview.get('subject', ''))}</code>\n"
                f"• <b>Adjunto:</b> CV_Mateo_Sonzogni.pdf (Harvard ATS 1 Página)\n\n"
                f"<b>Cuerpo del correo (extracto):</b>\n"
                f"<pre>{html.escape(preview.get('body', '')[:400])}...</pre>\n\n"
                f"¿Deseas enviar la postulación ahora?"
            )
            buttons = [
                [
                    {"text": "Confirmar y Enviar", "callback_data": f"confirm_apply:{job_id}"},
                    {"text": "Cancelar", "callback_data": f"cancel_apply:{job_id}"}
                ]
            ]
            await self.send_message(chat_id, preview_msg, reply_markup={"inline_keyboard": buttons})

        elif data.startswith("confirm_apply:"):
            job_id = data.split("confirm_apply:")[1]
            job = await self.engine.storage.get_job(job_id)
            if not job:
                await self.send_message(chat_id, "Vacante no encontrada.")
                return

            if job.status == JobStatus.APPLIED or job.applied_at:
                await self.send_message(
                    chat_id,
                    f"<b>[POSTULACIÓN BLOQUEADA]</b> La vacante '{html.escape(job.title)}' ya fue enviada previamente ({job.applied_at or 'estado APPLIED'})."
                )
                return

            await self.send_message(chat_id, "<i>[POSTULANDO] Despachando postulación con CV Harvard ATS y pitch personalizado...</i>")
            res = await self.engine.app_dispatcher.dispatch_application(job_id=job_id, confirmed=True)
            if res.get("ok"):
                msg = (
                    f"<b>[POSTULACIÓN ENVIADA CON ÉXITO]</b>\n\n"
                    f"• <b>Destinatario:</b> <code>{html.escape(str(res.get('dispatched_to')))}</code>\n"
                    f"• <b>Canal:</b> {html.escape(str(res.get('provider', '')).upper())}\n"
                    f"• <b>Estado:</b> Vacante registrada como POSTULADA en base de datos."
                )
                await self.send_message(chat_id, msg)
            else:
                await self.send_message(chat_id, f"<b>[ERROR EN POSTULACIÓN]</b>\n{html.escape(str(res.get('error')))}")

        elif data.startswith("cancel_apply:"):
            await self.send_message(chat_id, "Postulación cancelada.")
