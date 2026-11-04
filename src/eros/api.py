import asyncio
from contextlib import asynccontextmanager
import email.utils as email_utils
import json
import logging
import os
import secrets
import time
from typing import Any
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

from eros.config import get_settings
from eros.hunter.email_finder import EMAIL_SOURCE_MANUAL
from eros.hunter.engine import HunterEngine, ScanInProgressError
from eros.integrations.llm import LLMOutputError, LLMUnavailableError
from eros.logging_setup import configure_logging
from eros.models import JobStatus
from eros.security import verify_cv_token
from eros.tasks import TaskError, TaskRegistry
from eros.ui import HTML_DASHBOARD
from eros.content.article import ArticleGenerator
from eros.content.models import ArticleGenerateRequest
from eros.bot.telegram import TelegramBot
from eros.radar.models import (
    TrendItem,
    TrendScanResponse,
    TrendStatus,
)
from eros.radar.storage import RadarStorage
from eros.radar.engine import RadarEngine

configure_logging()
logger = logging.getLogger("eros.api")

engine = HunterEngine()
settings = get_settings()
telegram_bot = TelegramBot(engine=engine)
radar_storage = RadarStorage()
radar_engine = RadarEngine(storage=radar_storage)
article_generator = ArticleGenerator(engine=engine, radar_storage=radar_storage)
task_registry = TaskRegistry()


def llm_http_error(e: Exception) -> HTTPException:
    """503 si no hay IA disponible; 502 si respondió algo inutilizable. Nunca se inventa un reemplazo."""
    if isinstance(e, LLMUnavailableError):
        return HTTPException(
            status_code=503,
            detail=f"IA no disponible: {e} No se genera texto sin IA; reintentá más tarde.",
        )
    return HTTPException(status_code=502, detail=f"La IA devolvió una respuesta inválida: {e}")


def error_response(status_code: int, result: dict[str, Any]) -> JSONResponse:
    """Error con la forma estándar de FastAPI ({"detail": ...}) más campos para el admin."""
    content = {"detail": result.get("error", "Error"), **{k: v for k, v in result.items() if k not in ("ok", "error")}}
    return JSONResponse(status_code=status_code, content=content)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicializar base de datos y sincronizar perfil inicial
    await engine.initialize()
    await radar_storage.init_db()
    logger.info("Eros Hunter API, artículos y TrendRadar inicializados.")

    bot_task = None
    if telegram_bot.is_configured:
        logger.info("Iniciando bot de Telegram en segundo plano...")
        bot_task = asyncio.create_task(telegram_bot.start_polling())

    scanner_task = None
    if settings.periodic_scan_enabled:
        logger.info(f"Iniciando escaneo periodico en segundo plano (cada {settings.periodic_scan_interval_hours}h)...")
        from eros.main import periodic_scanner
        scanner_task = asyncio.create_task(periodic_scanner(engine, telegram_bot, interval_hours=settings.periodic_scan_interval_hours))
    else:
        logger.info("Escaneo periodico autonomo desactivado (PERIODIC_SCAN_ENABLED=False). Escaneo solo bajo demanda.")

    yield

    if bot_task:
        logger.info("Deteniendo bot de Telegram...")
        telegram_bot.running = False
        bot_task.cancel()

    if scanner_task:
        logger.info("Deteniendo tarea periódica de escaneo...")
        scanner_task.cancel()


app = FastAPI(
    title="Eros Career OS & Job Hunter API",
    version="0.3.0",
    description="API y Control Center seguro del Agente Eros (Job Hunter + artículos para el portafolio)",
    lifespan=lifespan,
)

# Configuración estricta de CORS (sin comodín * al permitir credenciales)
default_origins = [
    "https://mateogs.tech",
    "https://eros.mateogs.tech",
    "https://api.mateogs.tech",
    "http://localhost:3000",
    "http://localhost:8000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:8000",
]
env_origins = [o.strip() for o in os.getenv("EROS_ALLOWED_ORIGINS", "").split(",") if o.strip()]
allowed_origins = env_origins if env_origins else default_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==============================================================================
# Modelos de Datos
# ==============================================================================

