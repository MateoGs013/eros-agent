"""Interfaz Web Standalone de Eros Agent (eros.mateogs.tech).
Panel de Control y Diagnóstico con autenticación mediante EROS_API_KEY.
"""

HTML_DASHBOARD = r"""<!DOCTYPE html>
<html lang="es" class="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Eros Agent · Control Center</title>
  <meta name="robots" content="noindex, nofollow">
  <link rel="icon" type="image/svg+xml" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24'><rect width='24' height='24' rx='4' fill='%23ff3e00'/><text x='12' y='16' fill='%2309090b' font-family='monospace' font-weight='bold' font-size='11' text-anchor='middle'>ER</text></svg>">
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
  <style>
    body { background-color: #08090a; color: #f4f4f6; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    .font-mono-code { font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
    [v-cloak] { display: none; }
  </style>
</head>
<body class="min-h-screen bg-[#08090a] text-[#f4f4f6] selection:bg-[#ff3e00]/20 selection:text-white">
  <div id="app" v-cloak class="min-h-screen flex flex-col">

    <!-- Notificación Toast Flotante -->
    <div v-if="toast.show" class="fixed bottom-5 right-5 z-50 flex items-center gap-2.5 px-4 py-3 rounded-lg border shadow-xl text-xs font-mono-code transition-all"
         :class="toast.type === 'ok' ? 'bg-[#101b14] border-emerald-500/40 text-emerald-300' : 'bg-[#221010] border-rose-500/40 text-rose-300'">
      <span class="w-2 h-2 rounded-full" :class="toast.type === 'ok' ? 'bg-emerald-400' : 'bg-rose-400'"></span>
      <span>{{ toast.msg }}</span>
    </div>

    <!-- Pantalla de Inicio de Sesión si no está autenticado -->
    <div v-if="!authenticated" class="min-h-screen flex items-center justify-center p-4">
      <div class="max-w-md w-full bg-[#101114] border border-white/10 rounded-xl p-8 shadow-2xl space-y-6">
        <div class="text-center space-y-2">
          <div class="w-12 h-12 rounded-lg bg-[#ff3e00] text-[#09090b] flex items-center justify-center font-bold text-base mx-auto font-mono-code tracking-tighter shadow-lg shadow-[#ff3e00]/25">
            ER
          </div>
          <h1 class="text-base font-bold text-white tracking-tight">Eros Agent · Control Center</h1>
          <p class="text-xs text-zinc-400 font-mono-code">Acceso seguro para el agente en eros.mateogs.tech</p>
        </div>

        <form @submit.prevent="login" class="space-y-4">
          <div class="space-y-1.5">
            <label class="block text-xs font-medium text-zinc-300 font-mono-code">Clave Secreta (EROS_API_KEY)</label>
            <div class="relative">
              <input :type="showKey ? 'text' : 'password'" v-model="keyInput" placeholder="Ingresá la clave de Eros..."
                     class="w-full bg-[#16171b] border border-white/10 rounded-md px-3.5 py-2.5 text-xs text-white font-mono-code focus:outline-none focus:border-[#ff3e00] pr-10" autofocus />
              <button type="button" @click="showKey = !showKey" class="absolute right-3 top-1/2 -translate-y-1/2 text-zinc-400 hover:text-white text-xs">
                {{ showKey ? 'Ocultar' : 'Ver' }}
              </button>
            </div>
            <p class="text-[11px] text-zinc-500 font-mono-code">Definida en las variables de entorno del contenedor.</p>
          </div>

          <button type="submit" :disabled="loading"
                  class="w-full bg-[#ff3e00] hover:bg-[#e03700] text-[#09090b] font-bold py-2.5 rounded-md text-xs font-mono-code uppercase tracking-wider transition-colors disabled:opacity-50">
            {{ loading ? 'Autenticando...' : 'Acceder al Panel' }}
          </button>
        </form>
      </div>
    </div>

    <!-- Panel de Control Principal Autenticado -->
    <div v-else class="flex-1 flex flex-col">
      <!-- Barra Superior -->
      <header class="border-b border-white/10 bg-[#0c0d10] px-6 py-3.5 flex items-center justify-between">
        <div class="flex items-center gap-3">
          <div class="w-8 h-8 rounded bg-[#ff3e00] text-[#09090b] flex items-center justify-center font-bold text-xs font-mono-code">
            ER
          </div>
          <div>
            <div class="flex items-center gap-2">
              <h1 class="text-xs font-bold text-white uppercase font-mono-code tracking-wide">Eros Agent</h1>
              <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-mono-code bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <span class="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
                ONLINE
              </span>
            </div>
            <p class="text-[11px] text-zinc-500 font-mono-code">eros.mateogs.tech</p>
          </div>
        </div>

        <div class="flex items-center gap-3">
          <button @click="logout" class="px-3 py-1.5 rounded border border-white/10 hover:border-white/20 text-xs font-mono-code text-zinc-400 hover:text-white transition-colors">
            Cerrar Sesión
          </button>
        </div>
      </header>

      <!-- Pestañas de Navegación -->
      <div class="border-b border-white/10 bg-[#0f1013] px-6 flex gap-6">
        <button @click="activeTab = 'metrics'" class="py-3 text-xs font-mono-code border-b-2 transition-colors uppercase tracking-wider"
                :class="activeTab === 'metrics' ? 'border-[#ff3e00] text-white font-bold' : 'border-transparent text-zinc-400 hover:text-white'">
          Métricas & Vacantes
        </button>
        <button @click="activeTab = 'sources'" class="py-3 text-xs font-mono-code border-b-2 transition-colors uppercase tracking-wider"
                :class="activeTab === 'sources' ? 'border-[#ff3e00] text-white font-bold' : 'border-transparent text-zinc-400 hover:text-white'">
          Fuentes de Empleo
        </button>
        <button @click="activeTab = 'matching'" class="py-3 text-xs font-mono-code border-b-2 transition-colors uppercase tracking-wider"
                :class="activeTab === 'matching' ? 'border-[#ff3e00] text-white font-bold' : 'border-transparent text-zinc-400 hover:text-white'">
          Filtros & Matching
        </button>
        <button @click="activeTab = 'diagnostics'" class="py-3 text-xs font-mono-code border-b-2 transition-colors uppercase tracking-wider"
                :class="activeTab === 'diagnostics' ? 'border-[#ff3e00] text-white font-bold' : 'border-transparent text-zinc-400 hover:text-white'">
          Conexiones & Diagnóstico
        </button>
      </div>

      <!-- Contenido Principal -->
      <main class="flex-1 p-6 max-w-7xl w-full mx-auto space-y-6">

        <!-- TAB 1: MÉTRICAS Y VACANTES -->
        <div v-if="activeTab === 'metrics'" class="space-y-6">
          <!-- Cards de Métricas -->
          <div class="grid grid-cols-2 sm:grid-cols-5 gap-3.5">
            <div class="bg-[#101114] border border-white/10 rounded-lg p-4 space-y-1">
              <span class="text-[10px] text-zinc-400 uppercase font-mono-code">Total Vacantes</span>
              <p class="text-2xl font-bold font-mono-code text-white">{{ stats.total ?? '—' }}</p>
            </div>
            <div class="bg-[#101114] border border-emerald-500/20 rounded-lg p-4 space-y-1">
              <span class="text-[10px] text-emerald-400 uppercase font-mono-code">Alto Match (≥75)</span>
              <p class="text-2xl font-bold font-mono-code text-emerald-400">{{ stats.high_match_count ?? '—' }}</p>
            </div>
            <div class="bg-[#101114] border border-amber-500/20 rounded-lg p-4 space-y-1">
              <span class="text-[10px] text-amber-400 uppercase font-mono-code">Pendientes IA</span>
              <p class="text-2xl font-bold font-mono-code text-amber-400">{{ stats.pending_eval_count ?? '—' }}</p>
            </div>
            <div class="bg-[#101114] border border-blue-500/20 rounded-lg p-4 space-y-1">
              <span class="text-[10px] text-blue-400 uppercase font-mono-code">Aplicadas</span>
              <p class="text-2xl font-bold font-mono-code text-blue-400">{{ stats.applied_count ?? '—' }}</p>
            </div>
            <div class="bg-[#101114] border border-white/5 rounded-lg p-4 space-y-1">
              <span class="text-[10px] text-zinc-500 uppercase font-mono-code">Descartadas</span>
              <p class="text-2xl font-bold font-mono-code text-zinc-500">{{ stats.discarded_count ?? '—' }}</p>
            </div>
          </div>

          <!-- Barra de Acciones Rápidas del Motor -->
          <div class="bg-[#101114] border border-white/10 rounded-lg p-4 flex flex-wrap items-center justify-between gap-3">
            <div class="space-y-0.5">
              <h2 class="text-xs font-bold text-white font-mono-code uppercase">Acciones Rápidas del Agente</h2>
              <p class="text-[11px] text-zinc-400 font-mono-code">Dispará tareas del ciclo de búsqueda y evaluación de IA en segundo plano.</p>
            </div>
            <div class="flex items-center gap-2 flex-wrap">
              <button @click="triggerAction('scan')" :disabled="actionLoading"
                      class="px-3.5 py-2 rounded bg-[#ff3e00] hover:bg-[#e03700] text-[#09090b] font-bold text-xs font-mono-code transition-colors disabled:opacity-50">
                ▶ Escanear Fuentes
              </button>
              <button @click="triggerAction('evaluate')" :disabled="actionLoading"
                      class="px-3.5 py-2 rounded bg-white/10 hover:bg-white/15 text-white font-medium text-xs font-mono-code transition-colors disabled:opacity-50">
                Evaluar con Gemini
              </button>
              <button @click="triggerAction('purge')" :disabled="actionLoading"
                      class="px-3.5 py-2 rounded bg-white/10 hover:bg-white/15 text-white font-medium text-xs font-mono-code transition-colors disabled:opacity-50">
                Purgar Incompatibles
              </button>
              <button @click="triggerAction('sync')" :disabled="actionLoading"
                      class="px-3.5 py-2 rounded bg-white/10 hover:bg-white/15 text-white font-medium text-xs font-mono-code transition-colors disabled:opacity-50">
                Sincronizar Perfil
              </button>
            </div>
          </div>

          <!-- Tabla de Últimas Ofertas -->
          <div class="bg-[#101114] border border-white/10 rounded-lg overflow-hidden">
            <div class="p-4 border-b border-white/10 flex items-center justify-between">
              <h3 class="text-xs font-bold text-white uppercase font-mono-code">Vacantes Recientes</h3>
              <button @click="loadData" class="text-xs font-mono-code text-zinc-400 hover:text-white">Actualizar</button>
            </div>
            <div class="overflow-x-auto">
              <table class="w-full text-left text-xs font-mono-code">
                <thead class="bg-white/5 text-zinc-400 uppercase text-[10px]">
                  <tr>
                    <th class="p-3">Título / Empresa</th>
                    <th class="p-3">Fuente</th>
                    <th class="p-3">Match</th>
                    <th class="p-3">Estado</th>
                    <th class="p-3 text-right">Enlace</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-white/5">
                  <tr v-for="j in recentJobs" :key="j.id" class="hover:bg-white/[0.02]">
                    <td class="p-3">
                      <div class="font-bold text-white">{{ j.title }}</div>
                      <div class="text-[11px] text-zinc-400">{{ j.company }} · {{ j.country || 'Remoto' }}</div>
                    </td>
                    <td class="p-3 text-zinc-400">{{ j.source }}</td>
                    <td class="p-3">
                      <span v-if="j.match_score !== null" class="font-bold px-1.5 py-0.5 rounded text-[11px]"
                            :class="j.match_score >= 75 ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : (j.match_score >= 50 ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' : 'bg-zinc-500/10 text-zinc-400 border border-zinc-500/20')">
                        {{ j.match_score }}%
                      </span>
                      <span v-else class="text-zinc-500">Pendiente</span>
                    </td>
                    <td class="p-3">
                      <span class="text-[11px] px-1.5 py-0.5 rounded border border-white/10 text-zinc-300">{{ j.status }}</span>
                    </td>
                    <td class="p-3 text-right">
                      <a :href="j.url" target="_blank" rel="noopener noreferrer" class="text-[#ff3e00] hover:underline">Abrir ↗</a>
                    </td>
                  </tr>
                  <tr v-if="!recentJobs.length">
                    <td colspan="5" class="p-6 text-center text-zinc-500">No hay vacantes registradas aún. Dispará "Escanear Fuentes".</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <!-- TAB 2: FUENTES DE EMPLEO -->
        <div v-if="activeTab === 'sources'" class="bg-[#101114] border border-white/10 rounded-lg p-6 space-y-6">
          <div class="space-y-1">
            <h2 class="text-sm font-bold text-white uppercase font-mono-code">Fuentes de Empleo Conectadas</h2>
            <p class="text-xs text-zinc-400 font-mono-code">Activa o desactiva las plataformas que Eros consulta durante cada ciclo de búsqueda.</p>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div v-for="(enabled, name) in config.sources" :key="name"
                 class="p-4 rounded border border-white/10 bg-[#16171b] flex items-center justify-between">
              <div>
                <span class="text-xs font-bold text-white font-mono-code capitalize">{{ name }}</span>
                <p class="text-[11px] text-zinc-400 font-mono-code">{{ getSourceDesc(name) }}</p>
              </div>
              <label class="relative inline-flex items-center cursor-pointer">
                <input type="checkbox" v-model="config.sources[name]" class="sr-only peer">
                <div class="w-9 h-5 bg-zinc-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-zinc-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-emerald-500"></div>
              </label>
            </div>
          </div>

          <div class="pt-4 border-t border-white/10 flex justify-end">
            <button @click="saveConfig" :disabled="saving"
                    class="px-5 py-2.5 rounded bg-[#ff3e00] hover:bg-[#e03700] text-[#09090b] font-bold text-xs font-mono-code transition-colors disabled:opacity-50">
              {{ saving ? 'Guardando...' : 'Guardar Fuentes' }}
            </button>
          </div>
        </div>

        <!-- TAB 3: FILTROS & MATCHING -->
        <div v-if="activeTab === 'matching'" class="bg-[#101114] border border-white/10 rounded-lg p-6 space-y-6">
          <div class="space-y-1">
            <h2 class="text-sm font-bold text-white uppercase font-mono-code">Reglas de Matching y Filtros</h2>
            <p class="text-xs text-zinc-400 font-mono-code">Ajusta los umbrales de compatibilidad que exige Eros para calificar y alertar ofertas.</p>
          </div>

          <div class="space-y-5 max-w-xl">
            <!-- Umbral Mínimo -->
            <div class="space-y-2 p-4 rounded bg-[#16171b] border border-white/10">
              <div class="flex items-center justify-between font-mono-code text-xs">
                <label class="font-bold text-white">Score Mínimo de Notificación</label>
                <span class="text-emerald-400 font-bold text-sm">{{ config.match_min_score }}%</span>
              </div>
              <input type="range" min="40" max="95" step="5" v-model.number="config.match_min_score"
                     class="w-full accent-[#ff3e00] cursor-pointer">
              <p class="text-[11px] text-zinc-500 font-mono-code">Las ofertas con score igual o superior disparan alerta por Telegram y se priorizan en el panel.</p>
            </div>

            <!-- Modalidad Remota -->
            <div class="p-4 rounded bg-[#16171b] border border-white/10 flex items-center justify-between">
              <div>
                <span class="text-xs font-bold text-white font-mono-code">Solo ofertas 100% Remotas</span>
                <p class="text-[11px] text-zinc-500 font-mono-code">Descarta automáticamente ofertas que requieran presencia en oficina.</p>
              </div>
              <input type="checkbox" v-model="config.remote_only" class="w-4 h-4 accent-[#ff3e00]">
            </div>

            <!-- Auto-evaluación -->
            <div class="p-4 rounded bg-[#16171b] border border-white/10 flex items-center justify-between">
              <div>
                <span class="text-xs font-bold text-white font-mono-code">Auto-evaluar con IA tras escaneo</span>
                <p class="text-[11px] text-zinc-500 font-mono-code">Ejecuta Gemini automáticamente al terminar de raspar nuevas vacantes.</p>
              </div>
              <input type="checkbox" v-model="config.auto_evaluate" class="w-4 h-4 accent-[#ff3e00]">
            </div>

            <!-- Límite de Evaluación -->
            <div class="space-y-2 p-4 rounded bg-[#16171b] border border-white/10 font-mono-code text-xs">
              <label class="font-bold text-white block">Límite de Evaluación por Ciclo</label>
              <input type="number" min="5" max="50" v-model.number="config.eval_limit"
                     class="bg-[#0c0d10] border border-white/10 rounded px-3 py-1.5 text-white w-28 text-xs font-mono-code">
              <p class="text-[11px] text-zinc-500">Cantidad máxima de ofertas evaluadas por Gemini en cada tanda para optimizar cuota de API.</p>
            </div>
          </div>

          <div class="pt-4 border-t border-white/10 flex justify-end">
            <button @click="saveConfig" :disabled="saving"
                    class="px-5 py-2.5 rounded bg-[#ff3e00] hover:bg-[#e03700] text-[#09090b] font-bold text-xs font-mono-code transition-colors disabled:opacity-50">
              {{ saving ? 'Guardando...' : 'Guardar Filtros' }}
            </button>
          </div>
        </div>

        <!-- TAB 4: CONEXIONES & DIAGNÓSTICO -->
        <div v-if="activeTab === 'diagnostics'" class="space-y-4">
          <div class="bg-[#101114] border border-white/10 rounded-lg p-6 space-y-6">
            <div class="space-y-1">
              <h2 class="text-sm font-bold text-white uppercase font-mono-code">Estado de Conexiones e Integraciones</h2>
              <p class="text-xs text-zinc-400 font-mono-code">Verificá la comunicación en vivo con los servicios externos del agente.</p>
            </div>

            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
              <!-- Gemini -->
              <div class="p-4 rounded-lg bg-[#16171b] border border-white/10 space-y-3 font-mono-code">
                <div class="flex items-center justify-between">
                  <span class="text-xs font-bold text-white">Google Gemini</span>
                  <span class="text-[10px] px-2 py-0.5 rounded"
                        :class="config.integrations.gemini ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'">
                    {{ config.integrations.gemini ? 'Configurada' : 'Falta Key' }}
                  </span>
                </div>
                <p class="text-[11px] text-zinc-400">Scoring semántico y redacción de CV Harvard ATS adaptado.</p>
                <button @click="testIntegration('gemini')" :disabled="testing.gemini"
                        class="w-full py-1.5 text-xs rounded border border-white/10 hover:border-white/20 text-white font-medium transition-colors disabled:opacity-50">
                  {{ testing.gemini ? 'Probando...' : 'Probar Conexión' }}
                </button>
                <div v-if="testResult.gemini" class="text-[11px] p-2 rounded bg-black/30 border border-white/5"
                     :class="testResult.gemini.ok ? 'text-emerald-400' : 'text-rose-400'">
                  {{ testResult.gemini.msg }}
                </div>
              </div>

              <!-- Telegram Bot -->
              <div class="p-4 rounded-lg bg-[#16171b] border border-white/10 space-y-3 font-mono-code">
                <div class="flex items-center justify-between">
                  <span class="text-xs font-bold text-white">Telegram Bot</span>
                  <span class="text-[10px] px-2 py-0.5 rounded"
                        :class="config.integrations.telegram ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-zinc-500/10 text-zinc-400 border border-zinc-500/20'">
                    {{ config.integrations.telegram ? 'Configurado' : 'Sin Token' }}
                  </span>
                </div>
                <p class="text-[11px] text-zinc-400">Alertas automáticas al canal C2 privado ante coincidencias altas.</p>
                <button @click="testIntegration('telegram')" :disabled="testing.telegram"
                        class="w-full py-1.5 text-xs rounded border border-white/10 hover:border-white/20 text-white font-medium transition-colors disabled:opacity-50">
                  {{ testing.telegram ? 'Probando...' : 'Probar Bot' }}
                </button>
                <div v-if="testResult.telegram" class="text-[11px] p-2 rounded bg-black/30 border border-white/5"
                     :class="testResult.telegram.ok ? 'text-emerald-400' : 'text-rose-400'">
                  {{ testResult.telegram.msg }}
                </div>
              </div>

              <!-- Portfolio API -->
              <div class="p-4 rounded-lg bg-[#16171b] border border-white/10 space-y-3 font-mono-code">
                <div class="flex items-center justify-between">
                  <span class="text-xs font-bold text-white">Portfolio API</span>
                  <span class="text-[10px] px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                    Conectada
                  </span>
                </div>
                <p class="text-[11px] text-zinc-400 truncate">{{ config.integrations.portfolio_url }}</p>
                <button @click="testIntegration('portfolio')" :disabled="testing.portfolio"
                        class="w-full py-1.5 text-xs rounded border border-white/10 hover:border-white/20 text-white font-medium transition-colors disabled:opacity-50">
                  {{ testing.portfolio ? 'Probando...' : 'Probar API' }}
                </button>
                <div v-if="testResult.portfolio" class="text-[11px] p-2 rounded bg-black/30 border border-white/5"
                     :class="testResult.portfolio.ok ? 'text-emerald-400' : 'text-rose-400'">
                  {{ testResult.portfolio.msg }}
                </div>
              </div>
            </div>
          </div>
        </div>

      </main>
    </div>
  </div>

  <script>
    const { createApp, ref, reactive, onMounted } = Vue

    createApp({
      setup() {
        const authenticated = ref(false)
        const keyInput = ref(localStorage.getItem('eros_key') || '')
        const showKey = ref(false)
        const loading = ref(false)
        const saving = ref(false)
        const actionLoading = ref(false)
        const activeTab = ref('metrics')

        const stats = ref({})
        const recentJobs = ref([])
        const config = reactive({
          match_min_score: 75,
          remote_only: true,
          auto_evaluate: true,
          eval_limit: 15,
          sources: {},
          integrations: {}
        })

        const testing = reactive({ gemini: false, telegram: false, portfolio: false })
        const testResult = reactive({ gemini: null, telegram: null, portfolio: null })

        const toast = reactive({ show: false, msg: '', type: 'ok' })
        function showToast(msg, type = 'ok') {
          toast.msg = msg
          toast.type = type
          toast.show = true
          setTimeout(() => { toast.show = false }, 3500)
        }

        function authHeaders() {
          const k = localStorage.getItem('eros_key') || ''
          return k ? { 'Authorization': `Bearer ${k}` } : {}
        }

        async function checkAuth() {
          try {
            const res = await fetch('/api/auth/me', { headers: authHeaders() })
            if (res.ok) {
              const data = await res.json()
              authenticated.value = data.authenticated
              if (data.authenticated) loadData()
            }
          } catch {
            authenticated.value = false
          }
        }

        async function login() {
          const val = keyInput.value.trim()
          if (!val) return showToast('Ingresá la clave de Eros', 'err')
          loading.value = true
          try {
            const res = await fetch('/api/auth/login', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ key: val }),
            })
            if (res.ok) {
              localStorage.setItem('eros_key', val)
              authenticated.value = true
              showToast('Acceso autorizado')
              loadData()
            } else {
              showToast('Clave incorrecta', 'err')
            }
          } catch (e) {
            showToast('Error de conexión', 'err')
          } finally {
            loading.value = false
          }
        }

        async function logout() {
          localStorage.removeItem('eros_key')
          await fetch('/api/auth/logout', { method: 'POST' }).catch(() => {})
          authenticated.value = false
        }

        async function loadData() {
          try {
            const [statsRes, jobsRes, cfgRes] = await Promise.all([
              fetch('/api/stats', { headers: authHeaders() }),
              fetch('/api/jobs?limit=10', { headers: authHeaders() }),
              fetch('/api/config', { headers: authHeaders() }),
            ])
            if (statsRes.ok) stats.value = await statsRes.json()
            if (jobsRes.ok) {
              const d = await jobsRes.json()
              recentJobs.value = d.data || []
            }
            if (cfgRes.ok) {
              const c = await cfgRes.json()
              config.match_min_score = c.match_min_score
              config.remote_only = c.remote_only
              config.auto_evaluate = c.auto_evaluate
              config.eval_limit = c.eval_limit
              config.sources = c.sources || {}
              config.integrations = c.integrations || {}
            }
          } catch (e) {
            console.error('Error cargando datos:', e)
          }
        }

        async function saveConfig() {
          saving.value = true
          try {
            const res = await fetch('/api/config', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', ...authHeaders() },
              body: JSON.stringify({
                match_min_score: config.match_min_score,
                remote_only: config.remote_only,
                auto_evaluate: config.auto_evaluate,
                eval_limit: config.eval_limit,
                sources: config.sources,
              })
            })
            if (res.ok) {
              showToast('Configuraciones guardadas')
            } else {
              showToast('Error al guardar configuración', 'err')
            }
          } catch {
            showToast('Fallo de red', 'err')
          } finally {
            saving.value = false
          }
        }

        async function triggerAction(action) {
          actionLoading.value = true
          try {
            let res
            if (action === 'scan') res = await fetch('/api/scan', { method: 'POST', headers: authHeaders() })
            if (action === 'evaluate') res = await fetch('/api/evaluate', { method: 'POST', headers: authHeaders() })
            if (action === 'purge') res = await fetch('/api/purge', { method: 'POST', headers: authHeaders() })
            if (action === 'sync') res = await fetch('/api/profile/sync', { method: 'POST', headers: authHeaders() })
            if (res && res.ok) {
              const d = await res.json()
              showToast(`Acción completada con éxito`)
              loadData()
            } else {
              showToast('Error ejecutando acción', 'err')
            }
          } catch {
            showToast('Fallo de conexión', 'err')
          } finally {
            actionLoading.value = false
          }
        }

        async function testIntegration(name) {
          testing[name] = true
          testResult[name] = null
          try {
            const res = await fetch(`/api/integrations/test/${name}`, { method: 'POST', headers: authHeaders() })
            const d = await res.json()
            if (d.ok) {
              const detail = d.latency_ms ? `${d.latency_ms} ms` : (d.bot || 'OK')
              testResult[name] = { ok: true, msg: `Conexión exitosa (${detail})` }
            } else {
              testResult[name] = { ok: false, msg: d.error || 'Falló la prueba' }
            }
          } catch (e) {
            testResult[name] = { ok: false, msg: String(e) }
          } finally {
            testing[name] = false
          }
        }

        function getSourceDesc(name) {
          const map = {
            remotive: 'API oficial de empleos remotos globales',
            weworkremotely: 'Canal curado de tecnología y desarrollo remoto',
            linkedin: 'Scraper de vacantes activas de software',
            computrabajo: 'Portal laboral regional (Argentina y LATAM)',
            getonboard: 'Especializado en startups tecnológicas de LATAM',
            remoteok: 'Ofertas remotas internacionales',
            hackernews: 'Hilos mensuales "Who is hiring" de YCombinator'
          }
          return map[name.toLowerCase()] || 'Conector de vacantes de software'
        }

        onMounted(() => {
          checkAuth()
        })

        return {
          authenticated,
          keyInput,
          showKey,
          loading,
          saving,
          actionLoading,
          activeTab,
          stats,
          recentJobs,
          config,
          testing,
          testResult,
          toast,
          login,
          logout,
          loadData,
          saveConfig,
          triggerAction,
          testIntegration,
          getSourceDesc,
        }
      }
    }).mount('#app')
  </script>
</body>
</html>
"""
