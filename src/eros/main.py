import argparse
import asyncio
import logging
import sys
from eros.bot.telegram import TelegramBot
from eros.config import get_settings
from eros.hunter.engine import HunterEngine

# Asegurar encoding UTF-8 en terminales Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("eros")


async def periodic_scanner(engine: HunterEngine, bot: TelegramBot, interval_hours: int = 4) -> None:
    """Tarea periódica en segundo plano que corre el escaneo cada N horas."""
    while True:
        try:
            logger.info("Despertando tarea programada: buscando nuevas ofertas...")
            scan_res = await engine.run_scan()
            if scan_res["new_jobs"] > 0:
                logger.info(f"Evaluando {scan_res['new_jobs']} nuevas ofertas encontradas...")
                matches = await engine.evaluate_pending_jobs(limit=15)
                settings = get_settings()
                for job, match in matches:
                    if match.score >= settings.match_min_score:
                        await bot.notify_match(job, match)
            else:
                logger.info("No hay nuevas vacantes en esta pasada.")
        except Exception as e:
            logger.error(f"Error en tarea periódica de escaneo: {e}")

        await asyncio.sleep(interval_hours * 3600)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Eros Agent — Asistente de Búsqueda de Empleo")
    parser.add_argument("--sync", action="store_true", help="Sincronizar perfil desde el portafolio en vivo")
    parser.add_argument("--scan", action="store_true", help="Escanear ofertas de todas las fuentes")
    parser.add_argument("--evaluate", action="store_true", help="Evaluar ofertas pendientes con el LLM")
    parser.add_argument("--server", action="store_true", help="Iniciar servidor API HTTP con FastAPI")
    parser.add_argument("--port", type=int, default=8000, help="Puerto para el servidor HTTP (default: 8000)")
    parser.add_argument("--post", type=str, help="Generar publicación omnicanal sobre un tema técnico específico")
    parser.add_argument("--bot", action="store_true", help="Iniciar bot de Telegram")
    parser.add_argument("--daemon", action="store_true", help="Modo demonio: Servidor HTTP + bot de Telegram")

    args = parser.parse_args()
    engine = HunterEngine()
    await engine.initialize()
    bot = TelegramBot(engine=engine)

    # 1. Sincronizar perfil
    if args.sync:
        profile = await engine.sync_profile()
        print(f"\n[OK] Perfil sincronizado con éxito:")
        print(f"• Nombre: {profile.name}")
        print(f"• Rol: {profile.role}")
        print(f"• Ubicación: {profile.location} ({profile.timezone})")
        print(f"• Idiomas: {profile.languages}")
        print(f"• Tecnologías: {', '.join(profile.tech_stack)}")
        print(f"• Proyectos: {[p.title for p in profile.projects]}")
        return

    # 2. Generar post de contenido por CLI
    if args.post:
        from eros.content.generator import ContentGenerator
        from eros.content.storage import ContentStorage
        from eros.content.models import ContentGenerateRequest, ContentPillar

        c_storage = ContentStorage()
        await c_storage.init_db()
        gen = ContentGenerator(storage=c_storage, engine=engine)
        print(f"\n[GENERANDO] Creando publicación omnicanal con Gemini para: '{args.post}'...")
        post = await gen.generate_post(ContentGenerateRequest(topic=args.post, pillar=ContentPillar.ARCHITECTURE))
        print(f"\n[OK] Publicación generada con ID: {post.id}")
        print(f"• Título: {post.title}")
        print(f"• Hook:\n{post.hook}\n")
        print(f"• Tweets: {len(post.twitter_thread)}")
        print(f"• Slides Carousel: {len(post.carousel_slides)}")
        print(f"• Ver Carousel en navegador: http://localhost:{args.port}/api/content/carousel/{post.id}/html")
        return

    # 3. Escanear
    if args.scan:
        print("\n[BUSCANDO] Escaneando Get on Board, RemoteOK y Hacker News...")
        res = await engine.run_scan()
        print(f"[OK] Finalizado: {res['total_found']} ofertas obtenidas ({res['new_jobs']} nuevas en la base).")
        return

    # 4. Evaluar
    if args.evaluate:
        print("\n[EVALUANDO] Evaluando vacantes con el LLM Matcher...")
        matches = await engine.evaluate_pending_jobs(limit=5)
        print(f"[OK] Se evaluaron {len(matches)} vacantes:")
        for job, match in matches:
            print(f"  • [{match.score}%] {job.title} en {job.company} -> {match.verdict}")
        return

    # 5. Solo bot
    if args.bot:
        if not bot.is_configured:
            print("[ERROR] TELEGRAM_BOT_TOKEN no configurado en .env.")
            sys.exit(1)
        print("[INICIANDO] Bot de Telegram activo (Ctrl+C para salir)...")
        await bot.start_polling()
        return

    # 6. Modo demonio: Servidor FastAPI + Bot de Telegram
    if args.daemon:
        import uvicorn
        print(f"[INICIANDO] Modo Demonio (API Server + Bot Telegram)...")
        config = uvicorn.Config("eros.api:app", host="0.0.0.0", port=args.port, log_level="info")
        server = uvicorn.Server(config)
        tasks = [server.serve()]
        if bot.is_configured:
            tasks.append(bot.start_polling())
        await asyncio.gather(*tasks)
        return

    # 7. Servidor FastAPI por defecto
    import uvicorn
    print(f"[INICIANDO] Eros Agent API Server en http://0.0.0.0:{args.port}...")
    config = uvicorn.Config("eros.api:app", host="0.0.0.0", port=args.port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nEros Agent detenido por el usuario.")
