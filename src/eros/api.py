import asyncio
from contextlib import asynccontextmanager
import logging
from typing import Any
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from eros.hunter.engine import HunterEngine
from eros.models import JobStatus

logger = logging.getLogger("eros.api")

engine = HunterEngine()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicializar base de datos y sincronizar perfil inicial
    await engine.initialize()
    logger.info("Eros Hunter API inicializada.")
    yield


app = FastAPI(
    title="Eros Job Hunter API",
    version="0.1.0",
    description="API interna del Agente Job Hunter para la consola de administración",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StatusUpdateRequest(BaseModel):
    status: JobStatus


@app.get("/health")
async def health():
    return {"ok": True, "service": "eros-agent"}


@app.get("/api/stats")
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


@app.get("/api/jobs")
async def list_jobs(
    min_score: int = Query(0, ge=0, le=100),
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200)
):
    """Lista las ofertas con filtros de puntaje y estado."""
    jobs = await engine.storage.list_matched_jobs(min_score=min_score, limit=limit)
    if status:
        jobs = [j for j in jobs if j.status.value == status]
    return {"data": jobs, "count": len(jobs)}


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str):
    """Devuelve el detalle de una oferta."""
    job = await engine.storage.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Oferta no encontrada")
    return {"data": job}


@app.post("/api/scan")
async def trigger_scan(evaluate: bool = True):
    """Dispara un escaneo en vivo en Get on Board, RemoteOK y Hacker News."""
    scan_res = await engine.run_scan()
    eval_res = []
    if evaluate:
        eval_res = await engine.evaluate_pending_jobs(limit=8)

    return {
        "ok": True,
        "scanned": scan_res["total_found"],
        "new_jobs": scan_res["new_jobs"],
        "evaluated_count": len(eval_res)
    }


@app.post("/api/evaluate")
async def trigger_evaluate(limit: int = 10):
    """Evalúa las vacantes pendientes con Gemini."""
    eval_res = await engine.evaluate_pending_jobs(limit=limit)
    return {
        "ok": True,
        "evaluated_count": len(eval_res),
        "evaluated": [{"id": j.id, "title": j.title, "score": m.score, "verdict": m.verdict} for j, m in eval_res]
    }


@app.post("/api/pitch/{job_id}")
async def generate_pitch(job_id: str):
    """Genera una propuesta personalizada conectada con el portafolio."""
    pitch = await engine.generate_pitch_for_job(job_id)
    if not pitch:
        raise HTTPException(status_code=404, detail="No se pudo generar el pitch para la oferta")
    return {"data": pitch}


@app.post("/api/cv/{job_id}")
async def generate_cv(job_id: str):
    """Genera un CV adaptado Harvard ATS para la vacante."""
    result = await engine.generate_cv_for_job(job_id)
    if not result:
        raise HTTPException(status_code=404, detail="No se pudo generar el CV para la oferta")
    cv_data, html = result
    return {"data": cv_data, "html": html}


@app.get("/api/cv/{job_id}/html", response_class=HTMLResponse)
async def get_cv_html(job_id: str):
    """Devuelve la vista HTML imprimible del CV de la vacante."""
    html = await engine.get_cv_html_for_job(job_id)
    if not html:
        raise HTTPException(status_code=404, detail="CV no disponible para esta oferta")
    return HTMLResponse(content=html, media_type="text/html")


@app.patch("/api/jobs/{job_id}/status")
async def update_job_status(job_id: str, body: StatusUpdateRequest):
    """Actualiza el estado de la vacante (APPLIED, DISCARDED, SAVED, etc.)."""
    job = await engine.storage.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Oferta no encontrada")
    
    await engine.storage.update_job_status(job_id, body.status)
    return {"ok": True, "job_id": job_id, "new_status": body.status}


@app.post("/api/profile/sync")
async def sync_profile():
    """Fuerza la sincronización del perfil desde la API del portafolio."""
    profile = await engine.sync_profile()
    return {"ok": True, "profile": profile}

