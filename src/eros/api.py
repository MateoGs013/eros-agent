import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
import secrets
import time
from typing import Any
from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

from eros.config import get_settings
from eros.hunter.engine import HunterEngine
from eros.models import JobStatus
from eros.ui import HTML_DASHBOARD
from eros.content.models import (
    ContentGenerateRequest,
    ContentPostStatus,
    ContentStatusUpdateRequest,
)
from eros.content.storage import ContentStorage
from eros.content.generator import ContentGenerator
from eros.content.carousel import CarouselRenderer
from eros.content.dispatcher import ContentDispatcher
from eros.bot.telegram import TelegramBot
from eros.radar.models import (
    TrendGenerateRequest,
    TrendItem,
    TrendScanResponse,
    TrendStatus,
)
from eros.radar.storage import RadarStorage
from eros.radar.engine import RadarEngine

logger = logging.getLogger("eros.api")

engine = HunterEngine()
settings = get_settings()
content_storage = ContentStorage()
content_generator = ContentGenerator(storage=content_storage, engine=engine)
content_dispatcher = ContentDispatcher(storage=content_storage)
telegram_bot = TelegramBot(engine=engine)
radar_storage = RadarStorage()
radar_engine = RadarEngine(storage=radar_storage)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicializar base de datos y sincronizar perfil inicial
    await engine.initialize()
    await content_storage.init_db()
    await radar_storage.init_db()
    logger.info("Eros Hunter API, Content Engine y TrendRadar inicializados.")

    bot_task = None
    if telegram_bot.is_configured:
        logger.info("Iniciando bot de Telegram en segundo plano...")
        bot_task = asyncio.create_task(telegram_bot.start_polling())

    yield

    if bot_task:
        logger.info("Deteniendo bot de Telegram...")
        telegram_bot.running = False
        bot_task.cancel()


