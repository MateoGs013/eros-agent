# Eros Career OS — Autonomous Job Hunter, CV Matcher & Content Engine

Sistema multiagente autónomo personal para **búsqueda de empleo tech** (remoto USD / LATAM) y **creación de contenido técnico omnicanal** (LinkedIn, X/Twitter, Dev.to, Carousels PDF). Diseñado para operar 100% dentro del nivel gratuito de Google Gemini Free Tier ($0 de coste operativo) y distribuirse mediante **n8n** en tu propio VPS con Coolify.

## Reglas que Eros respeta (auditoría 2-nov-2026)

- **Correos reales o ninguno.** Eros nunca arma una dirección (`jobs@empresa.com`). Cada correo guarda su fuente en `contact_email_source`: `posting` (publicado en el aviso), `company_site` (en el sitio de la empresa, mismo dominio), `hunter` (Hunter.io), `manual` (escrito a mano) o `unknown` (heredado, sin fuente: hay que escribir la dirección para enviar). De un nombre genérico ("Empresa Confidencial") no se infiere ningún dominio.
- **Una postulación se envía una sola vez.** Antes de enviar, Eros marca la vacante como «enviando» de forma atómica; manda `Idempotency-Key: apply-<job_id>` a n8n. Si el envío se corta, la vacante queda en `send_state: "unknown"` y no se reenvía sin `force_retry`. Sin proveedor (n8n de postulaciones o SMTP) no se envía ni se marca como postulada.
- **El escaneo no borra historial.** Lo descartado y lo postulado se conservan; lo borrado a mano se recuerda (`seen_jobs`) para que no vuelva como nuevo. La misma vacante en dos fuentes (empresa + título normalizados) se guarda una vez.
- **Sin IA no se inventa.** Sin Gemini/Claude, la evaluación de vacantes usa una estimación heurística marcada `scored_by: "heuristic"` que nunca deja una vacante en `saved` ni escribe notas de conexión. CV, pitch y posts fallan con 503 (`IA no disponible`) en vez de rellenar texto.
- **Publicar respeta el canal** y queda `published` recién cuando n8n confirma por el callback.


---

## 🌟 Módulos y Capacidades

### 1. 📱 Content Writer & Omnichannel Engine (`eros.content`)
- **Generación Omnicanal de Alta Densidad Técnica:** A partir de un tema de ingeniería o un proyecto de tu portafolio, redacta simultáneamente:
  - **LinkedIn Post:** Hook magnético, contexto del problema, solución técnica con viñetas limpias, métricas reales, CTA de debate y hashtags.
  - **Primer Comentario:** Enlace contextual a https://mateogs.tech o al repositorio respectivo.
  - **Hilo de Twitter/X:** Hilo conciso de 3 a 5 tweets (< 275 caracteres cada uno).
  - **Artículo Técnico para Dev.to:** Markdown completo con encabezados, tags y bloques de código.
- **5 Pilares Temáticos Configurados:**
  - `architecture`: Decisiones de diseño (SSR vs SPA, monorrepo, microservicios, edge caching).
  - `production_lessons`: Bugs reales en producción, incidentes de CORS, políticas CSP (`eval`), hidratación.
  - `performance_optimization`: Core Web Vitals, Lighthouse 99-100, bundle splitting, optimización de fuentes e imágenes.
  - `ai_agent_ops`: Arquitecturas de agentes autónomos, LLMs con Gemini Free Tier, prompt engineering y tool calling.
  - `fullstack_engineering`: TypeScript end-to-end, Vue 3 / Nuxt 3, Node / Express, PostgreSQL.

