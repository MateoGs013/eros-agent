# Eros Career OS — Autonomous Job Hunter, CV Matcher & Portfolio Writer

Sistema multiagente autónomo personal para **búsqueda de empleo tech** (remoto USD / LATAM) y **artículos técnicos para el portafolio** (mateogs.tech, en español y en inglés). Diseñado para operar 100% dentro del nivel gratuito de Google Gemini Free Tier ($0 de coste operativo), en tu propio VPS con Coolify; **n8n** solo dispara el escaneo diario de vacantes.

## Reglas que Eros respeta (auditoría 2-nov-2026)

- **Correos reales o ninguno.** Eros nunca arma una dirección (`jobs@empresa.com`). Cada correo guarda su fuente en `contact_email_source`: `posting` (publicado en el aviso), `company_site` (en el sitio de la empresa, mismo dominio), `hunter` (Hunter.io), `manual` (escrito a mano) o `unknown` (heredado, sin fuente: hay que escribir la dirección para enviar). De un nombre genérico ("Empresa Confidencial") no se infiere ningún dominio.
- **Una postulación se envía una sola vez.** Antes de enviar, Eros marca la vacante como «enviando» de forma atómica; manda `Idempotency-Key: apply-<job_id>` a n8n. Si el envío se corta, la vacante queda en `send_state: "unknown"` y no se reenvía sin `force_retry`. Sin proveedor (n8n de postulaciones o SMTP) no se envía ni se marca como postulada.
- **El escaneo no borra historial.** Lo descartado y lo postulado se conservan; lo borrado a mano se recuerda (`seen_jobs`) para que no vuelva como nuevo. La misma vacante en dos fuentes (empresa + título normalizados) se guarda una vez.
- **Sin IA no se inventa.** Sin Gemini/Claude, la evaluación de vacantes usa una estimación heurística marcada `scored_by: "heuristic"` que nunca deja una vacante en `saved` ni escribe notas de conexión. CV y pitch fallan con 503 (`IA no disponible`) y un artículo deja su tarea en `failed` (`llm_unavailable`) en vez de rellenar texto.
- **Eros no publica.** Escribe los artículos y los devuelve; la API del portafolio es la que los publica. Ya no hay publicación en LinkedIn ni en X.


---

## 🌟 Módulos y Capacidades

### 1. ✍️ Artículos para el portafolio (`eros.content`)
- **Un artículo largo por pedido, en español y en inglés.** Primero escribe el artículo en español (900 a 1500 palabras, en primera persona como Mateo, en rioplatense) con el perfil real del portafolio y, si se piden, un proyecto o una tendencia del Radar; después lo traduce al inglés de forma fiel, con la misma estructura.
- **Sin tema, elige uno.** Anclado en un proyecto o en el stack real, y distinto de los títulos que el portafolio ya publicó (`avoid_titles`).
- **Nunca inventa.** Ni métricas, ni porcentajes, ni clientes: solo cita los proyectos reales del perfil.
- **Solo el Markdown que el portafolio muestra:** subtítulos `##` y `###` (el título va aparte), párrafos, listas, citas, bloques de código, código en línea, negrita, itálica y enlaces `http`/`https`. Sin tablas, imágenes, HTML crudo ni emojis. Eros valida todo eso al recibir la respuesta: si no cumple, la tarea falla con el motivo (un `#` inicial se saca solo).

### 2. 🎯 Autonomous Job Hunter & CV Matcher (`eros.hunter`)
- **Multi-Fuente:** Get on Board, RemoteOK, Hacker News ("Who is hiring?").
- **Scoring y Match:** Evaluación semántica contra tu perfil y proyectos reales (0–100%).
- **CV Harvard ATS:** Generación de currículum a medida para la vacante con versión HTML imprimible.
- **Pitches y Cover Letters:** Redacción instantánea de propuestas adaptadas.