class StatusUpdateRequest(BaseModel):
    status: JobStatus


class LoginRequest(BaseModel):
    key: str


class ConfigUpdateRequest(BaseModel):
    match_min_score: int | None = None
    remote_only: bool | None = None
    auto_evaluate: bool | None = None
    eval_limit: int | None = None
    sources: dict[str, bool] | None = None


class SemanticSearchRequest(BaseModel):
    query: str
    limit: int = 30


class ApplyEmailRequest(BaseModel):
    to_email: str | None = None
    subject: str | None = None
    body: str | None = None
    channel: str = "auto"
    confirmed: bool = False
    # Reintentar un envío que se cortó sin saber si salió (send_state="unknown")
    force_retry: bool = False
    # El CV que armó el portafolio desde su base ({filename, pdf_base64, text, sha256, lang?, height_mm?}).
    # Obligatorio: sin él responde 422 cv_required. Lo valida eros.hunter.attached_cv.
    cv: dict[str, Any] | None = None


class ContactEmailUpdateRequest(BaseModel):
    contact_email: str


# ==============================================================================
# Seguridad y Autenticación
# ==============================================================================

def verify_key(key: str | None) -> bool:
    """Valida la clave contra EROS_API_KEY en tiempo constante para mitigar timing attacks."""
    if not key:
        return False
    current_key = get_settings().eros_api_key.strip()
    if not current_key:
        return False
    return secrets.compare_digest(key.strip(), current_key)