app = FastAPI(
    title="Eros Career OS & Job Hunter API",
    version="0.3.0",
    description="API y Control Center seguro del Agente Eros (Job Hunter + Content Engine)",
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


# ==============================================================================
# Seguridad y Autenticación
# ==============================================================================

def verify_key(key: str | None) -> bool:
    """Valida la clave contra EROS_API_KEY en tiempo constante para mitigar timing attacks."""
    if not key:
        return False
    current_key = get_settings().eros_api_key.strip()
    if not current_key:
        current_key = "eros_dev_sec_7f9b8c2d1e0a4f5b6c7d8e9f0a1b2c3d"
    return secrets.compare_digest(key.strip(), current_key)


async def verify_auth(
    authorization: str | None = Header(None),
    eros_session: str | None = Cookie(None),
) -> str:
    """Dependencia de autenticación: verifica Bearer token o cookie HTTP-only eros_session."""
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif eros_session:
        token = eros_session.strip()

    if not token or not verify_key(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autorizado. Proporcione una EROS_API_KEY válida vía Bearer token o sesión.",
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
    """Healthcheck público para monitoreo de uptime y Coolify."""
    return {"ok": True, "service": "eros-agent"}


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
                    f"https://generativelanguage.googleapis.com/v1beta/models?key={current_settings.gemini_api_key}"
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
    """Devuelve métricas resumidas para los badges del panel admin."""
    all_jobs = await engine.storage.list_matched_jobs(min_score=0, limit=1000)
    unseen = await engine.storage.list_unseen_jobs()

    high_matches = [j for j in all_jobs if (j.match_score or 0) >= 75 and j.status != JobStatus.DISCARDED]
    applied = [j for j in all_jobs if j.status == JobStatus.APPLIED]
    discarded = [j for j in all_jobs if j.status == JobStatus.DISCARDED]

    return {
        "total": len(all_jobs) + len(unseen),
        "high_match_count": len(high_matches),
        "pending_eval_count": len(unseen),
        "applied_count": len(applied),
        "discarded_count": len(discarded),
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


@app.post("/api/scan", dependencies=[Depends(verify_auth)])
async def trigger_scan(evaluate: bool | None = None):
    """Dispara un escaneo en vivo en todas las fuentes habilitadas."""
    scan_res = await engine.run_scan()
    eval_res = []

    if evaluate is None:
        auto_eval_str = await engine.storage.get_setting("auto_evaluate", "1")
        evaluate = (auto_eval_str == "1")

    if evaluate:
        eval_limit_str = await engine.storage.get_setting("eval_limit", "15")
        limit = int(eval_limit_str) if (eval_limit_str and eval_limit_str.isdigit()) else 15
        eval_res = await engine.evaluate_pending_jobs(limit=limit)

    return {
        "ok": True,
        "scanned": scan_res["total_found"],
        "new_jobs": scan_res["new_jobs"],
        "evaluated_count": len(eval_res)
    }


@app.post("/api/purge", dependencies=[Depends(verify_auth)])
async def trigger_purge():
    """Limpia o marca como descartadas vacantes en base que no cumplen con los filtros actuales."""
    purged = await engine.clean_existing_unqualified_jobs()
    return {"ok": True, "purged_count": purged}


@app.post("/api/evaluate", dependencies=[Depends(verify_auth)])
async def trigger_evaluate(limit: int = 15):
    """Evalúa las vacantes pendientes con Gemini aplicando los criterios de perfil."""
    eval_res = await engine.evaluate_pending_jobs(limit=limit)
    return {
        "ok": True,
        "evaluated_count": len(eval_res),
        "evaluated": [{"id": j.id, "title": j.title, "score": m.score, "verdict": m.verdict} for j, m in eval_res]
    }


@app.post("/api/jobs/{job_id}/evaluate", dependencies=[Depends(verify_auth)])
async def evaluate_single_job_endpoint(job_id: str):
    """Evalúa una única vacante bajo demanda con Gemini."""
    res = await engine.evaluate_single_job(job_id)
    if not res:
        raise HTTPException(status_code=404, detail="Oferta no encontrada")
    job, match = res
    return {"ok": True, "job": job, "match": match}


@app.post("/api/pitch/{job_id}", dependencies=[Depends(verify_auth)])
async def generate_pitch(job_id: str):
    """Genera una propuesta personalizada conectada con el portafolio."""
    pitch = await engine.generate_pitch_for_job(job_id)
    if not pitch:
        raise HTTPException(status_code=404, detail="No se pudo generar el pitch para la oferta")
    return {"data": pitch}


@app.post("/api/cv/{job_id}", dependencies=[Depends(verify_auth)])
async def generate_cv(job_id: str):
    """Genera un CV adaptado Harvard ATS para la vacante."""
    result = await engine.generate_cv_for_job(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="No se pudo generar el CV para la oferta")
    cv_data, html = result
    return {"data": cv_data, "html": html}


@app.get("/api/cv/{job_id}/html", response_class=HTMLResponse, dependencies=[Depends(verify_auth)])
async def get_cv_html(job_id: str, auto_print: bool = False):
    """Devuelve la vista HTML imprimible del CV de la vacante."""
    html = await engine.get_cv_html_for_job(job_id)
    if not html:
        raise HTTPException(status_code=404, detail="CV no disponible para esta oferta")
    if auto_print:
        html = html.replace("</body>", "<script>window.addEventListener('load', () => { setTimeout(() => window.print(), 350); });</script></body>")
    return HTMLResponse(content=html, media_type="text/html")


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


@app.post("/api/profile/sync", dependencies=[Depends(verify_auth)])
async def sync_profile():
    """Fuerza la sincronización del perfil desde la API del portafolio."""
    profile = await engine.sync_profile()
    return {"ok": True, "profile": profile}


# ==============================================================================
# Endpoints de Generación y Distribución de Contenido (Career OS)
# ==============================================================================

@app.post("/api/content/generate", dependencies=[Depends(verify_auth)])
async def generate_content(body: ContentGenerateRequest):
    """Genera una publicación técnica omnicanal (LinkedIn, X/Twitter, Dev.to, Carousel 5 slides)."""
    try:
        post = await content_generator.generate_post(body)
        return {"ok": True, "data": post}
    except Exception as e:
        logger.error(f"Error generando contenido: {e}")
        raise HTTPException(status_code=500, detail=f"Falla generando contenido: {str(e)}")


@app.get("/api/content/posts", dependencies=[Depends(verify_auth)])
async def list_content_posts(
    status: ContentPostStatus | None = None,
    limit: int = Query(50, ge=1, le=100)
):
    """Lista las publicaciones creadas con opción de filtrado por estado."""
    posts = await content_storage.list_posts(status=status, limit=limit)
    return {"data": posts, "count": len(posts)}


@app.get("/api/content/posts/{post_id}", dependencies=[Depends(verify_auth)])
async def get_content_post(post_id: str):
    """Devuelve una publicación por ID con todas sus plataformas y slides."""
    post = await content_storage.get_post(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Publicación no encontrada")
    return {"data": post}


@app.patch("/api/content/posts/{post_id}/status", dependencies=[Depends(verify_auth)])
async def update_content_post_status(post_id: str, body: ContentStatusUpdateRequest):
    """Actualiza el estado de una publicación (draft, approved, published, rejected)."""
    post = await content_storage.get_post(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Publicación no encontrada")

    await content_storage.update_status(post_id, body.status)
    return {"ok": True, "post_id": post_id, "new_status": body.status}


@app.post("/api/content/posts/{post_id}/publish", dependencies=[Depends(verify_auth)])
async def publish_content_post(post_id: str):
    """Aprueba la publicación y la despacha al webhook de n8n para distribución."""
    res = await content_dispatcher.publish_post(post_id)
    if not res.get("ok"):
        raise HTTPException(status_code=502, detail=res.get("error", "Error despachando a n8n"))
    return res


@app.delete("/api/content/posts/{post_id}", dependencies=[Depends(verify_auth)])
async def delete_content_post(post_id: str):
    """Elimina una publicación."""
    post = await content_storage.get_post(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Publicación no encontrada")

    await content_storage.delete_post(post_id)
    return {"ok": True, "deleted": post_id}


@app.get("/api/content/carousel/{post_id}/html", response_class=HTMLResponse)
async def get_carousel_html(post_id: str, auto_print: bool = False):
    """Devuelve la vista interactiva e imprimible (Print to PDF de LinkedIn) de las diapositivas."""
    post = await content_storage.get_post(post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Publicación no encontrada")

    html = CarouselRenderer.render_html(post, auto_print=auto_print)
    return HTMLResponse(content=html, media_type="text/html")


@app.post("/api/webhooks/n8n/callback")
async def n8n_callback(payload: dict[str, Any]):
    """Webhook receptor de confirmación desde n8n cuando se ejecuta un workflow."""
    logger.info(f"Callback recibido desde n8n: {payload}")
    post_id = payload.get("post_id")
    status_str = payload.get("status", "published")
    if post_id:
        new_status = ContentPostStatus.PUBLISHED if status_str == "published" else ContentPostStatus.REJECTED
        await content_storage.update_status(
            post_id,
            new_status,
            n8n_response=json.dumps(payload.get("details", payload))
        )
    return {"ok": True, "received": True}


# ---------------------------------------------------------------------------
# TrendRadar Endpoints (Eros Radar de Tendencias Técnicas)
# ---------------------------------------------------------------------------

@app.post("/api/radar/scan", dependencies=[Depends(verify_auth)], response_model=TrendScanResponse)
async def scan_radar(limit: int = 15):
    """Escanea Hacker News, Dev.to y GitHub en busca de tendencias técnicas de alta relevancia."""
    trends = await radar_engine.scan(limit_per_source=limit)
    return TrendScanResponse(
        total_found=len(trends),
        new_trends=len(trends),
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


@app.post("/api/radar/trends/{trend_id}/generate", dependencies=[Depends(verify_auth)])
async def generate_post_from_trend(trend_id: str, payload: TrendGenerateRequest | None = None):
    """Genera una publicación omnicanal completa a partir de una tendencia detectada."""
    trend = await radar_storage.get_trend(trend_id)
    if not trend:
        raise HTTPException(status_code=404, detail="Tendencia no encontrada")

    req = payload or TrendGenerateRequest()
    pillar_val = req.pillar or "TECHNICAL_BREAKDOWN"
    angle = req.custom_angle or trend.engineering_angle

    gen_req = ContentGenerateRequest(
        topic=trend.title,
        key_points=[
            f"Referencia original: {trend.url}",
            f"Síntesis: {trend.summary}",
            f"Ángulo de ingeniería: {angle}",
        ],
        project_slug=req.project_slug,
        pillar=pillar_val,  # type: ignore
    )

    post = await content_generator.generate(gen_req)
    await radar_storage.update_status(trend_id, TrendStatus.GENERATED, post_id=post.id)
    return {
        "ok": True,
        "trend_id": trend_id,
        "post": post.model_dump(),
    }