### 3. ⚡ n8n: escaneo diario y postulaciones
- **Escaneo diario:** el workflow de `n8n/` (`Eros · Búsqueda diaria de vacantes`) corre a las 08:00 y 18:00 y llama a `POST /api/scan?evaluate=true&notify=true` (las vacantes desde `MATCH_MIN_SCORE` llegan por Telegram) con la credencial *Header Auth* `n8n → Eros` (`Authorization` = `Bearer <EROS_API_KEY>`). No lee `$env` (n8n 2.x lo bloquea en los nodos por defecto): falta asignarle la credencial al importarlo.
- **Postulaciones por correo (opcional):** si está `N8N_APPLICATION_WEBHOOK_URL`, Eros manda ahí cada postulación con `N8N_WEBHOOK_SECRET` en el header `X-N8N-Secret`. Ese webhook no está en el workflow de `n8n/`: es el que tengas armado para mandar los correos (por ejemplo con Gmail), y **tiene que validarlo** con *Authentication → Header Auth* (credencial `Eros → n8n`, `X-N8N-Secret` = el mismo valor). Sin esa URL, Eros usa SMTP; sin ninguno de los dos, no envía.

### 4. 🤖 Centro de Control por Telegram (`TelegramBot`)
- `/buscar` — Dispara un escaneo de vacantes en todas las fuentes.
- `/ofertas` — Muestra las mejores vacantes detectadas.
- `/status` — Resumen en vivo de vacantes y del webhook de postulaciones.
- `/perfil` — Muestra el perfil sincronizado del portafolio.
- `/sync` — Sincroniza en tiempo real tu perfil desde `https://api.mateogs.tech/api`.

---

## 📝 Artículos: contrato con el portafolio

`POST /api/articles/generate` (misma autenticación que el resto: `Authorization: Bearer <EROS_API_KEY>`, `X-Eros-Key` o la sesión). Todo el cuerpo es opcional:

```json
{
  "topic": "string o null (máx. 300)",
  "project_slug": "string o null",
  "trend_id": "string o null",
  "angle": "string o null (máx. 1000)",
  "avoid_titles": ["títulos ya publicados (máx. 300, cada uno de hasta 200)"]
}
```

Responde **202** igual que `/api/scan`: `{ok, task_id, kind: "article", status, started_at, already_running, status_url}`. Se escribe un artículo a la vez: un segundo pedido mientras hay uno en curso devuelve esa misma tarea con `already_running: true`. Con `trend_id`, la tendencia del Radar queda `GENERATED` cuando el artículo termina.

`GET /api/tasks/{task_id}` con `status: "done"` trae en `result`:

```json
{
  "topic": "string",
  "project_slug": "string o null",
  "trend_id": "string o null",
  "tags": ["nuxt", "postgres"],
  "es": {"title": "máx. 160", "summary": "máx. 400", "markdown": "string"},
  "en": {"title": "string", "summary": "string", "markdown": "string"},
  "model": "modelo de Gemini que lo escribió"
}
```

Con `status: "failed"`, `error` explica el motivo en castellano y `error_code` lo resume:

| `error_code` | Qué pasó |
|---|---|
| `llm_unavailable` | `Gemini no está disponible: …` (sin clave, cuota agotada o todos los modelos fallaron). |
| `llm_output_invalid` | La respuesta no sirve: `El artículo vino incompleto: …`, `El artículo no respeta el formato del portafolio: …` o lo mismo para la traducción al inglés. |
| `trend_not_found` | No existe esa tendencia en el Radar. |
| `project_not_found` | El proyecto no está en el perfil, ni después de sincronizarlo. |

Las tareas viven en memoria: si Eros se reinicia, `GET /api/tasks/{id}` responde 404.

---

## 📡 Endpoints de la API (FastAPI)