async def verify_auth(
    authorization: str | None = Header(None),
    x_eros_key: str | None = Header(None, alias="X-Eros-Key"),
    eros_session: str | None = Cookie(None),
) -> str:
    """Dependencia de autenticación: verifica Bearer token, header X-Eros-Key o cookie HTTP-only eros_session."""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif x_eros_key:
        token = x_eros_key.strip()
    elif eros_session:
        token = eros_session.strip()

    if not token or not verify_key(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autorizado. Proporcione una EROS_API_KEY válida vía Bearer token, header X-Eros-Key o sesión.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


# ==============================================================================
# Vistas Públicas & Autenticación
# ==============================================================================

@app.get("/", response_class=HTMLResponse)
async def dashboard_index():
    """Sirve la consola web standalone de administración y diagnóstico."""
    return HTMLResponse(content=HTML_DASHBOARD, media_type="text/html")


@app.get("/health")
async def health():
    """Healthcheck público para monitoreo de uptime y Coolify: comprueba que la base responde."""
    db_ok = await engine.storage.ping()
    body = {"ok": db_ok, "service": "eros-agent", "database": "ok" if db_ok else "error"}
    return JSONResponse(status_code=200 if db_ok else 503, content=body)


@app.post("/api/auth/login")
async def auth_login(body: LoginRequest, response: Response):
    """Inicia sesión y genera cookie HttpOnly de sesión."""
    if not verify_key(body.key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Clave EROS_API_KEY inválida")

    response.set_cookie(
        key="eros_session",
        value=body.key.strip(),
        httponly=True,
        samesite="lax",
        secure=get_settings().env == "production",
        max_age=86400 * 30,  # 30 días
    )
    return {"ok": True, "authenticated": True}


@app.post("/api/auth/logout")
async def auth_logout(response: Response):
    """Cierra la sesión activa y elimina la cookie."""
    response.delete_cookie(key="eros_session")
    return {"ok": True, "authenticated": False}


@app.get("/api/auth/me")
async def auth_me(
    authorization: str | None = Header(None),
    eros_session: str | None = Cookie(None),
):
    """Permite al cliente chequear si tiene una sesión válida sin lanzar 401."""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif eros_session:
        token = eros_session.strip()

    is_valid = bool(token and verify_key(token))
    return {"authenticated": is_valid}


# ==============================================================================
# Configuración Dinámica del Agente (Protegida)
# ==============================================================================

@app.get("/api/config", dependencies=[Depends(verify_auth)])
async def get_config():
    """Devuelve las configuraciones activas del agente guardadas en SQLite."""
    current_settings = get_settings()
    min_score_str = await engine.storage.get_setting("match_min_score", str(current_settings.match_min_score))
    remote_only_str = await engine.storage.get_setting("remote_only", "1")
    auto_eval_str = await engine.storage.get_setting("auto_evaluate", "1")
    eval_limit_str = await engine.storage.get_setting("eval_limit", "15")
    sources_str = await engine.storage.get_setting("sources_enabled")

    sources_map = {s.name: True for s in engine.sources}
    if sources_str:
        try:
            sources_map.update(json.loads(sources_str))
        except Exception:
            pass

    return {
        "match_min_score": int(min_score_str) if (min_score_str and min_score_str.isdigit()) else 75,
        "remote_only": remote_only_str == "1",
        "auto_evaluate": auto_eval_str == "1",
        "eval_limit": int(eval_limit_str) if (eval_limit_str and eval_limit_str.isdigit()) else 15,
        "sources": sources_map,
        "integrations": {
            "gemini": bool(current_settings.gemini_api_key),
            "telegram": bool(current_settings.telegram_bot_token),
            "portfolio": bool(current_settings.portfolio_api_url),
        },
    }


@app.post("/api/config", dependencies=[Depends(verify_auth)])
async def update_config(body: ConfigUpdateRequest):
    """Guarda nuevas preferencias operativas del agente en SQLite."""
    if body.match_min_score is not None:
        await engine.storage.set_setting("match_min_score", str(body.match_min_score))
    if body.remote_only is not None:
        await engine.storage.set_setting("remote_only", "1" if body.remote_only else "0")
    if body.auto_evaluate is not None:
        await engine.storage.set_setting("auto_evaluate", "1" if body.auto_evaluate else "0")
    if body.eval_limit is not None:
        await engine.storage.set_setting("eval_limit", str(body.eval_limit))
    if body.sources is not None:
        await engine.storage.set_setting("sources_enabled", json.dumps(body.sources))
    return {"ok": True, "saved": True}


# ==============================================================================
# Diagnóstico de Integraciones en Vivo (Protegida)
# ==============================================================================

@app.post("/api/integrations/test/{service}", dependencies=[Depends(verify_auth)])
async def test_integration(service: str):
    """Prueba la conectividad en vivo con Gemini, Telegram o la API del Portafolio."""
    current_settings = get_settings()
    svc = service.lower().strip()
    start = time.perf_counter()

    if svc == "gemini":
        if not current_settings.gemini_api_key:
            return {"ok": False, "error": "GEMINI_API_KEY no configurado en el servidor"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    headers={"x-goog-api-key": current_settings.gemini_api_key}
                )
                latency = int((time.perf_counter() - start) * 1000)
                if resp.status_code == 200:
                    return {"ok": True, "latency_ms": latency}
                return {"ok": False, "error": f"Gemini respondió con HTTP {resp.status_code}: {resp.text[:120]}"}
        except Exception as e:
            return {"ok": False, "error": f"Error conectando con Gemini: {str(e)}"}

    elif svc == "telegram":
        if not current_settings.telegram_bot_token:
            return {"ok": False, "error": "TELEGRAM_BOT_TOKEN no configurado en el servidor"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"https://api.telegram.org/bot{current_settings.telegram_bot_token}/getMe")
                latency = int((time.perf_counter() - start) * 1000)
                if resp.status_code == 200:
                    data = resp.json()
                    bot_name = data.get("result", {}).get("username", "bot")
                    return {"ok": True, "latency_ms": latency, "bot": f"@{bot_name}"}
                return {"ok": False, "error": f"Telegram respondió con HTTP {resp.status_code}"}
        except Exception as e:
            return {"ok": False, "error": f"Error conectando con Telegram: {str(e)}"}

    elif svc == "portfolio":
        if not current_settings.portfolio_api_url:
            return {"ok": False, "error": "PORTFOLIO_API_URL no configurado"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                url = f"{current_settings.portfolio_api_url.rstrip('/')}/projects"
                resp = await client.get(url)
                latency = int((time.perf_counter() - start) * 1000)
                if resp.status_code == 200:
                    return {"ok": True, "latency_ms": latency}
                return {"ok": False, "error": f"Portfolio respondió con HTTP {resp.status_code}"}
        except Exception as e:
            return {"ok": False, "error": f"Error conectando con Portfolio API: {str(e)}"}

    raise HTTPException(status_code=400, detail=f"Servicio no soportado: {service}")


# ==============================================================================
# Endpoints de Operación del Agente (Protegidos)
# ==============================================================================

@app.get("/api/stats", dependencies=[Depends(verify_auth)])
async def get_stats():
    """Devuelve métricas resumidas para los badges del panel admin (cada vacante cuenta una vez)."""
    counts = await engine.storage.count_jobs(high_match_min_score=75)
    return {
        "total": counts["total"],
        "high_match_count": counts["high_match"],
        "pending_eval_count": counts[JobStatus.NEW.value],
        "applied_count": counts[JobStatus.APPLIED.value],
        "discarded_count": counts[JobStatus.DISCARDED.value],
        "saved_count": counts[JobStatus.SAVED.value],
        "evaluated_count": counts[JobStatus.EVALUATED.value],
    }


@app.get("/api/jobs", dependencies=[Depends(verify_auth)])
async def list_jobs(
    min_score: int = Query(0, ge=0, le=100),
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500)
):
    """Lista las ofertas con filtros de puntaje y estado sin excluir estados salvo que se especifique."""
    jobs = await engine.storage.list_all_jobs(status=status, min_score=min_score, limit=limit)
    return {"data": jobs, "count": len(jobs)}


@app.get("/api/jobs/{job_id}", dependencies=[Depends(verify_auth)])
async def get_job(job_id: str):
    """Devuelve el detalle de una oferta."""
    job = await engine.storage.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Oferta no encontrada")
    return {"data": job}


@app.post("/api/jobs/semantic-search", dependencies=[Depends(verify_auth)])
async def semantic_search_jobs(body: SemanticSearchRequest):
    """Busca ofertas ordenadas por afinidad semántica vectorial con la consulta."""
    jobs = await engine.semantic_search(body.query, limit=body.limit)
    return {"data": jobs, "count": len(jobs), "query": body.query}


@app.post("/api/vectorize", dependencies=[Depends(verify_auth)])
async def trigger_vectorize(limit: int = 100):
    """Vectoriza vacantes pendientes o existentes sin embedding."""
    count = await engine.backfill_missing_embeddings(limit=limit)
    return {"ok": True, "vectorized_count": count}


async def _eval_limit() -> int:
    eval_limit_str = await engine.storage.get_setting("eval_limit", "15")
    return int(eval_limit_str) if (eval_limit_str and eval_limit_str.isdigit()) else 15


def _evaluation_summary(eval_res: list) -> dict[str, Any]:
    return {
        "evaluated_count": len(eval_res),
        "evaluated": [
            {"id": j.id, "title": j.title, "score": m.score, "verdict": m.verdict, "scored_by": m.scored_by, "status": j.status.value}
            for j, m in eval_res
        ],
    }


async def _notify_matches(evaluated: list) -> int:
    """Avisa por Telegram las vacantes evaluadas con puntaje suficiente; devuelve cuántas salieron."""
    min_score = get_settings().match_min_score
    sent = 0
    for job, match in evaluated:
        if match.score >= min_score and await telegram_bot.notify_match(job, match):
            sent += 1
    return sent


def _accepted(task: dict[str, Any], created: bool) -> JSONResponse:
    return JSONResponse(status_code=202, content={
        "ok": True,
        "task_id": task["task_id"],
        "kind": task["kind"],
        "status": task["status"],
        "started_at": task["started_at"],
        "already_running": not created,
        "status_url": f"/api/tasks/{task['task_id']}",
    })


@app.post("/api/scan", dependencies=[Depends(verify_auth)], status_code=202)
async def trigger_scan(evaluate: bool = False, background_eval: bool = False, notify: bool = False):
    """Dispara un escaneo en segundo plano y responde 202 con el id de la tarea.

    El estado se consulta en GET /api/tasks/{task_id}. Si ya hay un escaneo corriendo,
    devuelve el de ese (already_running=true) en vez de arrancar otro.
    evaluate=true (o background_eval=true con auto_evaluate activo) evalúa las nuevas al terminar.
    notify=true avisa por Telegram las evaluadas con puntaje desde MATCH_MIN_SCORE (lo usa el cron
    diario de n8n; «Buscar vacantes» del admin no lo pide).
    """
    if engine.scan_in_progress and not task_registry.running("scan"):
        raise HTTPException(status_code=409, detail="Ya hay un escaneo en curso (iniciado por Telegram o el escaneo periódico).")

    async def job() -> dict[str, Any]:
        scan_res = await engine.run_scan()
        should_eval = evaluate
        if not should_eval and background_eval:
            should_eval = (await engine.storage.get_setting("auto_evaluate", "0")) == "1"
        summary: dict[str, Any] = {"scanned": scan_res["total_found"], "new_jobs": scan_res["new_jobs"], "evaluated_count": 0}
        if should_eval:
            if engine.evaluation_in_progress:
                summary["evaluation_skipped"] = "Ya había una evaluación en curso."
            else:
                evaluated = await engine.evaluate_pending_jobs(limit=await _eval_limit())
                summary.update(_evaluation_summary(evaluated))
                if notify:
                    summary["notified_count"] = await _notify_matches(evaluated)
        return summary

    task, created = task_registry.start("scan", job)
    return _accepted(task, created)


@app.get("/api/tasks/{task_id}", dependencies=[Depends(verify_auth)])
async def get_task_status(task_id: str):
    """Estado de una tarea en segundo plano: running, done (con result) o failed (con error)."""
    task = task_registry.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tarea no encontrada (puede que Eros se haya reiniciado).")
    return task


@app.post("/api/purge", dependencies=[Depends(verify_auth)])
async def trigger_purge():
    """Marca como descartadas (sin borrarlas) las vacantes que no cumplen los filtros actuales.

    Nunca toca las postuladas.
    """
    discarded = await engine.discard_incompatible_jobs()
    return {"ok": True, "discarded_count": discarded, "purged_count": discarded}


@app.post("/api/evaluate", dependencies=[Depends(verify_auth)], status_code=202)
async def trigger_evaluate(limit: int = 15):
    """Evalúa las vacantes pendientes en segundo plano y responde 202 con el id de la tarea."""
    if engine.evaluation_in_progress and not task_registry.running("evaluate"):
        raise HTTPException(status_code=409, detail="Ya hay una evaluación en curso.")

    async def job() -> dict[str, Any]:
        return _evaluation_summary(await engine.evaluate_pending_jobs(limit=limit))

    task, created = task_registry.start("evaluate", job)
    return _accepted(task, created)


@app.post("/api/jobs/{job_id}/evaluate", dependencies=[Depends(verify_auth)])
async def evaluate_single_job_endpoint(job_id: str):
    """Evalúa una única vacante bajo demanda con Gemini."""
    res = await engine.evaluate_single_job(job_id)
    if not res:
        raise HTTPException(status_code=404, detail="Oferta no encontrada")
    job, match = res
    return {"ok": True, "job": job, "match": match, "generated_by": match.scored_by}


@app.post("/api/pitch/{job_id}", dependencies=[Depends(verify_auth)])
async def generate_pitch(job_id: str):
    """Genera una propuesta personalizada conectada con el portafolio."""
    try:
        pitch = await engine.generate_pitch_for_job(job_id)
    except (LLMUnavailableError, LLMOutputError) as e:
        raise llm_http_error(e)
    if not pitch:
        raise HTTPException(status_code=404, detail="No se pudo generar el pitch para la oferta")
    return {"data": pitch}


@app.post("/api/cv/{job_id}", dependencies=[Depends(verify_auth)])
async def generate_cv(job_id: str):
    """Genera un CV adaptado Harvard ATS para la vacante."""
    try:
        result = await engine.generate_cv_for_job(job_id)
    except (LLMUnavailableError, LLMOutputError) as e:
        raise llm_http_error(e)
    if not result:
        raise HTTPException(status_code=404, detail="No se pudo generar el CV para la oferta")
    cv_data, html = result
    return {"data": cv_data, "html": html}


async def verify_cv_access(
    job_id: str,
    token: str | None = Query(None),
    authorization: str | None = Header(None),
    x_eros_key: str | None = Header(None, alias="X-Eros-Key"),
    eros_session: str | None = Cookie(None),
) -> None:
    """El CV se sirve con la clave de Eros o con el token firmado de esa vacante (enlace de los correos)."""
    if verify_cv_token(job_id, token):
        return
    await verify_auth(authorization=authorization, x_eros_key=x_eros_key, eros_session=eros_session)


@app.get("/api/cv/{job_id}/html", response_class=HTMLResponse, dependencies=[Depends(verify_cv_access)])
@app.get("/api/jobs/{job_id}/cv/html", response_class=HTMLResponse, dependencies=[Depends(verify_cv_access)])
async def get_cv_html(job_id: str, auto_print: bool = False):
    """Devuelve la vista HTML imprimible del CV ya guardado de la vacante (nunca lo genera)."""
    html = await engine.get_cv_html_for_job(job_id)
    if not html:
        raise HTTPException(status_code=404, detail="Esta vacante no tiene un CV guardado. Generalo con POST /api/cv/{job_id}.")
    if auto_print:
        html = html.replace("</body>", "<script>window.addEventListener('load', () => { setTimeout(() => window.print(), 350); });</script></body>")
    return HTMLResponse(content=html, media_type="text/html")


@app.get("/api/cv/{job_id}/pdf", dependencies=[Depends(verify_cv_access)])
@app.get("/api/jobs/{job_id}/cv/pdf", dependencies=[Depends(verify_cv_access)])
async def get_cv_pdf(job_id: str, download: bool = False):
    """Devuelve el PDF (1 página A4 Harvard ATS) del CV ya guardado de la vacante (nunca lo genera)."""
    pdf_bytes = await engine.get_cv_pdf_for_job(job_id)
    if not pdf_bytes:
        raise HTTPException(status_code=404, detail="Esta vacante no tiene un CV guardado. Generalo con POST /api/cv/{job_id}.")

    disposition = "attachment" if download else "inline"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'{disposition}; filename="CV_Mateo_Sonzogni.pdf"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )


@app.patch("/api/jobs/{job_id}/status", dependencies=[Depends(verify_auth)])
async def update_job_status(job_id: str, body: StatusUpdateRequest):
    """Actualiza el estado de la vacante (APPLIED, DISCARDED, SAVED, etc.)."""
    job = await engine.storage.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Oferta no encontrada")

    await engine.storage.update_job_status(job_id, body.status)
    return {"ok": True, "job_id": job_id, "new_status": body.status}


@app.delete("/api/jobs", dependencies=[Depends(verify_auth)])
async def delete_all_jobs():
    """Elimina todas las vacantes escaneadas para empezar desde cero."""
    deleted = await engine.clear_all_jobs()
    return {"ok": True, "deleted_count": deleted}


@app.delete("/api/jobs/{job_id}", dependencies=[Depends(verify_auth)])
async def delete_single_job(job_id: str):
    """Elimina una vacante específica por ID."""
    job = await engine.storage.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Oferta no encontrada")
    await engine.storage.delete_job(job_id)
    return {"ok": True, "deleted_id": job_id}


@app.get("/api/jobs/{job_id}/apply-preview", dependencies=[Depends(verify_auth)])
async def get_apply_preview(job_id: str):
    """Devuelve la vista previa del asunto, cuerpo y enlaces para postular por correo."""
    preview = await engine.app_dispatcher.get_application_preview(job_id)
    if not preview.get("ok"):
        raise HTTPException(status_code=404, detail=preview.get("error", "Error generando vista previa"))
    return preview


APPLY_ERROR_STATUS = {
    "job_not_found": 404,
    "already_applied": 409,
    "cv_required": 422,
    "invalid_cv": 422,
    "send_in_progress": 409,
    "send_outcome_unknown": 409,
    "missing_email": 422,
    "invalid_email": 422,
    "unverified_email": 422,
    "requires_confirmation": 428,
    "invalid_channel": 422,
    "no_provider": 503,
    "provider_rejected": 502,
}


@app.post("/api/jobs/{job_id}/apply-email", dependencies=[Depends(verify_auth)])
async def apply_job_by_email(job_id: str, payload: ApplyEmailRequest | None = None):
    """Despacha la postulación vía el webhook de postulaciones de n8n o SMTP, con el CV que manda el portafolio.

    ok=true solo si un proveedor aceptó el envío. Los errores llevan `detail` y `error_code`.
    Sin `cv` responde 422 cv_required: Eros nunca adjunta un CV propio.
    """
    req = payload or ApplyEmailRequest()
    res = await engine.app_dispatcher.dispatch_application(
        job_id=job_id,
        to_email=req.to_email,
        custom_subject=req.subject,
        custom_body=req.body,
        channel=req.channel,
        confirmed=req.confirmed,
        force_retry=req.force_retry,
        cv=req.cv,
    )
    if not res.get("ok"):
        if res.get("error_code") == "send_outcome_unknown" and res.get("provider"):
            # El proveedor se cortó a mitad del envío (no es un conflicto previo)
            return error_response(504, res)
        return error_response(APPLY_ERROR_STATUS.get(res.get("error_code", ""), 400), res)
    return res


@app.patch("/api/jobs/{job_id}/contact-email", dependencies=[Depends(verify_auth)])
async def update_job_contact_email(job_id: str, body: ContactEmailUpdateRequest):
    """Define a mano el correo de contacto de una vacante (fuente: manual)."""
    job = await engine.storage.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Oferta no encontrada")
    email = body.contact_email.strip().lower()
    if email:
        _, parsed = email_utils.parseaddr(email)
        if not parsed or parsed != email or "@" not in email or "." not in email.split("@")[-1]:
            raise HTTPException(status_code=422, detail=f"El correo '{email}' no tiene un formato válido.")
    await engine.storage.update_job_contact_email(job_id, email or None, source=EMAIL_SOURCE_MANUAL)
    return {
        "ok": True,
        "job_id": job_id,
        "contact_email": email or None,
        "contact_email_source": EMAIL_SOURCE_MANUAL if email else None,
    }


@app.post("/api/jobs/{job_id}/find-email", dependencies=[Depends(verify_auth)])
async def find_job_contact_email(job_id: str):
    """Busca un correo de selección real (aviso, sitio de la empresa o Hunter.io). Nunca lo adivina.

    Un correo escrito a mano no se reemplaza por uno encontrado.
    """
    job = await engine.storage.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Oferta no encontrada")

    found_email, source = await engine.email_finder.resolve_contact_email(
        company=job.company,
        job_url=job.url,
        recruiter_name=job.hiring_manager_name,
        description=job.description,
    )
    keep_manual = job.contact_email and job.contact_email_source == EMAIL_SOURCE_MANUAL
    if found_email and not keep_manual:
        await engine.storage.update_job_contact_email(job_id, found_email, source=source)
        return {
            "ok": True,
            "job_id": job_id,
            "contact_email": found_email,
            "contact_email_source": source,
            "source": source,
            "found": True,
        }
    return {
        "ok": True,
        "job_id": job_id,
        "contact_email": job.contact_email,
        "contact_email_source": job.contact_email_source if job.contact_email else None,
        "source": source,
        "found": bool(found_email),
    }


@app.post("/api/profile/sync", dependencies=[Depends(verify_auth)])
async def sync_profile():
    """Fuerza la sincronización del perfil desde la API del portafolio."""
    profile = await engine.sync_profile()
    return {"ok": True, "profile": profile}


# ==============================================================================
# Artículos para el portafolio (Eros los escribe; el portafolio los publica)
# ==============================================================================

@app.post("/api/articles/generate", dependencies=[Depends(verify_auth)], status_code=202)
async def generate_article(payload: ArticleGenerateRequest | None = None):
    """Escribe un artículo (es + en) en segundo plano y responde 202 con el id de la tarea.

    Cuando termina, GET /api/tasks/{task_id} trae el artículo en `result`. Si ya hay uno
    escribiéndose, devuelve esa tarea (already_running=true). Con trend_id, la tendencia
    del Radar queda GENERATED al terminar. Eros nunca escribe en el portafolio.
    """
    req = payload or ArticleGenerateRequest()

    async def job() -> dict[str, Any]:
        try:
            article = await article_generator.generate(req)
        except LLMUnavailableError as e:
            raise TaskError(f"Gemini no está disponible: {e}", code="llm_unavailable") from e
        except LLMOutputError as e:
            raise TaskError(str(e), code="llm_output_invalid") from e
        return article.model_dump()

    task, created = task_registry.start("article", job)
    return _accepted(task, created)


# ---------------------------------------------------------------------------
# TrendRadar Endpoints (Eros Radar de Tendencias Técnicas)
# Para escribir un artículo a partir de una tendencia: POST /api/articles/generate con trend_id.
# ---------------------------------------------------------------------------

@app.post("/api/radar/scan", dependencies=[Depends(verify_auth)], response_model=TrendScanResponse)
async def scan_radar(limit: int = 15):
    """Escanea Hacker News, Dev.to y GitHub en busca de tendencias técnicas de alta relevancia."""
    trends = await radar_engine.scan(limit_per_source=limit)
    return TrendScanResponse(
        total_found=len(trends),
        new_trends=radar_engine.last_new_count,
        trends=trends,
    )


@app.get("/api/radar/trends", dependencies=[Depends(verify_auth)], response_model=list[TrendItem])
async def get_radar_trends(
    status: TrendStatus | None = None,
    min_score: int | None = None,
    limit: int = 50,
):
    """Devuelve las tendencias detectadas por TrendRadar ordenadas por relevancia técnica."""
    return await radar_storage.get_trends(status=status, min_score=min_score, limit=limit)


@app.get("/api/radar/trends/{trend_id}", dependencies=[Depends(verify_auth)], response_model=TrendItem)
async def get_radar_trend(trend_id: str):
    trend = await radar_storage.get_trend(trend_id)
    if not trend:
        raise HTTPException(status_code=404, detail="Tendencia no encontrada")
    return trend


@app.patch("/api/radar/trends/{trend_id}/status", dependencies=[Depends(verify_auth)])
async def update_radar_trend_status(trend_id: str, payload: dict[str, Any]):
    new_status = payload.get("status")
    if not new_status:
        raise HTTPException(status_code=400, detail="El campo 'status' es obligatorio")
    try:
        ts = TrendStatus(new_status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Estado inválido: {new_status}")
    ok = await radar_storage.update_status(trend_id, ts)
    return {"ok": ok, "id": trend_id, "status": ts.value}
