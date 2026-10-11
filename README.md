# Eros Career OS — Autonomous Job Hunter, CV Matcher & Content Engine

Sistema multiagente autónomo personal para **búsqueda de empleo tech** (remoto USD / LATAM) y **creación de contenido técnico omnicanal** (LinkedIn, X/Twitter, Dev.to, Carousels PDF). Diseñado para operar 100% dentro del nivel gratuito de Google Gemini Free Tier ($0 de coste operativo) y distribuirse mediante **n8n** en tu propio VPS con Coolify.

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
- **Webhook de n8n:** Al aprobar un borrador (desde Telegram o la API), Eros despacha el payload estructurado a n8n, el cual lo publica de forma automatizada en LinkedIn, X/Twitter y Dev.to.

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
| `POST` | `/api/content/posts/{id}/publish` | Aprueba y despacha el payload al webhook de n8n. |
| `GET` | `/api/content/carousel/{id}/html` | Visor HTML interactivo e imprimible del carousel. |
| `POST` | `/api/webhooks/n8n/callback` | Callback para que n8n confirme la publicación externa. |
| `GET` | `/api/jobs` | Lista de ofertas laborales escaneadas y evaluadas. |
| `POST` | `/api/scan` | Dispara escaneo de empleos. |
| `POST` | `/api/cv/{job_id}` | Genera CV Harvard ATS adaptado para una vacante. |

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

---

## 🐳 Despliegue en VPS (Coolify)

1. Repositorio en GitHub: `MateoGs013/eros-agent`.
2. En Coolify:
   - Crear aplicación tipo **Dockerfile**.
   - Configurar variables de entorno (`GEMINI_API_KEY`, `EROS_API_KEY`, `N8N_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID`, `PORTFOLIO_API_URL`).
   - Puerto de escucha: `8000`.
3. Interconexión interna:
   - Portafolio Express (`HUNTER_API_URL=http://eros-agent:8000`).
   - n8n (`flow.mateogs.tech`) recibe webhooks desde `eros-agent` y confirma mediante callback.

