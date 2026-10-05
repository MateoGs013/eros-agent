# Eros Agent — Autonomous Job Hunter & CV Matcher

Agente personal autónomo en segundo plano diseñado para monitorear vacantes de empleo (remoto USD / LATAM), evaluar compatibilidad técnica en tiempo real contra el portafolio y CV de Mateo, y alertar mediante un bot privado de Telegram con generación de pitches a medida.

---

## Características

- 🔄 **Sincronización Viva con tu Portafolio:** Consume tu API (`https://api.mateogs.tech/api`) para obtener siempre tu stack, experiencia, métricas y proyectos reales (La Rúcula, Ynara, etc.) sin hardcodear datos.
- 🔎 **Multi-Fuente de Vacantes:**
  - **Get on Board API:** Puestos tech para LATAM y remoto.
  - **RemoteOK API:** Puestos remotos globales en USD.
  - **Hacker News ("Who is hiring?"):** Puestos directos en startups y fundadores de EE.UU.
- 🧠 **Evaluación Semántica con IA (LLM Matcher):**
  - Scoring de compatibilidad (0–100%).
  - Filtro duro de exclusión (requisitos incompatibles, on-site estricto en el exterior).
  - Puntos a favor, puntos en contra y proyectos clave de tu portafolio a destacar.
- ✉️ **Generador de Pitches Personalizados:** Redacta cover letters y mensajes directos en español o inglés conectando los requisitos de la vacante con tus proyectos reales.
- 📱 **Control Total por Telegram (C2):** Alertas con botones interactivos (`[✉️ Generar Pitch]`, `[🔗 Ver Oferta]`, `[❌ Descartar]`).
- 🐳 **Listo para VPS y Coolify:** Contenedor Docker autónomo que corre 24/7 en segundo plano.

---

## Configuración Rápida (.env)

Copia `.env.example` a `.env` y configura tus variables:

```bash
cp .env.example .env
```

| Variable | Descripción |
|---|---|
| `PORTFOLIO_API_URL` | URL de tu API Express (`https://api.mateogs.tech/api`). |
| `TELEGRAM_BOT_TOKEN` | Token de tu bot creado con `@BotFather`. |
| `TELEGRAM_ALLOWED_USER_ID` | Tu ID de Telegram (para que el bot solo responda a vos). |
| `GEMINI_API_KEY` | API Key de Google Gemini (para scoring rápido y gratuito). |
| `ANTHROPIC_API_KEY` | API Key de Anthropic (opcional, para redacción con Claude). |
| `MATCH_MIN_SCORE` | Puntaje mínimo (0–100) para enviar alertas (default: `75`). |

---

## Comandos de Uso Local

Con el entorno virtual activado:

```powershell
# 1. Probar sincronización con la API viva del portafolio
python -m eros.main --sync

# 2. Escanear vacantes en todas las fuentes
python -m eros.main --scan

# 3. Evaluar vacantes pendientes con IA
python -m eros.main --evaluate

# 4. Iniciar bot interactivo de Telegram
python -m eros.main --bot

# 5. Iniciar modo demonio 24/7 (bot + escáner periódico)
python -m eros.main --daemon
```

---

## Despliegue en el VPS (Coolify)

1. Subí este repositorio a GitHub (`MateoGs013/eros-agent`).
2. En tu panel de Coolify en tu VPS:
   - Añadí una nueva **Application** desde GitHub.
   - Seleccioná el repositorio `eros-agent`.
   - Tipo de Build: **Dockerfile**.
   - Cargá las variables de entorno (`TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`, etc.).
3. ¡Listo! El agente comenzará a correr 24/7 en tu servidor.