### 2. 🎠 Carousel Visual Studio (`CarouselRenderer`)
- **Diapositivas 4:5 (1080 x 1350 px):** Relación de aspecto óptima para el algoritmo de LinkedIn.
- **Estética Técnica Dark Noir:** Fondo obsidiana (`#07090e`), acentos en esmeralda neón (`#10b981`) y cian eléctrico (`#06b6d4`), tipografía Inter y bloques de código en Fira Code.
- **Visor Interactivo Web:** Navegación por teclado (flechas ◀ / ▶) y pills interactivos.
- **Impresión Directa a PDF de LinkedIn:** Incluye reglas CSS `@media print` (`@page { size: 1080px 1350px; margin: 0; }`) para exportar directamente a PDF listo para adjuntar como documento en LinkedIn.

### 3. ⚡ Distribución y Orquestación con n8n (`ContentDispatcher`)
- **Human-in-the-Loop:** Nada se publica sin aprobación explícita.
- **Webhook de n8n:** Al aprobar un borrador (desde Telegram o la API), Eros despacha el payload a `N8N_WEBHOOK_URL` con el `channel` pedido (`all`, `linkedin`, `twitter`, `devto`) y solo el texto de esos canales. n8n publica y confirma con `POST /api/webhooks/n8n/callback` (`{post_id, status: "published", channel}`).
- **Seguridad del webhook:** Eros manda `N8N_WEBHOOK_SECRET` en el header `X-N8N-Secret` (contenido y postulaciones). **Los webhooks de n8n tienen que validarlo**: en el nodo Webhook, *Authentication → Header Auth* con una credencial `X-N8N-Secret` = el mismo valor. El workflow de `n8n/` ya lo trae configurado (falta asignarle la credencial). Sin eso, cualquiera que conozca la URL puede publicar en tus redes.

### 4. 🎯 Autonomous Job Hunter & CV Matcher (`eros.hunter`)
- **Multi-Fuente:** Get on Board, RemoteOK, Hacker News ("Who is hiring?").
- **Scoring y Match:** Evaluación semántica contra tu perfil y proyectos reales (0–100%).
- **CV Harvard ATS:** Generación de currículum a medida para la vacante con versión HTML imprimible.
- **Pitches y Cover Letters:** Redacción instantánea de propuestas adaptadas.

### 5. 🤖 Centro de Control por Telegram (`TelegramBot`)
- `/post <tema>` — Genera un post omnicanal instantáneo y te envía la vista previa con botones para aprobar o ver el carousel.
- `/pendientes` — Lista borradores esperando tu visto bueno.
- `/buscar` — Dispara un escaneo de vacantes en todas las fuentes.
- `/ofertas` — Muestra las mejores vacantes detectadas.
- `/status` — Resumen en vivo de vacantes y publicaciones.
- `/sync` — Sincroniza en tiempo real tu perfil desde `https://api.mateogs.tech/api`.

---

## 📡 Endpoints de la API (FastAPI)

| Método | Endpoint | Descripción |
|---|---|---|
| `POST` | `/api/content/generate` | Genera una publicación omnicanal (LinkedIn + X + Dev.to + 5 slides). |
| `GET` | `/api/content/posts` | Lista publicaciones (filtro por `status: draft, approved, published`). |
| `GET` | `/api/content/posts/{id}` | Detalle completo de una publicación. |
| `PATCH` | `/api/content/posts/{id}/status` | Actualiza estado (`draft`, `approved`, `published`, `rejected`). |
| `POST` | `/api/content/posts/{id}/publish` | Body `{channel}`. Despacha a n8n → `status: "dispatched"` (o `approved_local` sin n8n). 409 si ya está publicada, rechazada o ese canal ya se despachó. |
| `GET` | `/api/content/carousel/{id}/html` | Visor HTML interactivo e imprimible del carousel. |
| `POST` | `/api/webhooks/n8n/callback` | Callback para que n8n confirme la publicación externa. |
| `GET` | `/api/jobs` | Lista de ofertas (incluye `contact_email_source`, `scored_by`, `send_state`). |
| `POST` | `/api/scan` | **202** con `task_id`: escanea en segundo plano. Un segundo pedido mientras corre devuelve la misma tarea (`already_running: true`). |
| `POST` | `/api/evaluate` | **202** con `task_id`: evalúa pendientes en segundo plano. |
| `GET` | `/api/tasks/{task_id}` | Estado de la tarea: `running`, `done` (con `result`) o `failed` (con `error`). |
| `POST` | `/api/purge` | Marca como descartadas (sin borrar) las incompatibles. Nunca toca las postuladas. |
| `POST` | `/api/jobs/{id}/find-email` | Busca un correo real; devuelve `contact_email`, `contact_email_source`, `source`, `found`. |
| `PATCH` | `/api/jobs/{id}/contact-email` | Correo escrito a mano (`contact_email_source: "manual"`). |
| `GET` | `/api/jobs/{id}/apply-preview` | Vista previa con `contact_email_source`, `contact_email_verified`, `requires_manual_email`, `pitch_source`. |
| `POST` | `/api/jobs/{id}/apply-email` | Envía la postulación. Errores con `detail` + `error_code` (ver abajo). |
| `POST` | `/api/cv/{job_id}` | Genera CV Harvard ATS adaptado (503 sin IA). |
| `GET` | `/api/jobs/{id}/cv/html` · `/pdf` | Solo el CV ya guardado. Requiere la clave o `?token=` firmado de esa vacante. Nunca genera con IA. |
| `GET` | `/health` | 200 si la base responde, 503 si no. |