| Método | Endpoint | Descripción |
|---|---|---|
| `POST` | `/api/articles/generate` | **202** con `task_id`: escribe un artículo para el portafolio (ver arriba). |
| `GET` | `/api/jobs` | Lista de ofertas (incluye `contact_email_source`, `scored_by`, `send_state`). |
| `POST` | `/api/scan` | **202** con `task_id`: escanea en segundo plano. Un segundo pedido mientras corre devuelve la misma tarea (`already_running: true`). `?evaluate=true` evalúa las nuevas y `&notify=true` avisa por Telegram las que pasan `MATCH_MIN_SCORE`. |
| `POST` | `/api/evaluate` | **202** con `task_id`: evalúa pendientes en segundo plano. |
| `GET` | `/api/tasks/{task_id}` | Estado de la tarea: `running`, `done` (con `result`) o `failed` (con `error` y `error_code`). |
| `POST` | `/api/purge` | Marca como descartadas (sin borrar) las incompatibles. Nunca toca las postuladas. |
| `POST` | `/api/jobs/{id}/find-email` | Busca un correo real; devuelve `contact_email`, `contact_email_source`, `source`, `found`. |
| `PATCH` | `/api/jobs/{id}/contact-email` | Correo escrito a mano (`contact_email_source: "manual"`). |
| `GET` | `/api/jobs/{id}/apply-preview` | Vista previa con `contact_email_source`, `contact_email_verified`, `requires_manual_email`, `pitch_source`. |
| `POST` | `/api/jobs/{id}/apply-email` | Envía la postulación con el CV que manda el portafolio en `cv` (obligatorio). Errores con `detail` + `error_code` (ver abajo). |
| `POST` | `/api/cv/{job_id}` | Genera CV Harvard ATS adaptado (503 sin IA). |
| `GET` | `/api/jobs/{id}/cv/html` · `/pdf` | Solo el CV ya guardado. Requiere la clave o `?token=` firmado de esa vacante. Nunca genera con IA. |
| `POST` | `/api/radar/scan` · `GET` `/api/radar/trends` | Radar de tendencias (Hacker News, Dev.to, GitHub): punto de partida de los artículos con `trend_id`. |
| `GET` | `/health` | 200 si la base responde, 503 si no. |

### El CV de `apply-email`

Eros no adjunta un CV propio. El admin del portafolio arma el CV Harvard ATS de la vacante desde su base,
lo imprime a PDF (una página A4, cota de 248–265 mm) y lo manda en el cuerpo:

```json
{ "to_email": "…", "subject": "…", "body": "…", "channel": "n8n", "confirmed": true, "force_retry": false,
  "cv": { "filename": "CV_….pdf", "pdf_base64": "…", "text": "…", "sha256": "…", "lang": "es", "height_mm": 256.4 } }
```

`src/eros/hunter/attached_cv.py` lo valida (base64, `%PDF-`, hasta 2 MB, sha256, nombre sin rutas, texto) antes de
tomar la marca de envío. n8n recibe esos bytes en `cv_pdf_base64`, más `cv_filename`, `cv_text`, `cv_sha256` y `cv_lang`;
`cv_data` y `cv_html_url` van en `null`. SMTP adjunta los mismos bytes. Telegram ya no postula: responde que se postula
desde el admin.

### Errores de `apply-email`

| `error_code` | HTTP | Qué pasó |
|---|---|---|
| `already_applied` / `send_in_progress` | 409 | Ya se postuló / hay un envío en curso. |
| `send_outcome_unknown` | 409 / 504 | Un envío se cortó: revisar «Enviados»; reintentar con `force_retry: true`. |
| `missing_email` / `invalid_email` / `unverified_email` | 422 | Falta, es inválido o no se sabe de dónde salió: escribir la dirección (`to_email`). |
| `cv_required` / `invalid_cv` | 422 | Falta el `cv` del portafolio o no es válido. No se envió nada ni se tomó la marca. |
| `requires_confirmation` | 428 | Correo encontrado automáticamente: mandar `confirmed: true`. |
| `no_provider` | 503 | No hay `N8N_APPLICATION_WEBHOOK_URL` ni `SMTP_HOST`. No se marcó como postulada. |
| `provider_rejected` | 502 | n8n/SMTP rechazó el envío (seguro que no salió). |

---

## 💻 Comandos CLI

```powershell
# 1. Escribir un artículo por CLI (muestra los títulos; no lo guarda ni lo publica):
python -m eros.main --articulo "Por qué el portafolio se renderiza en el servidor"

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
   - Configurar variables de entorno (`GEMINI_API_KEY`, `EROS_API_KEY`, `N8N_APPLICATION_WEBHOOK_URL`, `N8N_WEBHOOK_SECRET`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID`, `PORTFOLIO_API_URL`). Ver `.env.example`. `N8N_WEBHOOK_URL` ya no se usa: si quedó cargada, Eros la ignora y se puede borrar.
   - Puerto de escucha: `8000`. El contenedor trae `HEALTHCHECK` contra `/health`.
   - Montar un volumen persistente en `/app/data` (ahí vive la base SQLite).
3. Interconexión interna:
   - Portafolio Express (`HUNTER_API_URL=http://eros-agent:8000`): pide los artículos y los publica.
   - n8n (`flow.mateogs.tech`) llama a Eros dos veces por día para escanear y, si está configurado, recibe las postulaciones por correo.
