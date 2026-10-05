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
    parser.add_argument("--bot", action="store_true", help="Iniciar solo el bot de Telegram")
    parser.add_argument("--daemon", action="store_true", help="Modo demonio: Bot de Telegram + escáner periódico 24/7")

    args = parser.parse_args()
    engine = HunterEngine()
    await engine.initialize()
    bot = TelegramBot(engine=engine)

    # 1. Sincronizar perfil
    if args.sync:
        profile = await engine.sync_profile()
        print(f"\n✅ Perfil sincronizado con éxito:")
        print(f"• Nombre: {profile.name}")
        print(f"• Rol: {profile.role}")
        print(f"• Ubicación: {profile.location} ({profile.timezone})")
        print(f"• Idiomas: {profile.languages}")
        print(f"• Tecnologías: {', '.join(profile.tech_stack)}")
        print(f"• Proyectos: {[p.title for p in profile.projects]}")
        return

    # 2. Escanear
    if args.scan:
        print("\n🔎 Escaneando Get on Board, RemoteOK y Hacker News...")
        res = await engine.run_scan()
        print(f"✅ Finalizado: {res['total_found']} ofertas obtenidas ({res['new_jobs']} nuevas en la base).")
        return

    # 3. Evaluar
    if args.evaluate:
        print("\n🧠 Evaluando vacantes con el LLM Matcher...")
        matches = await engine.evaluate_pending_jobs(limit=5)
        print(f"✅ Se evaluaron {len(matches)} vacantes:")
        for job, match in matches:
            print(f"  • [{match.score}%] {job.title} en {job.company} -> {match.verdict}")
        return

    # 4. Solo bot
    if args.bot:
        if not bot.is_configured:
            print("❌ TELEGRAM_BOT_TOKEN no configurado en .env.")
            sys.exit(1)
        print("🤖 Iniciando bot de Telegram (Ctrl+C para salir)...")
        await bot.start_polling()
        return

    # 5. Modo por defecto o --daemon (para Coolify / VPS)
    print("🚀 Iniciando Eros Agent en modo Daemon...")
    if bot.is_configured:
        print(f"• Telegram Bot: ACTIVO (Monitoreando para usuario {bot.allowed_user_id or 'todos'})")
        # Correr el bot y el scheduler concurrentemente
        await asyncio.gather(
            bot.start_polling(),
            periodic_scanner(engine, bot, interval_hours=4)
        )
    else:
        print("• Telegram Bot: DESACTIVADO (configurar TELEGRAM_BOT_TOKEN en .env).")
        print("• Ejecutando escaneo inicial y manteniendo el demonio de fondo...")
        await engine.run_scan()
        await periodic_scanner(engine, bot, interval_hours=4)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nEros Agent detenido por el usuario.")