### Errores de `apply-email`

| `error_code` | HTTP | Qué pasó |
|---|---|---|
| `already_applied` / `send_in_progress` | 409 | Ya se postuló / hay un envío en curso. |
| `send_outcome_unknown` | 409 / 504 | Un envío se cortó: revisar «Enviados»; reintentar con `force_retry: true`. |
| `missing_email` / `invalid_email` / `unverified_email` | 422 | Falta, es inválido o no se sabe de dónde salió: escribir la dirección (`to_email`). |
| `requires_confirmation` | 428 | Correo encontrado automáticamente: mandar `confirmed: true`. |
| `no_provider` | 503 | No hay `N8N_APPLICATION_WEBHOOK_URL` ni `SMTP_HOST`. No se marcó como postulada. |
| `provider_rejected` | 502 | n8n/SMTP rechazó el envío (seguro que no salió). |

---

## 💻 Comandos CLI

```powershell
# 1. Generar contenido omnicanal directamente por CLI:
python -m eros.main --post "Por qué migramos de React a Nuxt 3 y SSR"

# 2. Iniciar el servidor API (puerto 8000):
python -m eros.main --server --port 8000

# 3. Iniciar modo demonio (Servidor API + Bot de Telegram en paralelo):
python -m eros.main --daemon --port 8000

# 4. Escanear vacantes laborales:
python -m eros.main --scan

# 5. Evaluar vacantes pendientes con IA:
python -m eros.main --evaluate
```

## 🧪 Tests

```powershell
python scripts/run_tests_offline.py
```

Corre toda la suite sin red (cualquier conexión que no sea a localhost falla), con las claves en blanco y una base SQLite temporal. No lee el `.env`.

---

## 🐳 Despliegue en VPS (Coolify)

1. Repositorio en GitHub: `MateoGs013/eros-agent`.
2. En Coolify:
   - Crear aplicación tipo **Dockerfile**.
   - Configurar variables de entorno (`GEMINI_API_KEY`, `EROS_API_KEY`, `N8N_WEBHOOK_URL`, `N8N_APPLICATION_WEBHOOK_URL`, `N8N_WEBHOOK_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID`, `PORTFOLIO_API_URL`). Ver `.env.example`.
   - Puerto de escucha: `8000`. El contenedor trae `HEALTHCHECK` contra `/health`.
   - Montar un volumen persistente en `/app/data` (ahí vive la base SQLite).
3. Interconexión interna:
   - Portafolio Express (`HUNTER_API_URL=http://eros-agent:8000`).
   - n8n (`flow.mateogs.tech`) recibe webhooks desde `eros-agent` y confirma mediante callback.

