"""Interfaz Web Standalone de Eros Agent (eros.mateogs.tech).
Panel de Control y Diagnóstico con autenticación mediante EROS_API_KEY.
"""

HTML_DASHBOARD = r"""<!DOCTYPE html>
<html lang="es" class="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Eros Career OS · Control Center</title>
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
    <div v-if="toast.show" class="fixed bottom-5 right-5 z-50 flex items-center gap-2.5 px-4 py-3 rounded-lg border shadow-2xl text-xs font-mono-code transition-all"
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
          <h1 class="text-base font-bold text-white tracking-tight">Eros Career OS · Control Center</h1>
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
              <h1 class="text-xs font-bold text-white uppercase font-mono-code tracking-wide">Eros Career OS</h1>
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
      <div class="border-b border-white/10 bg-[#0f1013] px-6 flex gap-6 overflow-x-auto">
        <button @click="activeTab = 'metrics'" class="py-3 text-xs font-mono-code border-b-2 transition-colors uppercase tracking-wider whitespace-nowrap"
                :class="activeTab === 'metrics' ? 'border-[#ff3e00] text-white font-bold' : 'border-transparent text-zinc-400 hover:text-white'">
          Métricas & Vacantes
        </button>
        <button @click="activeTab = 'content'" class="py-3 text-xs font-mono-code border-b-2 transition-colors uppercase tracking-wider whitespace-nowrap"
                :class="activeTab === 'content' ? 'border-[#ff3e00] text-white font-bold' : 'border-transparent text-zinc-400 hover:text-white'">
          Contenido Omnicanal
        </button>
        <button @click="activeTab = 'sources'" class="py-3 text-xs font-mono-code border-b-2 transition-colors uppercase tracking-wider whitespace-nowrap"
                :class="activeTab === 'sources' ? 'border-[#ff3e00] text-white font-bold' : 'border-transparent text-zinc-400 hover:text-white'">
          Fuentes de Empleo
        </button>
        <button @click="activeTab = 'matching'" class="py-3 text-xs font-mono-code border-b-2 transition-colors uppercase tracking-wider whitespace-nowrap"
                :class="activeTab === 'matching' ? 'border-[#ff3e00] text-white font-bold' : 'border-transparent text-zinc-400 hover:text-white'">
          Filtros & Matching
        </button>
        <button @click="activeTab = 'diagnostics'" class="py-3 text-xs font-mono-code border-b-2 transition-colors uppercase tracking-wider whitespace-nowrap"
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
              <h2 class="text-xs font-bold text-white font-mono-code uppercase">Acciones Rápidas del Hunter</h2>
              <p class="text-[11px] text-zinc-400 font-mono-code">Dispará tareas del ciclo de búsqueda, scraping y evaluación de IA.</p>
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

          <!-- Tabla de Vacantes con Hiring Manager Detective -->
          <div class="bg-[#101114] border border-white/10 rounded-lg overflow-hidden">
            <div class="p-4 border-b border-white/10 flex items-center justify-between">
              <div>
                <h3 class="text-xs font-bold text-white uppercase font-mono-code">Vacantes Recientes & Detective de Recruiter</h3>
                <p class="text-[11px] text-zinc-400 font-mono-code">Detecta hiring managers en LinkedIn y redacta notas de conexión de 1 toque.</p>
              </div>
              <button @click="loadData" class="text-xs font-mono-code text-zinc-400 hover:text-white">Actualizar</button>
            </div>
            <div class="overflow-x-auto">
              <table class="w-full text-left text-xs font-mono-code">
                <thead class="bg-white/5 text-zinc-400 uppercase text-[10px]">
                  <tr>
                    <th class="p-3">Título / Empresa</th>
                    <th class="p-3">Hiring Lead</th>
                    <th class="p-3">Fuente</th>
                    <th class="p-3">Match</th>
                    <th class="p-3">Estado</th>
                    <th class="p-3 text-right">Acciones</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-white/5">
                  <tr v-for="j in recentJobs" :key="j.id" class="hover:bg-white/[0.02]">
                    <td class="p-3">
                      <div class="font-bold text-white">{{ j.title }}</div>
                      <div class="text-[11px] text-zinc-400">{{ j.company }} · {{ j.country || 'Remoto' }}</div>
                    </td>
                    <td class="p-3">
                      <div v-if="j.hiring_manager_name" class="space-y-0.5">
                        <div class="flex items-center gap-1.5 font-bold text-zinc-200">
                          <span>{{ j.hiring_manager_name }}</span>
                          <a v-if="j.hiring_manager_url" :href="j.hiring_manager_url" target="_blank" rel="noopener noreferrer"
                             class="text-[10px] px-1 py-0.2 rounded bg-[#ff3e00]/20 text-[#ff3e00] hover:bg-[#ff3e00]/30 font-bold" title="Abrir perfil de LinkedIn">
                            In ↗
                          </a>
                        </div>
                        <div v-if="j.hiring_manager_title" class="text-[10px] text-zinc-500 truncate max-w-xs" :title="j.hiring_manager_title">
                          {{ j.hiring_manager_title }}
                        </div>
                      </div>
                      <span v-else class="text-zinc-600">—</span>
                    </td>
                    <td class="p-3 text-zinc-400 uppercase text-[11px]">{{ j.source }}</td>
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
                    <td class="p-3 text-right space-x-2">
                      <button v-if="j.connection_note" @click="copyText(j.connection_note, 'Nota de conexión copiada')"
                              class="text-[11px] px-2 py-1 rounded bg-[#ff3e00]/15 hover:bg-[#ff3e00]/25 text-[#ff3e00] border border-[#ff3e00]/30 font-bold"
                              title="Copiar nota de conexión (< 280 caracteres)">
                        Copiar Nota
                      </button>
                      <button @click="openJobModal(j)"
                              class="text-[11px] px-2 py-1 rounded bg-white/5 hover:bg-white/10 text-zinc-300 border border-white/10">
                        Detalle
                      </button>
                      <a :href="j.url" target="_blank" rel="noopener noreferrer" class="text-zinc-400 hover:text-white">
                        Abrir ↗
                      </a>
                    </td>
                  </tr>
                  <tr v-if="!recentJobs.length">
                    <td colspan="6" class="p-6 text-center text-zinc-500">No hay vacantes registradas aún. Dispará "Escanear Fuentes".</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <!-- TAB 2: CONTENIDO OMNICANAL -->
        <div v-if="activeTab === 'content'" class="space-y-6">
          <!-- Cards de Métricas de Contenido -->
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-3.5">
            <div class="bg-[#101114] border border-white/10 rounded-lg p-4 space-y-1">
              <span class="text-[10px] text-zinc-400 uppercase font-mono-code">Total Posts</span>
              <p class="text-2xl font-bold font-mono-code text-white">{{ contentPosts.length }}</p>
            </div>
            <div class="bg-[#101114] border border-amber-500/20 rounded-lg p-4 space-y-1">
              <span class="text-[10px] text-amber-400 uppercase font-mono-code">Borradores (Draft)</span>
              <p class="text-2xl font-bold font-mono-code text-amber-400">{{ contentDraftsCount }}</p>
            </div>
            <div class="bg-[#101114] border border-emerald-500/20 rounded-lg p-4 space-y-1">
              <span class="text-[10px] text-emerald-400 uppercase font-mono-code">Despachados n8n</span>
              <p class="text-2xl font-bold font-mono-code text-emerald-400">{{ contentPublishedCount }}</p>
            </div>
            <div class="bg-[#101114] border border-white/5 rounded-lg p-4 space-y-1">
              <span class="text-[10px] text-zinc-500 uppercase font-mono-code">Descartados</span>
              <p class="text-2xl font-bold font-mono-code text-zinc-500">{{ contentRejectedCount }}</p>
            </div>
          </div>

          <!-- Barra de Acciones y Filtros de Contenido -->
          <div class="bg-[#101114] border border-white/10 rounded-lg p-4 flex flex-wrap items-center justify-between gap-3">
            <div class="flex items-center gap-2 flex-wrap">
              <button @click="contentFilter = 'all'"
                      class="px-3 py-1.5 rounded text-xs font-mono-code uppercase transition-colors"
                      :class="contentFilter === 'all' ? 'bg-[#ff3e00] text-[#09090b] font-bold' : 'bg-white/5 text-zinc-400 hover:text-white'">
                Todos ({{ contentPosts.length }})
              </button>
              <button @click="contentFilter = 'draft'"
                      class="px-3 py-1.5 rounded text-xs font-mono-code uppercase transition-colors"
                      :class="contentFilter === 'draft' ? 'bg-[#ff3e00] text-[#09090b] font-bold' : 'bg-white/5 text-zinc-400 hover:text-white'">
                Borradores ({{ contentDraftsCount }})
              </button>
              <button @click="contentFilter = 'published'"
                      class="px-3 py-1.5 rounded text-xs font-mono-code uppercase transition-colors"
                      :class="contentFilter === 'published' ? 'bg-[#ff3e00] text-[#09090b] font-bold' : 'bg-white/5 text-zinc-400 hover:text-white'">
                Publicados ({{ contentPublishedCount }})
              </button>
              <button @click="contentFilter = 'rejected'"
                      class="px-3 py-1.5 rounded text-xs font-mono-code uppercase transition-colors"
                      :class="contentFilter === 'rejected' ? 'bg-[#ff3e00] text-[#09090b] font-bold' : 'bg-white/5 text-zinc-400 hover:text-white'">
                Descartados ({{ contentRejectedCount }})
              </button>
            </div>

            <div class="flex items-center gap-2">
              <button @click="showNewPostModal = true"
                      class="px-3.5 py-2 rounded bg-[#ff3e00] hover:bg-[#e03700] text-[#09090b] font-bold text-xs font-mono-code transition-colors">
                + Generar Nuevo Post
              </button>
              <button @click="loadContentPosts" class="text-xs font-mono-code text-zinc-400 hover:text-white px-2 py-1">
                Refrescar
              </button>
            </div>
          </div>

          <!-- Listado de Tarjetas de Publicación -->
          <div v-if="filteredPosts.length" class="space-y-4">
            <div v-for="p in filteredPosts" :key="p.id"
                 class="bg-[#101114] border border-white/10 rounded-lg p-5 space-y-4 hover:border-white/20 transition-all">
              
              <!-- Cabecera de la Publicación -->
              <div class="flex flex-wrap items-start justify-between gap-3 border-b border-white/5 pb-3">
                <div class="space-y-1">
                  <div class="flex items-center gap-2 flex-wrap">
                    <span class="text-[10px] uppercase px-2 py-0.5 rounded font-mono-code font-bold bg-[#ff3e00]/15 text-[#ff3e00] border border-[#ff3e00]/30">
                      {{ p.pillar }}
                    </span>
                    <span class="text-[10px] uppercase px-2 py-0.5 rounded font-mono-code"
                          :class="p.status === 'published' ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : (p.status === 'draft' ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' : 'bg-zinc-500/10 text-zinc-400 border border-zinc-500/20')">
                      {{ p.status }}
                    </span>
                    <span class="text-[11px] text-zinc-500 font-mono-code">{{ formatDate(p.created_at) }}</span>
                  </div>
                  <h3 class="text-sm font-bold text-white font-mono-code">{{ p.title }}</h3>
                </div>

                <!-- Botones de Acción -->
                <div class="flex items-center gap-2 flex-wrap">
                  <a :href="`/api/content/carousel/${p.id}/html`" target="_blank" rel="noopener noreferrer"
                     class="px-2.5 py-1.5 rounded bg-white/5 hover:bg-white/10 text-xs font-mono-code text-zinc-300 border border-white/10 flex items-center gap-1">
                    Ver Carousel Web ↗
                  </a>
                  <button v-if="p.status === 'draft'" @click="publishPost(p.id)" :disabled="publishLoading[p.id]"
                          class="px-3 py-1.5 rounded bg-emerald-500 hover:bg-emerald-600 text-[#09090b] font-bold text-xs font-mono-code transition-colors disabled:opacity-50">
                    {{ publishLoading[p.id] ? 'Enviando...' : 'Aprobar y Despachar a n8n' }}
                  </button>
                  <button v-if="p.status === 'draft'" @click="updatePostStatus(p.id, 'rejected')"
                          class="px-2.5 py-1.5 rounded bg-white/5 hover:bg-white/10 text-xs font-mono-code text-zinc-400 border border-white/10">
                    Descartar
                  </button>
                  <button @click="deletePost(p.id)" class="px-2 py-1.5 text-zinc-600 hover:text-rose-400 text-xs font-mono-code" title="Eliminar">
                    ×
                  </button>
                </div>
              </div>

              <!-- Hook de LinkedIn -->
              <div class="space-y-1">
                <div class="flex items-center justify-between">
                  <span class="text-[10px] uppercase font-mono-code text-zinc-400">Hook LinkedIn & Twitter:</span>
                  <button @click="copyText(p.hook, 'Hook copiado')" class="text-[10px] text-[#ff3e00] hover:underline font-mono-code">Copiar</button>
                </div>
                <div class="p-3 rounded bg-[#16171b] border border-white/5 text-xs text-zinc-200 font-mono-code whitespace-pre-wrap">
                  {{ p.hook }}
                </div>
              </div>

              <!-- Primer Comentario con Enlaces -->
              <div class="space-y-1">
                <div class="flex items-center justify-between">
                  <span class="text-[10px] uppercase font-mono-code text-zinc-400">Primer Comentario (Sin penalización en LinkedIn):</span>
                  <button @click="copyText(p.first_comment, 'Comentario copiado')" class="text-[10px] text-[#ff3e00] hover:underline font-mono-code">Copiar</button>
                </div>
                <div class="p-2.5 rounded bg-[#0c0d10] border border-white/5 text-xs text-zinc-300 font-mono-code">
                  <code>{{ p.first_comment }}</code>
                </div>
              </div>

              <!-- Secciones Desplegables (X Thread, Dev.to, Diapositivas) -->
              <div class="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2">
                <!-- X / Twitter Thread -->
                <div class="p-3 rounded bg-[#16171b] border border-white/5 space-y-2">
                  <div class="flex items-center justify-between">
                    <span class="text-xs font-bold text-white font-mono-code">Hilo de X (Twitter)</span>
                    <span class="text-[10px] text-zinc-400 font-mono-code">{{ p.twitter_thread ? p.twitter_thread.length : 0 }} tweets</span>
                  </div>
                  <button @click="toggleExpanded(p.id, 'twitter')" class="text-[11px] text-[#ff3e00] font-mono-code hover:underline">
                    {{ isExpanded(p.id, 'twitter') ? 'Ocultar Hilo' : 'Ver Hilo Completo' }}
                  </button>
                  <div v-if="isExpanded(p.id, 'twitter')" class="space-y-2 pt-2 border-t border-white/5">
                    <div v-for="(t, idx) in p.twitter_thread" :key="idx"
                         class="p-2 rounded bg-black/40 text-[11px] font-mono-code text-zinc-300 space-y-1 border border-white/5">
                      <div class="flex justify-between text-[10px] text-zinc-500">
                        <span>Tweet {{ idx + 1 }}/{{ p.twitter_thread.length }}</span>
                        <button @click="copyText(t, `Tweet ${idx + 1} copiado`)" class="text-[#ff3e00] hover:underline">Copiar</button>
                      </div>
                      <p class="whitespace-pre-wrap">{{ t }}</p>
                    </div>
                  </div>
                </div>

                <!-- Diapositivas Carrusel -->
                <div class="p-3 rounded bg-[#16171b] border border-white/5 space-y-2">
                  <div class="flex items-center justify-between">
                    <span class="text-xs font-bold text-white font-mono-code">Carrusel LinkedIn</span>
                    <span class="text-[10px] text-zinc-400 font-mono-code">{{ p.carousel_slides ? p.carousel_slides.length : 0 }} slides</span>
                  </div>
                  <button @click="toggleExpanded(p.id, 'carousel')" class="text-[11px] text-[#ff3e00] font-mono-code hover:underline">
                    {{ isExpanded(p.id, 'carousel') ? 'Ocultar Esquema' : 'Ver Esquema' }}
                  </button>
                  <div v-if="isExpanded(p.id, 'carousel')" class="space-y-2 pt-2 border-t border-white/5">
                    <div v-for="s in p.carousel_slides" :key="s.number"
                         class="p-2 rounded bg-black/40 text-[11px] font-mono-code text-zinc-300 space-y-0.5 border border-white/5">
                      <div class="text-[10px] text-[#ff3e00] font-bold">Slide {{ s.number }}: {{ s.title }}</div>
                      <div v-if="s.subtitle" class="text-zinc-400 text-[10px]">{{ s.subtitle }}</div>
                      <div v-if="s.body" class="text-zinc-300 text-[10px]">{{ s.body }}</div>
                      <div v-if="s.code" class="p-1 rounded bg-[#08090a] text-[10px] text-emerald-400 font-mono-code">{{ s.code }}</div>
                    </div>
                  </div>
                </div>

                <!-- Artículo Dev.to -->
                <div class="p-3 rounded bg-[#16171b] border border-white/5 space-y-2">
                  <div class="flex items-center justify-between">
                    <span class="text-xs font-bold text-white font-mono-code">Artículo Dev.to</span>
                    <span class="text-[10px] text-zinc-400 font-mono-code">Markdown</span>
                  </div>
                  <button @click="toggleExpanded(p.id, 'devto')" class="text-[11px] text-[#ff3e00] font-mono-code hover:underline">
                    {{ isExpanded(p.id, 'devto') ? 'Ocultar Markdown' : 'Ver Markdown' }}
                  </button>
                  <div v-if="isExpanded(p.id, 'devto')" class="space-y-1 pt-2 border-t border-white/5">
                    <div class="flex justify-end">
                      <button @click="copyText(p.devto_markdown, 'Markdown copiado')" class="text-[10px] text-[#ff3e00] hover:underline font-mono-code">Copiar Markdown</button>
                    </div>
                    <pre class="p-2 rounded bg-black/40 text-[10px] font-mono-code text-zinc-300 max-h-48 overflow-y-auto whitespace-pre-wrap">{{ p.devto_markdown }}</pre>
                  </div>
                </div>
              </div>

            </div>
          </div>

          <div v-else class="p-12 text-center bg-[#101114] border border-white/10 rounded-lg space-y-3">
            <p class="text-xs text-zinc-400 font-mono-code">No hay publicaciones con el filtro seleccionado.</p>
            <button @click="showNewPostModal = true"
                    class="px-4 py-2 rounded bg-[#ff3e00] text-[#09090b] font-bold text-xs font-mono-code">
              + Generar Primer Post
            </button>
          </div>
        </div>

        <!-- TAB 3: FUENTES DE EMPLEO -->
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

        <!-- TAB 4: FILTROS & MATCHING -->
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

        <!-- TAB 5: CONEXIONES & DIAGNÓSTICO -->
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

      <!-- MODAL DETALLE DE VACANTE -->
      <div v-if="selectedJob" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm">
        <div class="max-w-2xl w-full bg-[#101114] border border-white/15 rounded-xl p-6 shadow-2xl space-y-5 max-h-[90vh] overflow-y-auto font-mono-code">
          
          <div class="flex items-start justify-between border-b border-white/10 pb-3">
            <div class="space-y-1">
              <div class="flex items-center gap-2">
                <span class="text-[10px] uppercase px-1.5 py-0.5 rounded bg-[#ff3e00]/20 text-[#ff3e00] font-bold">
                  {{ selectedJob.source }}
                </span>
                <span v-if="selectedJob.match_score !== null" class="text-[10px] px-1.5 py-0.5 rounded font-bold"
                      :class="selectedJob.match_score >= 75 ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400'">
                  Match: {{ selectedJob.match_score }}%
                </span>
              </div>
              <h2 class="text-base font-bold text-white">{{ selectedJob.title }}</h2>
              <p class="text-xs text-zinc-400">{{ selectedJob.company }} · {{ selectedJob.country || 'Remoto' }}</p>
            </div>
            <button @click="selectedJob = null" class="text-zinc-400 hover:text-white text-lg">×</button>
          </div>

          <!-- Información de Hiring Manager -->
          <div v-if="selectedJob.hiring_manager_name" class="p-3.5 rounded bg-[#16171b] border border-white/10 space-y-1.5">
            <div class="text-[10px] uppercase text-[#ff3e00] font-bold">Hiring Lead / Recruiter Detectado</div>
            <div class="flex items-center justify-between">
              <div>
                <div class="text-xs font-bold text-white">{{ selectedJob.hiring_manager_name }}</div>
                <div class="text-[11px] text-zinc-400">{{ selectedJob.hiring_manager_title }}</div>
              </div>
              <a v-if="selectedJob.hiring_manager_url" :href="selectedJob.hiring_manager_url" target="_blank" rel="noopener noreferrer"
                 class="px-2.5 py-1 rounded bg-[#ff3e00] text-[#09090b] font-bold text-xs hover:bg-[#e03700]">
                Ver Perfil LinkedIn ↗
              </a>
            </div>
          </div>

          <!-- Nota de Conexión de LinkedIn -->
          <div v-if="selectedJob.connection_note" class="space-y-1.5">
            <div class="flex items-center justify-between">
              <span class="text-xs font-bold text-zinc-300">Nota de Invitación LinkedIn (&lt; 280 caracteres):</span>
              <button @click="copyText(selectedJob.connection_note, 'Nota copiada al portapapeles')"
                      class="text-xs text-[#ff3e00] hover:underline font-bold">
                Copiar Nota
              </button>
            </div>
            <div class="p-3 rounded bg-[#0c0d10] border border-white/10 text-xs text-zinc-200 whitespace-pre-wrap">
              {{ selectedJob.connection_note }}
            </div>
          </div>

          <!-- Salario -->
          <div v-if="selectedJob.salary" class="text-xs text-zinc-300">
            <span class="text-zinc-500">Salario:</span> <span class="text-emerald-400 font-bold">{{ selectedJob.salary }}</span>
          </div>

          <!-- Botones de pie -->
          <div class="pt-3 border-t border-white/10 flex justify-between items-center">
            <a :href="selectedJob.url" target="_blank" rel="noopener noreferrer"
               class="text-xs text-[#ff3e00] hover:underline font-bold">
              Abrir Ficha de la Oferta Original ↗
            </a>
            <button @click="selectedJob = null" class="px-4 py-2 rounded bg-white/10 hover:bg-white/15 text-xs text-white">
              Cerrar
            </button>
          </div>

        </div>
      </div>

      <!-- MODAL GENERAR NUEVO POST -->
      <div v-if="showNewPostModal" class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm">
        <div class="max-w-lg w-full bg-[#101114] border border-white/15 rounded-xl p-6 shadow-2xl space-y-4 font-mono-code">
          <div class="flex items-center justify-between border-b border-white/10 pb-3">
            <h2 class="text-sm font-bold text-white uppercase">Generar Publicación Omnicanal</h2>
            <button @click="showNewPostModal = false" class="text-zinc-400 hover:text-white text-lg">×</button>
          </div>

          <form @submit.prevent="generatePostAction" class="space-y-4">
            <div class="space-y-1">
              <label class="block text-xs font-medium text-zinc-300">Tema o Título Técnico:</label>
              <input type="text" v-model="newPostForm.topic" placeholder="Ej: Optimización de arquitectura Nuxt 3 y TypeScript..." required
                     class="w-full bg-[#16171b] border border-white/10 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-[#ff3e00]">
            </div>

            <div class="space-y-1">
              <label class="block text-xs font-medium text-zinc-300">Puntos Clave / Insights (opcional, uno por línea):</label>
              <textarea v-model="newPostForm.keyPoints" rows="3" placeholder="Punto 1: Reducción de latencia con caché SSR...&#10;Punto 2: Tipado estricto..."
                        class="w-full bg-[#16171b] border border-white/10 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-[#ff3e00]"></textarea>
            </div>

            <div class="space-y-1">
              <label class="block text-xs font-medium text-zinc-300">Proyecto Relacionado (opcional):</label>
              <input type="text" v-model="newPostForm.projectName" placeholder="Ej: Portafolio Dos Mundos / Eros Career OS"
                     class="w-full bg-[#16171b] border border-white/10 rounded px-3 py-2 text-xs text-white focus:outline-none focus:border-[#ff3e00]">
            </div>

            <div class="pt-2 border-t border-white/10 flex justify-end gap-2">
              <button type="button" @click="showNewPostModal = false" class="px-4 py-2 rounded bg-white/5 hover:bg-white/10 text-xs text-zinc-400">
                Cancelar
              </button>
              <button type="submit" :disabled="generateLoading"
                      class="px-4 py-2 rounded bg-[#ff3e00] hover:bg-[#e03700] text-[#09090b] font-bold text-xs transition-colors disabled:opacity-50">
                {{ generateLoading ? 'Generando en Gemini...' : 'Generar Omnicanal' }}
              </button>
            </div>
          </form>
        </div>
      </div>

    </div>
  </div>

  <script>
    const { createApp, ref, reactive, computed, onMounted } = Vue

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
        const selectedJob = ref(null)

        // Módulo de Contenido
        const contentPosts = ref([])
        const contentFilter = ref('all')
        const showNewPostModal = ref(false)
        const generateLoading = ref(false)
        const publishLoading = reactive({})
        const expandedSections = reactive({})

        const newPostForm = reactive({
          topic: '',
          keyPoints: '',
          projectName: ''
        })

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

        function copyText(text, successMsg = 'Copiado al portapapeles') {
          if (!text) return
          navigator.clipboard.writeText(text).then(() => {
            showToast(successMsg)
          }).catch(() => {
            showToast('No se pudo copiar', 'err')
          })
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
              if (data.authenticated) {
                loadData()
                loadContentPosts()
              }
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
              loadContentPosts()
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
              fetch('/api/jobs?limit=25', { headers: authHeaders() }),
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

        async function loadContentPosts() {
          try {
            const res = await fetch('/api/content/posts?limit=50', { headers: authHeaders() })
            if (res.ok) {
              const d = await res.json()
              contentPosts.value = d.data || []
            }
          } catch (e) {
            console.error('Error cargando posts:', e)
          }
        }

        const contentDraftsCount = computed(() => {
          return contentPosts.value.filter(p => p.status === 'draft').length
        })

        const contentPublishedCount = computed(() => {
          return contentPosts.value.filter(p => p.status === 'published').length
        })

        const contentRejectedCount = computed(() => {
          return contentPosts.value.filter(p => p.status === 'rejected').length
        })

        const filteredPosts = computed(() => {
          if (contentFilter.value === 'all') return contentPosts.value
          return contentPosts.value.filter(p => p.status === contentFilter.value)
        })

        async function generatePostAction() {
          if (!newPostForm.topic.trim()) return showToast('Ingresá un tema', 'err')
          generateLoading.value = true
          try {
            const points = newPostForm.keyPoints
              .split('\n')
              .map(p => p.trim())
              .filter(p => p.length > 0)

            const body = {
              topic: newPostForm.topic.trim(),
              key_points: points,
              project_name: newPostForm.projectName.trim() || undefined
            }

            const res = await fetch('/api/content/generate', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json', ...authHeaders() },
              body: JSON.stringify(body)
            })

            if (res.ok) {
              showToast('Publicación generada con éxito')
              showNewPostModal.value = false
              newPostForm.topic = ''
              newPostForm.keyPoints = ''
              newPostForm.projectName = ''
              loadContentPosts()
            } else {
              const d = await res.json()
              showToast(d.detail || 'Error generando publicación', 'err')
            }
          } catch (e) {
            showToast('Fallo de conexión al generar post', 'err')
          } finally {
            generateLoading.value = false
          }
        }

        async function publishPost(postId) {
          publishLoading[postId] = true
          try {
            const res = await fetch(`/api/content/posts/${postId}/publish`, {
              method: 'POST',
              headers: authHeaders()
            })
            const d = await res.json()
            if (res.ok && d.ok) {
              showToast('Publicación despachada a n8n')
              loadContentPosts()
            } else {
              showToast(d.detail || 'Falla al despachar a n8n', 'err')
            }
          } catch {
            showToast('Error de red', 'err')
          } finally {
            publishLoading[postId] = false
          }
        }

        async function updatePostStatus(postId, newStatus) {
          try {
            const res = await fetch(`/api/content/posts/${postId}/status`, {
              method: 'PATCH',
              headers: { 'Content-Type': 'application/json', ...authHeaders() },
              body: JSON.stringify({ status: newStatus })
            })
            if (res.ok) {
              showToast(`Estado actualizado: ${newStatus}`)
              loadContentPosts()
            } else {
              showToast('Error actualizando estado', 'err')
            }
          } catch {
            showToast('Error de red', 'err')
          }
        }

        async function deletePost(postId) {
          if (!confirm('¿Eliminar esta publicación?')) return
          try {
            const res = await fetch(`/api/content/posts/${postId}`, {
              method: 'DELETE',
              headers: authHeaders()
            })
            if (res.ok) {
              showToast('Publicación eliminada')
              loadContentPosts()
            }
          } catch {
            showToast('Error al eliminar', 'err')
          }
        }

        function isExpanded(postId, section) {
          return Boolean(expandedSections[`${postId}_${section}`])
        }

        function toggleExpanded(postId, section) {
          const k = `${postId}_${section}`
          expandedSections[k] = !expandedSections[k]
        }

        function formatDate(dt) {
          if (!dt) return '—'
          try {
            return new Date(dt).toLocaleString('es-AR', {
              day: '2-digit', month: '2-digit', year: 'numeric',
              hour: '2-digit', minute: '2-digit'
            })
          } catch {
            return dt
          }
        }

        function openJobModal(job) {
          selectedJob.value = job
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
          selectedJob,
          contentPosts,
          contentFilter,
          filteredPosts,
          contentDraftsCount,
          contentPublishedCount,
          contentRejectedCount,
          showNewPostModal,
          newPostForm,
          generateLoading,
          publishLoading,
          config,
          testing,
          testResult,
          toast,
          login,
          logout,
          loadData,
          loadContentPosts,
          generatePostAction,
          publishPost,
          updatePostStatus,
          deletePost,
          isExpanded,
          toggleExpanded,
          formatDate,
          openJobModal,
          copyText,
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
