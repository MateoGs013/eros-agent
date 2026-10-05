# Eros Agent — Autonomous Job Hunter & CV Matcher

Agente personal autónomo diseñado para monitorear vacantes de empleo (remoto USD / LATAM), evaluar compatibilidad técnica en tiempo real contra el portafolio y CV de Mateo usando Google Gemini, y gestionar postulaciones directamente desde el **Panel Admin del Portafolio** (`https://api.mateogs.tech/admin`).

---

## Características

- 🔄 **Sincronización Viva con tu Portafolio:** Consume tu API (`https://api.mateogs.tech/api`) para obtener siempre tu stack, experiencia, métricas y proyectos reales (La Rúcula, Ynara, etc.) sin hardcodear datos.
- 🔎 **Multi-Fuente de Vacantes:**
  - **Get on Board API:** Puestos tech para LATAM y remoto.
  - **RemoteOK API:** Puestos remotos globales en USD.
  - **Hacker News ("Who is hiring?"):** Puestos directos en startups y fundadores de EE.UU.
- 🧠 **Evaluación Semántica con IA (Gemini Flash Lite):**
  - Scoring de compatibilidad (0–100%).
  - Filtro duro de exclusión (requisitos incompatibles, on-site estricto en el exterior).
  - Puntos a favor, puntos en contra y proyectos clave de tu portafolio a destacar.
- ✉️ **Generador de Pitches Personalizados:** Redacta cover letters y mensajes directos en español o inglés conectando los requisitos de la vacante con tus proyectos reales y el enlace a https://mateogs.tech.
- 💻 **Centro de Mando Integrado en el Panel Admin:**
  - Pestaña `job hunter` en la consola técnica de administración (`/admin`).
  - Filtros rápidos por vacantes de alto match (🔥 ≥ 70%), postuladas y descartadas.
  - Botón de escaneo en vivo (`[⚡ Escanear Ofertas]`).
  - Redacción instantánea de pitches con IA (`[⚡ Generar Pitch con IA]`).
  - Botón directo para copiar la propuesta adaptada al portapapeles.
  - Estado de postulación (`[✓ Marcar Postulado]` y `[Descartar]`).
- 🐳 **Listo para VPS y Coolify:** Contenedor Docker multi-stage con FastAPI y SQLite que se conecta transparentemente con la API de Express del portafolio.

---

## Arquitectura de Red

```
[ Navegador Admin: /admin ]
         │ (Token Bearer)
         ▼
[ Express API :3001 ] ──proxy──▶ [ Eros Agent (FastAPI) :8000 ]
                                         │
                   ┌─────────────────────┼─────────────────────┐
                   ▼                     ▼                     ▼
             [ SQLite DB ]      [ Gemini 2.5 Flash Lite ]  [ Scrapers: GoB/RemoteOK/HN ]
```

---

## Configuración (.env)

Copia `.env.example` a `.env` y configura tus variables:

```bash
cp .env.example .env
```

| Variable | Descripción |
|---|---|
| `PORTFOLIO_API_URL` | URL de tu API Express (`https://api.mateogs.tech/api`). |
| `GEMINI_API_KEY` | API Key de Google Gemini para scoring y redacción. |
| `MATCH_MIN_SCORE` | Puntaje mínimo (0–100) para clasificar como alto match (default: `75`). |
| `DATABASE_PATH` | Ruta a la base SQLite (default: `data/eros.db`). |
| `PORT` | Puerto HTTP para la API de FastAPI (default: `8000`). |

---

## Comandos de Uso Local

Con el entorno virtual activado:

```powershell
# 1. Ejecutar el servidor API de Eros Agent (FastAPI)
uvicorn eros.api:app --port 8000 --reload

# 2. Sincronizar perfil con la API viva del portafolio
python -m eros.main --sync

# 3. Escaneo manual por CLI
python -m eros.main --scan

# 4. Evaluación manual con IA
python -m eros.main --evaluate
```

---

## Despliegue en el VPS (Coolify)

1. Subí este repositorio a GitHub (`MateoGs013/eros-agent`).
2. En tu panel de Coolify en tu VPS:
   - Añadí una nueva **Application** desde GitHub.
   - Seleccioná el repositorio `eros-agent`.
   - Tipo de Build: **Dockerfile**.
   - Cargá las variables de entorno (`PORTFOLIO_API_URL`, `GEMINI_API_KEY`, etc.).
   - Puerto de exposición interna o red Docker: `8000`.
3. En la configuración de tu contenedor de portafolio Express en Coolify:
   - Variable `HUNTER_API_URL`: `http://eros-agent:8000` (usando la red interna de Docker en Coolify).
4. ¡Listo! Todo queda interconectado en tu VPS privado.
