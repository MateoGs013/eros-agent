import asyncio
import json
import logging
from typing import Any
import httpx
from eros.config import get_settings
from eros.hunter.engine import HunterEngine
from eros.models import JobOffer, JobStatus, MatchResult

logger = logging.getLogger(__name__)


class TelegramBot:
    """Cliente y servidor de polling asíncrono para el bot privado de Telegram."""

    def __init__(self, engine: HunterEngine | None = None):
        self.settings = get_settings()
        self.engine = engine or HunterEngine()
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

        emoji_verdict = "🔥" if match.score >= 85 else "🎯"
        salary_text = f"\n💰 <b>Salario:</b> {job.salary}" if job.salary else ""
        country_text = f"\n🌍 <b>Ubicación:</b> {job.country}" if job.country else ""
        
        pros_text = ""
        if match.pros:
            pros_text = "\n\n<b>Puntos destacados:</b>\n" + "\n".join([f"• {p}" for p in match.pros[:3]])

        msg = (
            f"{emoji_verdict} <b>NUEVA VACANTE COMPATIBLE ({match.score}%)</b>\n\n"
            f"💼 <b>{job.title}</b>\n"
            f"🏢 <b>{job.company}</b> ({job.source.upper()})"
            f"{country_text}"
            f"{salary_text}\n\n"
            f"📝 <b>Análisis:</b> {match.summary}"
            f"{pros_text}"
        )

        buttons = [
            [
                {"text": "✉️ Generar Pitch / Carta", "callback_data": f"pitch:{job.id}"},
                {"text": "🔗 Ver Oferta", "url": job.url}
            ],
            [
                {"text": "❌ Descartar", "callback_data": f"discard:{job.id}"}
            ]
        ]
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

            # Seguridad: responder solo a Mateo si está configurado
            if self.allowed_user_id and user_id != self.allowed_user_id:
                logger.warning(f"Intento de acceso no autorizado desde usuario ID {user_id}")
                return

            await self._handle_command(chat_id, text, user_id)

        # 2. Clics en botones interactivos (Callback queries)
        elif "callback_query" in update:
            cb = update["callback_query"]
            cb_id = cb.get("id")
            user_id = cb.get("from", {}).get("id")
            chat_id = cb.get("message", {}).get("chat", {}).get("id")
            data = cb.get("data", "")

            if self.allowed_user_id and user_id != self.allowed_user_id:
                return

            await self._handle_callback(cb_id, chat_id, data)

    async def _handle_command(self, chat_id: int | str, text: str, user_id: int) -> None:
        """Maneja comandos como /start, /buscar, /status, /ofertas."""
        cmd = text.split()[0].lower() if text else ""

        if cmd in ["/start", "/ayuda"]:
            welcome = (
                "👋 <b>Hola Mateo, soy Eros Agent.</b>\n\n"
                "Estoy monitoreando activamente ofertas laborales conectadas con tu portafolio en <code>api.mateogs.tech</code>.\n\n"
                "<b>Comandos disponibles:</b>\n"
                "• <code>/buscar</code> — Escanear ofertas ahora en todas las fuentes.\n"
                "• <code>/ofertas</code> — Ver las mejores vacantes detectadas.\n"
                "• <code>/status</code> — Resumen de base de datos y estado.\n"
                "• <code>/perfil</code> — Ver datos sincronizados de tu portafolio.\n"
                "• <code>/sync</code> — Forzar actualización de tu CV y proyectos desde la API."
            )
            await self.send_message(chat_id, welcome)

        elif cmd == "/status":
            unseen = await self.engine.storage.list_unseen_jobs()
            matched = await self.engine.storage.list_matched_jobs(min_score=70)
            status_text = (
                "📊 <b>ESTADO DE EROS AGENT</b>\n\n"
                f"• <b>Vacantes pendientes de evaluar:</b> {len(unseen)}\n"
                f"• <b>Vacantes con match ≥ 70%:</b> {len(matched)}\n"
                f"• <b>Fuentes activas:</b> Get on Board, RemoteOK, Hacker News\n"
                f"• <b>Tu User ID:</b> <code>{user_id}</code>\n"
            )
            await self.send_message(chat_id, status_text)

        elif cmd == "/perfil":
            profile = await self.engine.get_active_profile()
            perfil_text = (
                f"👤 <b>PERFIL ACTIVO EN MEMORIA</b>\n\n"
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
            await self.send_message(chat_id, "⏳ Sincronizando datos desde tu API en mateogs.tech...")
            profile = await self.engine.sync_profile()
            await self.send_message(
                chat_id,
                f"✅ <b>Sincronización completada:</b>\n{len(profile.projects)} proyectos y {len(profile.tech_stack)} tecnologías cargadas."
            )

        elif cmd == "/buscar":
            await self.send_message(chat_id, "🔎 <b>Iniciando búsqueda en Get on Board, RemoteOK y Hacker News...</b>")
            scan_res = await self.engine.run_scan()
            eval_res = await self.engine.evaluate_pending_jobs(limit=10)

            high_matches = [m for m in eval_res if m[1].score >= self.settings.match_min_score]
            msg = (
                f"🏁 <b>Búsqueda finalizada:</b>\n"
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

            await self.send_message(chat_id, f"📋 <b>Top {len(matched)} ofertas más compatibles:</b>")
            for job in matched:
                buttons = [
                    [
                        {"text": "✉️ Pitch", "callback_data": f"pitch:{job.id}"},
                        {"text": "🔗 Ver", "url": job.url},
                        {"text": "❌", "callback_data": f"discard:{job.id}"}
                    ]
                ]
                card = f"🎯 <b>Match {job.match_score}%</b>: {job.title} en <b>{job.company}</b> ({job.source.upper()})"
                await self.send_message(chat_id, card, reply_markup={"inline_keyboard": buttons})

    async def _handle_callback(self, cb_id: str, chat_id: int | str, data: str) -> None:
        """Maneja clics en botones inline como 'pitch:<id>' o 'discard:<id>'."""
        # Responder a Telegram para apagar el reloj de carga en el botón
        async with httpx.AsyncClient(timeout=5.0) as client:
            try:
                await client.post(f"{self.base_url}/answerCallbackQuery", json={"callback_query_id": cb_id})
            except Exception:
                pass

        if data.startswith("pitch:"):
            job_id = data.split("pitch:")[1]
            await self.send_message(chat_id, "✍️ <i>Generando pitch a medida con tus proyectos y métricas...</i>")
            pitch = await self.engine.generate_pitch_for_job(job_id)
            if not pitch:
                await self.send_message(chat_id, "No se pudo recuperar la oferta para redactar el pitch.")
                return

            pitch_msg = (
                f"✉️ <b>PITCH PERSONALIZADO PARA LA VACANTE</b>\n\n"
                f"📌 <b>Asunto / Asunto sugerido:</b>\n<code>{pitch.subject_or_hook}</code>\n\n"
                f"💬 <b>Propuesta directa:</b>\n<pre>{pitch.elevator_pitch}</pre>\n\n"
                f"⭐ <b>Proyectos citados:</b> {', '.join(pitch.suggested_projects)}"
            )
            await self.send_message(chat_id, pitch_msg)

        elif data.startswith("discard:"):
            job_id = data.split("discard:")[1]
            await self.engine.storage.update_job_status(job_id, JobStatus.DISCARDED)
            await self.send_message(chat_id, "🗑️ Vacante descartada de la lista.")
