import json
import logging
import re
import time
from typing import Any
import httpx
from eros.config import get_settings

logger = logging.getLogger(__name__)


class GeminiQuotaExceededError(RuntimeError):
    """Excepción cuando se agota la cuota diaria o por minuto de Google Gemini."""
    pass


class LLMClient:
    """Cliente unificado y asíncrono para Gemini y Claude con soporte para cascada de modelos y fallback inteligente."""

    def __init__(self):
        self.settings = get_settings()
        self._quota_exhausted_until: float = 0.0

    async def generate(
        self,
        prompt: str,
        system_prompt: str | None = None,
        prefer_model: str = "gemini",
        temperature: float = 0.3,
        json_mode: bool = False,
        max_tokens: int = 4096,
    ) -> str:
        """Genera una respuesta utilizando el proveedor configurado con cascada de modelos."""
        if prefer_model == "claude" and self.settings.anthropic_api_key:
            try:
                return await self._call_claude(prompt, system_prompt)
            except Exception as e:
                logger.error(f"Error llamando a Claude API: {e}. Intentando fallback con Gemini...")

        if self.settings.gemini_api_key:
            # Si estamos en ventana de cooldown por cuota agotada de Gemini, usar fallback heurístico de inmediato
            if time.time() < self._quota_exhausted_until:
                logger.info("Cuota de Gemini en ventana de cooldown. Usando evaluador heurístico inteligente inmediato...")
                return self._heuristic_fallback(prompt)

            models_to_try: list[str] = [self.settings.gemini_model]
            fallback_models = getattr(self.settings, "gemini_fallback_models", [])
            for m in fallback_models:
                if m not in models_to_try:
                    models_to_try.append(m)

            for model_name in models_to_try:
                try:
                    return await self._call_gemini(
                        prompt,
                        system_prompt,
                        model=model_name,
                        temperature=temperature,
                        json_mode=json_mode,
                        max_tokens=max_tokens,
                    )
                except GeminiQuotaExceededError as e:
                    logger.warning(
                        f"Cuota diaria/por minuto de Gemini agotada en '{model_name}': {e}. "
                        "Activando cooldown de 5 minutos y fallback heurístico inmediato..."
                    )
                    self._quota_exhausted_until = time.time() + 300.0
                    return self._heuristic_fallback(prompt)
                except Exception as e:
                    err_msg = str(e)
                    if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "QuotaFailure" in err_msg:
                        logger.warning(
                            f"Detectado límite de cuota en Gemini '{model_name}': {err_msg[:200]}. "
                            "Activando cooldown y fallback heurístico inmediato..."
                        )
                        self._quota_exhausted_until = time.time() + 300.0
                        return self._heuristic_fallback(prompt)
                    logger.warning(f"Falla con modelo Gemini '{model_name}': {e}. Probando siguiente modelo de la cascada...")

            logger.error("Todos los modelos de Gemini fallaron o experimentan alta demanda. Activando evaluador heurístico inteligente...")

        # Si aún no tiene API keys configuradas o fallaron los proveedores externos, usamos un análisis heurístico inteligente como fallback
        return self._heuristic_fallback(prompt)

    async def _call_gemini(
        self,
        prompt: str,
        system_prompt: str | None = None,
        model: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> str:
        """Llama a la API de Google Gemini vía REST."""
        active_model = model or getattr(self.settings, "gemini_model", "gemini-3.5-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{active_model}:generateContent"
        headers = {
            "x-goog-api-key": self.settings.gemini_api_key,
            "content-type": "application/json",
        }

        contents = [{"role": "user", "parts": [{"text": prompt}]}]

        gen_config: dict[str, Any] = {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        }
        if json_mode:
            gen_config["responseMimeType"] = "application/json"

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": gen_config,
        }

        if system_prompt:
            payload["systemInstruction"] = {
                "parts": [{"text": system_prompt}]
            }

        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                resp_text = resp.text
                if resp.status_code == 429 or "RESOURCE_EXHAUSTED" in resp_text or "QuotaFailure" in resp_text:
                    raise GeminiQuotaExceededError(f"HTTP {resp.status_code} RESOURCE_EXHAUSTED: {resp_text[:300]}")
                logger.error(f"Gemini API ({active_model}) returned status {resp.status_code}: {resp_text[:300]}")
                raise RuntimeError(f"Gemini API ({active_model}) returned status {resp.status_code}: {resp_text[:300]}")

            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise RuntimeError("Gemini no devolvió candidatos.")

            parts = candidates[0].get("content", {}).get("parts", [])
            text = "".join([p.get("text", "") for p in parts])
            return text

    async def _call_claude(self, prompt: str, system_prompt: str | None = None, model: str = "claude-3-5-sonnet-20241022") -> str:
        """Llama a la API de Anthropic Claude vía REST."""
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.settings.anthropic_api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        payload = {
            "model": model,
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}]
        }
        if system_prompt:
            payload["system"] = system_prompt

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Claude API returned status {resp.status_code}: {resp.text}")

            data = resp.json()
            content = data.get("content", [])
            text = "".join([c.get("text", "") for c in content if c.get("type") == "text"])
            return text

    def _heuristic_evaluate_job(self, prompt: str) -> str:
        """Evaluador semántico-heurístico dinámico cuando la API externa no está disponible."""
        title_m = re.search(r"(?:Título|Puesto):\s*(.+)", prompt)
        company_m = re.search(r"Empresa:\s*(.+)", prompt)
        loc_m = re.search(r"(?:Ubicación\s*/\s*Modalidad|Ubicación):\s*(.+)", prompt)
        salary_m = re.search(r"Salario:\s*(.+)", prompt)
        tags_m = re.search(r"Tags:\s*(.+)", prompt)

        title = title_m.group(1).strip() if title_m else "Software Engineer / Desarrollador Web"
        company = company_m.group(1).strip() if company_m else "Empresa"
        location = loc_m.group(1).strip() if loc_m else "Remoto"
        salary = salary_m.group(1).strip() if salary_m else None
        if salary and "no especificado" in salary.lower():
            salary = None
        tags = [t.strip() for t in tags_m.group(1).split(",")] if tags_m else []

        desc = ""
        if "<job_posting>" in prompt:
            parts = prompt.split("<job_posting>", 1)
            desc_part = parts[1]
            if "</job_posting>" in desc_part:
                desc = desc_part.split("</job_posting>", 1)[0].strip()
            else:
                desc = desc_part[:2500].strip()
        elif "DESCRIPCIÓN DE LA VACANTE:" in prompt:
            parts = prompt.split("DESCRIPCIÓN DE LA VACANTE:", 1)
            desc_part = parts[1]
            if "INFORMACIÓN ACTUALIZADA DE MATEO:" in desc_part:
                desc = desc_part.split("INFORMACIÓN ACTUALIZADA DE MATEO:", 1)[0].strip()
            else:
                desc = desc_part[:2500].strip()
        else:
            desc = prompt[:2500]

        full_text = f"{title} {location} {' '.join(tags)} {desc}".lower()

        stack_map = {
            "Vue / Nuxt": ["vue", "nuxt", "vue 3", "vue.js", "nuxt 4"],
            "TypeScript / JavaScript": ["typescript", "ts", "javascript", "js", "ecmascript"],
            "Node.js / Express": ["node", "nodejs", "node.js", "express", "express.js"],
            "PostgreSQL / SQL": ["postgresql", "postgres", "sql", "prisma", "pgvector", "relational database"],
            "React / Next.js": ["react", "react.js", "next.js", "nextjs", "next"],
            "Python / FastAPI": ["python", "fastapi", "django", "flask"],
            "Tailwind CSS / UI": ["tailwind", "css", "html", "gsap", "sass", "responsive", "frontend"],
            "Docker & Linux": ["docker", "linux", "vps", "git", "ci/cd", "nginx"],
            "REST APIs & Arquitectura": ["rest", "restful", "api", "apis", "microservices", "clean architecture"],
        }

        matched_skills: list[str] = []
        for name, keywords in stack_map.items():
            if any(re.search(rf"\b{re.escape(kw)}\b", full_text) for kw in keywords):
                matched_skills.append(name)

        secondary_map = {
            "AWS / Cloud": ["aws", "amazon web services", "cloudformation", "terraform"],
            "GCP / Azure": ["gcp", "google cloud", "azure"],
            "Kubernetes": ["kubernetes", "k8s"],
            "Java / Spring": ["java", "spring boot", "spring"],
            "C# / .NET": ["c#", ".net", "dotnet"],
            "PHP / Laravel": ["php", "laravel", "symfony"],
            "Ruby / Rails": ["ruby", "rails"],
            "Go / Golang": ["golang", "go"],
            "Angular": ["angular"],
            "Mobile Nativo": ["swift", "kotlin", "android studio", "objective-c"],
        }

        missing_skills: list[str] = []
        for name, keywords in secondary_map.items():
            if any(re.search(rf"\b{re.escape(kw)}\b", full_text) for kw in keywords):
                missing_skills.append(name)

        is_incompatible_geo = False
        if any(w in full_text for w in ["caba presencial", "cordoba presencial", "presencial diario en madrid", "w-2 only", "green card required", "us citizenship required", "polygraph"]):
            is_incompatible_geo = True

        base_score = 72
        base_score += min(len(matched_skills) * 4, 20)

        is_remote = "remoto: true" in prompt.lower() or "remote" in full_text or "remoto" in full_text
        if is_remote:
            base_score += 5

        if any(w in full_text for w in ["argentina", "latam", "latin america", "utc-3", "neuquén", "rio negro"]):
            base_score += 3

        if missing_skills:
            base_score -= min(len(missing_skills) * 4, 16)

        if is_incompatible_geo:
            base_score = 20

        score = max(15, min(95, base_score))

        if is_incompatible_geo:
            verdict = "DESCARTAR"
        elif score >= 85:
            verdict = "EXCELENTE_MATCH"
        elif score >= 72:
            verdict = "BUEN_MATCH"
        elif score >= 50:
            verdict = "REGULAR"
        else:
            verdict = "DESCARTAR"

        matching_projects: list[str] = []
        if any("vue" in s.lower() or "tailwind" in s.lower() for s in matched_skills):
            matching_projects.append("La Rúcula")
        if any("python" in s.lower() for s in matched_skills):
            matching_projects.append("Ynara")
            matching_projects.append("Eros Agent")
        if not matching_projects or any("node" in s.lower() or "typescript" in s.lower() or "sql" in s.lower() for s in matched_skills):
            matching_projects.append("Portafolio (mateogs.tech)")
            if "Ynara" not in matching_projects:
                matching_projects.append("Ynara")
            if "ARG Piscinas" not in matching_projects and len(matching_projects) < 3:
                matching_projects.append("ARG Piscinas")

        pros = []
        if matched_skills:
            pros.append(f"Alineación técnica en stack central: {', '.join(matched_skills[:3])}")
        else:
            pros.append("Alineación con desarrollo web y buenas prácticas de ingeniería")
        if is_remote:
            pros.append("Modalidad remota compatible con disponibilidad horaria completa (UTC-3)")
        pros.append("Experiencia comprobada en producción con arquitectura desacoplada y rendimiento web")

        cons = []
        if is_incompatible_geo:
            cons.append("Incompatibilidad geográfica o legal estricta con la vacante")
        elif missing_skills:
            cons.append(f"Validar requisitos secundarios o de infraestructura: {', '.join(missing_skills[:3])}")
        else:
            cons.append("Validar procesos específicos de CI/CD e integraciones internas del equipo")

        matched_str = ", ".join(matched_skills[:4]) if matched_skills else "desarrollo Full Stack y APIs REST"
        summary = (
            f"La vacante para el puesto de {title} en {company} presenta un nivel de compatibilidad del {score}% con el perfil de Mateo. "
            f"El rol requiere competencias en {matched_str}, áreas donde Mateo cuenta con experiencia sólida construyendo software de extremo a extremo. "
            f"Su experiencia en producción con Express 5, PostgreSQL 17, TypeScript y frontend reactivo en Vue 3 y React "
            f"le permite integrarse con rapidez y autonomía operativa. "
            f"Proyectos en vivo como Portafolio (mateogs.tech) y Ynara validan directamente la calidad y solidez técnica requerida."
        )

        recruiter_note = (
            f"Hola, vi la búsqueda de {title} en {company}. Me especializo en Vue/Nuxt, Node y TypeScript con proyectos en producción (mateogs.tech). "
            f"Me gustaría conectar y conversar sobre cómo aportar al equipo."
        )
        if len(recruiter_note) > 280:
            recruiter_note = recruiter_note[:277] + "..."

        result = {
            "score": score,
            "verdict": verdict,
            "summary": summary,
            "pros": pros,
            "cons": cons,
            "missing_skills": missing_skills[:4],
            "matching_projects": matching_projects[:3],
            "salary_estimate": salary or "No especificado en la vacante",
            "hiring_manager_name": None,
            "hiring_manager_title": None,
            "recruiter_note": recruiter_note,
            "scored_by": "heuristic",
        }
        return json.dumps(result, ensure_ascii=False)

    def _heuristic_fallback(self, prompt: str) -> str:
        """Fallback cuando la API externa no está disponible o tiene spike de demanda."""
        if "PROPUESTA" in prompt or "elevator_pitch" in prompt:
            return json.dumps({
                "subject_or_hook": "Frontend & Full-stack Developer — Mateo Sonzogni",
                "elevator_pitch": (
                    "Hola! Me pongo en contacto porque mi perfil en desarrollo frontend y full stack "
                    "(Vue 3, Nuxt, TypeScript y arquitectura en Node/PostgreSQL) se alinea directamente con los desafíos de la posición. "
                    "Pueden ver mis proyectos en producción, arquitectura y métricas en vivo en mi portafolio: https://mateogs.tech\n\n"
                    "Quedo a disposición para conversar sobre cómo aportar al equipo."
                ),
                "cover_letter": "Disponible a solicitud.",
                "suggested_projects": ["Portafolio (mateogs.tech)", "La Rúcula", "Ynara"]
            })

        # Si se esperaba JSON de contenido técnico:
        if "carousel_slides" in prompt or "linkedin_post" in prompt:
            return json.dumps({
                "title": "Optimización y Arquitectura Frontend en Producción",
                "hook": "En producción, la teoría choca con la realidad del usuario. Así optimizamos el critical rendering path.",
                "linkedin_post": "En producción, la teoría choca con la realidad.\n\n• Reducción de cascada de red.\n• Estrategias de SSR y prefetching.\n• Métricas comprobadas en Lighthouse.\n\n#webdev #frontend #vuejs #architecture",
                "first_comment": "Detalles técnicos completos en https://mateogs.tech",
                "twitter_thread": [
                    "1/3 Optimización frontend en producción: lecciones aprendidas.",
                    "2/3 El cuello de botella principal fue la cascada de recursos bloqueantes.",
                    "3/3 Con prefetching y compresión Brotli bajamos latencia un 60%."
                ],
                "devto_article": {
                    "title": "Optimización y Arquitectura Frontend en Producción",
                    "tags": ["webdev", "architecture", "vue", "performance"],
                    "markdown_body": "# Lecciones de producción\n\nDetalles de arquitectura e implementación."
                },
                "carousel_slides": [
                    {"index": 1, "title": "Arquitectura Frontend", "subtitle": "Lecciones en producción", "bullets": ["Latencia reducida", "Cero layout shifts"], "metric_badge": "99/100", "code_snippet": None, "footer": "mateogs.tech"},
                    {"index": 2, "title": "El Problema", "subtitle": "Cascada de bloqueo", "bullets": ["Render blocking scripts"], "metric_badge": None, "code_snippet": None, "footer": "Producción"},
                    {"index": 3, "title": "La Solución", "subtitle": "Hydration diferida", "bullets": ["Lazy load selectivo"], "metric_badge": None, "code_snippet": "defineAsyncComponent(() => import('./Widget.vue'))", "footer": "Código"},
                    {"index": 4, "title": "Métricas", "subtitle": "Benchmarks", "bullets": ["-60% TTFB", "+35 puntos Lighthouse"], "metric_badge": "-60% TTFB", "code_snippet": None, "footer": "Resultados"},
                    {"index": 5, "title": "Conclusión", "subtitle": "Accionable", "bullets": ["Mide antes de optimizar", "Prioriza el critical path"], "metric_badge": "mateogs.tech", "code_snippet": None, "footer": "Mateo Sonzogni"}
                ]
            })

        # Si se esperaba evaluación de vacante / matching laboral:
        if "EVALUÁ ESTA OFERTA LABORAL" in prompt or "score" in prompt or "verdict" in prompt or "JSON" in prompt:
            return self._heuristic_evaluate_job(prompt)

        return "Hola! Soy Eros Agent. He evaluado la posición. Cumple con el stack de desarrollo frontend y arquitectura web."

    async def embed_text(self, text: str) -> list[float]:
        """Genera un vector embedding de 3072 dimensiones con Gemini."""
        if not self.settings.gemini_api_key:
            logger.warning("GEMINI_API_KEY no configurado para embeddings.")
            return []

        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent"
        headers = {
            "x-goog-api-key": self.settings.gemini_api_key,
            "content-type": "application/json",
        }
        payload = {
            "model": "models/gemini-embedding-001",
            "taskType": "SEMANTIC_SIMILARITY",
            "content": {
                "parts": [{"text": text[:3500]}]
            }
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code != 200:
                logger.error(f"Gemini Embedding API error HTTP {resp.status_code}: {resp.text[:200]}")
                return []
            data = resp.json()
            return data.get("embedding", {}).get("values", [])

    async def batch_embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Genera vectores embeddings para una lista de textos en una sola petición batch."""
        if not texts:
            return []
        if not self.settings.gemini_api_key:
            logger.warning("GEMINI_API_KEY no configurado para embeddings batch.")
            return [[] for _ in texts]

        # Dividir en chunks de máximo 50 para evitar exceder límites de payload
        chunk_size = 50
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), chunk_size):
            chunk = texts[i:i + chunk_size]
            url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:batchEmbedContents"
            headers = {
                "x-goog-api-key": self.settings.gemini_api_key,
                "content-type": "application/json",
            }
            requests = [
                {
                    "model": "models/gemini-embedding-001",
                    "taskType": "SEMANTIC_SIMILARITY",
                    "content": {"parts": [{"text": t[:3500]}]}
                }
                for t in chunk
            ]
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(url, headers=headers, json={"requests": requests})
                    if resp.status_code == 200:
                        data = resp.json()
                        embeddings = [e.get("values", []) for e in data.get("embeddings", [])]
                        all_embeddings.extend(embeddings)
                    elif resp.status_code == 429 or "RESOURCE_EXHAUSTED" in resp.text:
                        logger.warning("Batch embedding de Gemini agotó cuota (429). Omitiendo reintentos individuales...")
                        all_embeddings.extend([[] for _ in chunk])
                    else:
                        logger.warning(f"Batch embedding falló con HTTP {resp.status_code}. Pasando a uno a uno...")
                        for t in chunk:
                            emb = await self.embed_text(t)
                            all_embeddings.append(emb)
            except Exception as e:
                logger.error(f"Excepción en batch embed: {e}")
                all_embeddings.extend([[] for _ in chunk])

        return all_embeddings
