# Radar — Opportunity Intelligence Engine

> Motor agnóstico para monitorear, deduplicar y acompañar oportunidades para creadores audiovisuales AI-powered. Deja de perseguir concursos en 20 newsletters, Discord y Telegram. Radar las encuentra, deduplica, registra cambios y te avisa.

**Ya no es "Radar de Concursos". Es Radar.**

El mismo motor monitorea:

- Concursos y festivales (Posterheroes, Runway AIF, AI Film Festival)
- Grants y fondos culturales
- Residencias y becas
- Llamados a artistas / open calls
- Licitaciones creativas
- Programas de aceleración
- Hackathons y desafíos IA
- Programas beta (Runway, Adobe, OpenAI, Leonardo, Pika)

Si funciona para vos personal, tiene potencial para ser producto SaaS para creadores hispanos (no hay nada que haga realmente bien este trabajo en español).

---

## Filosofía

- **Organization-Centric**: Las oportunidades mueren, las organizaciones perduran. Todo cuelga de `organizations`.
- **Two Clocks**: Discovery semanal (busca nuevas orgs/sources) separado de Monitoring cada 12h (vigila fuentes conocidas). No rastrear Google cada 12h.
- **Fingerprint, not URL**: Misma oportunidad en 5 URLs (revista, oficial, PDF, IG, LinkedIn) = 1 registro con `alternate_links_json`. Hash `SHA256(org|title_agresivo|deadline|type|country|url)` + RapidFuzz.
- **Everything has a history**: `opportunity_history` registra cada cambio deadline, premio, status. No sobreescribir. Info oro para watchlist.
- **Assistant, not Search**: Valor no es "encontré 20", es "te avisé T-7 de la que te interesaba y detecté que extendieron plazo". Watchlist + notifications T-30,15,7,3,1.
- **Config over Code**: `config/config.yaml` gobierna TODO: plugins enabled/schedule/priority, logging, scoring. Cero tocar código para activar conector.
- **Headless First**: `python -m radar digest` es la única UI inicial. El agente puede vivir semanas headless.
- **Core Agnóstico**: Ninguna regla específica de org en `core/`, toda en `plugins/<org>/`. Loader como boundary.
- **Scoring deshabilitado hasta 300 opps**: No programar heurística basada en intuición. Juntar datos reales primero.

---

## Arquitectura v3.0 — Plataforma, no componentes sueltos

```
Plugin Loader          ✅ - Descubrimiento dinámico filesystem, validación manifest, aislamiento fallos, enable/disable YML, prioridades, 0 manual imports
Runtime                ✅ - Instanciación dinámica via importlib, lifecycle CREATED->INITIALIZED->RUNNING->STOPPED->FAILED, reload sin leaks, concurrencia 10 threads 0 crashes
Monitoring             ✅ - Orquestador Provider->Normalize->Fingerprint->Database->Logs, transacción atómica BEGIN->update+history+alternate->COMMIT, idempotencia, métricas
History                ✅ - Subsistema propio Opportunity->OpportunityHistory, first_seen inmutable, last_seen siempre, nunca borrar solo closed, idempotencia
Notification           ✅ - Idempotencia exacta 1 por evento (new, deadline_changed, reminder, closed, watchlist), consola + logs, sin email, Evento->Notification->Canal futuro
Fingerprint            ✅ - API congelada v1, 12 funcs normalización independientes, solo info estable, 2 niveles exacta y aproximada RapidFuzz
Deduplicación          ✅ - Exact hash + approximate lógica estricta URL igual + title>=0.85 para deadline extendido o URL diferente + title>=0.95 + deadline mismo para cross-source
Database               ✅ - SQLite WAL, FK ON, 9 tablas, vistas, idempotencia
Scheduler              ✅ - APScheduler real BackgroundScheduler, ThreadPoolExecutor, CronTrigger, jobs independientes, aislamiento, traceback, retry configurable
Logs                   ✅ - Separados por job, RotatingFileHandler
Métricas               ✅ - SourceMetrics y MonitoringMetrics completas
Idempotencia           ✅ - Transacción atómica, alternate_links y history idempotentes, crash rerun no duplica
```

**Flow validado con providers reales:**

```
Plugin (manifest.yaml + plugin.py candidate_urls + fetch_first_success + extract + normalize)
  ↓
Provider (fetch httpx fallback chain 3 URLs + Playwright opcional -> extract BeautifulSoup -> normalize)
  ↓
Normalize (NormalizedOpportunity)
  ↓
Fingerprint (hash + is_duplicate exact + approximate)
  ↓
History (first_seen inmutable, last_seen siempre, record_deadline_change, never_lose_history)
  ↓
Database (insert only new transacción atómica idempotente, first_seen nunca cambia)
  ↓
Notification (new_opportunity, deadline_changed con idempotencia exacta, consola y logs)
  ↓
Logs (monitor.log) -> Métricas
```

Sin excepciones en core, funciona igual para cualquier plugin futuro.

---

## Estado Actual — Infraestructura Cerrada Formalmente

- **Tickets 001-010 aprobados**, 53-69 tests OK según fase
- **Doctor:** `RESULT: OK (with WARN expected playwright optional)` - 9 discovered dynamic, 9 valid, 5 enabled, 5 loadable, 5 instantiated
- **Fingerprint:** v1 API congelada, 17 tests OK
- **Plugin Loader Runtime:** v2 + hardening reload sin leaks, concurrencia, close exception, 9+3 tests OK, 0 manual imports
- **Monitoring Engine:** 6 tests OK, transacción atómica, idempotencia, métricas
- **Opportunity History:** 7 tests OK, primera inmutable, última siempre, nunca perder historial
- **Notification Engine:** 7 tests OK, idempotencia exacta por evento, consola y logs, no email
- **Scheduler Runtime:** 6 tests OK, jobs independientes, aislamiento fallos, traceback, reintento configurable
- **Primer Provider Real:** Posterheroes 15 - Still Human extraído real, deduplicación OK, persistencia OK, logs OK, notificaciones OK, sin excepciones core
- **Scoring:** DISABLED hasta 300 opps reales

**Decisión senior:** Detener core, no agregar más managers/engines/capas. Mayor ROI viene de incorporar providers reales, endurecer parsers con tests de fixtures (como posterheroes_2026.html), acumular datos reales.

---

## Quickstart

```bash
# 1. Clonar
git clone https://github.com/villainslabs-git/radar.git
cd radar

# 2. venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Opcional para scrapers con JS:
playwright install chromium

# 3. DB (reproducible)
python3 scripts/init_db.py
# Crea data/radar.db con 9 orgs, 9 sources, 10 tablas, vistas

# 4. Validar infra
python3 -m radar doctor
# RESULT: OK

python3 -m radar plugins
# 9 discovered dynamic, 5 enabled, 5 loadable, 5 instantiated

python3 -m radar schedule
# DAILY 5 jobs priority orden

# 5. Tests (69 tests OK)
python3 tests/unit/test_fingerprint.py
python3 tests/unit/test_plugin_loader.py
python3 tests/unit/test_plugin_loader_hardening.py
python3 tests/unit/test_plugin_loader_runtime.py
python3 tests/unit/test_monitoring_engine.py
python3 tests/unit/test_opportunity_history.py
python3 tests/unit/test_notification_engine.py
python3 tests/unit/test_scheduler_runtime.py
python3 tests/plugins/posterheroes/test_posterheroes_extract.py

# 6. Primer provider real (Posterheroes)
python3 -m radar monitor --batch-size 1
# Fetched 1 new 1, DB count 1, Notifications 1, Logs monitor.log [NEW]

python3 -m radar digest
# Headless MVP: Total oportunidades: 1, Fuentes activas: 9

# 7. Ver notificaciones
python3 -c "from core.db import get_db; db=get_db(); print(db.get_pending_notifications())"
```

---

## Estructura

```
radar/
├── config/config.yaml       # Fuente de verdad, gobierna plugins enabled/schedule/priority, logging, scoring.enabled=false, scheduler retries
├── data/
│   ├── radar.db             # SQLite (ignorado en git, se genera con init_db.py)
│   ├── schema.sql           # DDL 10 tablas + vistas
│   ├── seed/                # Seeds YAML orgs y sources
│   │   ├── organizations.yaml (9 orgs)
│   │   └── sources.yaml (9 sources)
│   └── raw/                 # HTML crudo debug (ignorado, .gitkeep)
├── core/                    # Lógica pura, agnóstica, sin reglas org específicas
│   ├── db.py                # RadarDB wrapper WAL+FK, validate_integrity, CRUD oportunidades, history, notifications, watchlist, idempotencia
│   ├── fingerprint.py       # FingerprintEngine v1 API congelada, 12 funcs normalización independientes, solo info estable
│   ├── history.py           # HistoryTracker detect_changes por campo
│   ├── opportunity_history.py # OpportunityHistorySystem nunca pierde, first_seen inmutable, last_seen siempre, deadline/URL/status/description
│   ├── notification_engine.py # NotificationEngine idempotencia exacta por evento, consola y logs, no email, canales futuro
│   ├── monitoring_engine.py # MonitoringEngine SourceMetrics/MonitoringMetrics, monitor_source Provider->Normalize->Fingerprint->DB->Logs, transacción atómica, idempotencia, approximate duplicate lógica estricta, monitor_all
│   ├── plugin_loader.py     # Plugin Loader Runtime v2, discovery dinámico filesystem sin lista manual, validación manifest, aislamiento fallos, enable/disable YML, prioridades, lifecycle CREATED->INITIALIZED->RUNNING->STOPPED->FAILED, candidate_urls + fetch_first_success genérico
│   ├── provider.py          # Provider ABC fetch/extract/normalize/validate/run, FetchResult, RawOpportunity, NormalizedOpportunity, candidate_urls + fetch_first_success genérico, fetch_single
│   ├── logger.py            # setup_logger RotatingFileHandler 5MBx3, formato senior, get_logger
│   ├── config.py            # Config loader dot notation, singleton, validate
│   └── doctor.py            # Doctor robusto v2.1, usa PluginLoader real, 9 discovered dynamic, valid, enabled, loadable, fingerprint API frozen, scheduler jobs
├── plugins/                 # Uno por organización, cada uno con manifest.yaml + plugin.py
│   ├── base.py              # Re-export Provider
│   ├── registry.py          # Old registry (compat, loader real es plugin_loader.py)
│   ├── runway/              # contest, grant, beta, festival, playwright, priority 10, enabled true (skeleton, próximo real)
│   │   ├── manifest.yaml
│   │   └── plugin.py
│   ├── posterheroes/        # contest, festival, beautifulsoup, priority 10, enabled true - PRIMER REAL IMPLEMENTADO
│   │   ├── manifest.yaml
│   │   └── plugin.py        # Real: fetch httpx fallback chain 3 URLs, extract BeautifulSoup deadline 31st July 2026 awards €2,500/€1,500, normalize float
│   ├── adobe/               # residency, grant, beta
│   ├── leonardo/            # contest, beta, disabled
│   ├── openai/              # grant, residency, beta, disabled
│   ├── itsnicethat/         # aggregator, enabled
│   ├── filmfreeway/         # aggregator, disabled
│   ├── ai-film-festival/    # festival, contest, enabled
│   └── pika/                # contest, beta, disabled
├── jobs/
│   ├── scheduler.py         # RadarScheduler simple (imprime schedule)
│   ├── scheduler_runtime.py # SchedulerRuntime real 400 líneas BackgroundScheduler ThreadPoolExecutor CronTrigger, 5 jobs discover/monitor/notify/cleanup/healthcheck independientes, with_retry_and_isolation, JobResult, add_jobs desde YAML, start/shutdown, run_job_now
│   └── monitoring.py        # run_monitoring() real usa MonitoringEngine
├── cli/
│   └── main.py              # Typer + Rich CLI: doctor, init-db, stats, plugins, schedule, digest, monitor (real), discover, version
├── radar/
│   ├── __init__.py
│   └── __main__.py          # python -m radar
├── tests/
│   ├── unit/
│   │   ├── test_fingerprint.py (17 tests)
│   │   ├── test_plugin_loader.py (7 tests)
│   │   ├── test_plugin_loader_hardening.py (3 tests reload sin leaks, concurrencia, close exception)
│   │   ├── test_plugin_loader_runtime.py (9 tests discovery, manifest, dynamic load 0 manual imports, instanciar, lifecycle, enable/disable, prioridades, errores sin detener)
│   │   ├── test_monitoring_engine.py (6 tests ejecutar providers, deduplicación exact+approximate, registrar cambios, errores aislados, logs y métricas, flujo completo sin scoring)
│   │   ├── test_opportunity_history.py (7 tests primera/última aparición, deadline, URL, estado, descripción, nunca perder historial, historial completo 7 eventos)
│   │   ├── test_notification_engine.py (7 tests nuevas, deadline cambiado, deadline próximo, cerrada, watchlist, consola y logs, exactamente una por evento)
│   │   └── test_scheduler_runtime.py (6 tests creación y jobs, independientes, aislamiento fallos, traceback, reintento configurable, cron parsing)
│   └── plugins/
│       └── posterheroes/
│           ├── posterheroes_2026.html (47KB fixture real de www.posterheroes.org)
│           └── test_posterheroes_extract.py (7 tests robustez scraper)
│   └── fixtures/
│       └── runway_2026.html (136KB fixture real de aif.runwayml.com)
├── logs/                    # Logs separados por job (ignorado en git, .gitkeep)
├── scripts/
│   ├── init_db.py           # Recreation reproducible DB
│   ├── TICKET_001_REPORT.md ... TICKET_010_REPORT.md (reportes por ticket)
│   └── ...
├── config/config.yaml
├── schema.sql
├── TICKETS.md               # Backlog tickets atómicos, 001-010 aprobados, infraestructura cerrada, fase 2 providers reales abierta
├── architecture_description_v3.md
├── BACKLOG_TECNICO.md       # Hardening transacción atómica ✅, idempotencia ✅, escalabilidad O(n) documentada, reload sin leaks, canales futuro Evento->Notification->Canal
├── PROJECT_CLOSED_CORE_ARCHITECTURALLY_COMPLETE.md
├── HANDOVER_TO_HERMES.md    # Handover para HERMES Agent orquestador
└── ORCHESTRATION_PROTOCOL_HERMES.md
```

---

## Comandos

```bash
python -m radar doctor          # Diagnóstico integral 9 discovered, 5 enabled, 5 loadable, fingerprint API frozen, scheduler jobs, RESULT OK
python -m radar plugins         # Lista 9 discovered dynamic, status, schedule, priority, has_code, manifest_valid
python -m radar plugins --enabled # Solo 5 enabled respetando config.yaml
python -m radar schedule        # DAILY 5 jobs priority orden + SYSTEM JOBS discover/monitoring
python -m radar stats           # DB counts, plugins discovered/enabled/loadable, scoring DISABLED
python -m radar digest          # Headless MVP: Total oportunidades, fuentes activas, fase recolección
python -m radar monitor --batch-size 5  # El Vigilante: ejecuta providers -> fingerprint -> DB -> logs -> métricas, sin scoring
python -m radar monitor --batch-size 1  # Solo 1 source (ej. posterheroes)
python scripts/init_db.py       # Recrea DB reproducible
```

---

## Tickets — Trabajo por tickets atómicos

Ver `TICKETS.md` — Metodología tickets pequeños verificables, si algo se rompe no rompe resto, cada ticket genera `TICKET_XXX_REPORT.md`.

**Completados 001-010 aprobados:**

- 001 Bootstrap, renaming Radar
- 002 Núcleo reproducible, plugins folder, provider interface, logger, config, db, doctor, scoring DISABLED
- 003 Fingerprint Engine v1, registro dinámico, doctor robusto v2, API congelada, 17 tests
- 004 Plugin Loader Real, boundary core<->plugins, 7 tests
- 005 Plugin Loader Runtime, discovery dinámico, validación manifest, carga dinámica via importlib sin manual imports, instanciación, lifecycle, enable/disable YML, prioridades, aislamiento fallos, hardening reload sin leaks, concurrencia, close exception, 9+3 tests
- 006 Monitoring Engine, orquestador, history tracker, transacción atómica BEGIN->update+history+alternate->COMMIT, idempotencia, métricas, 6 tests
- 007 Opportunity History, sistema historial nunca pierde, first_seen inmutable, last_seen siempre, deadline/URL/status/descripción, 7 tests
- 008 Notification Engine, idempotencia exacta 1 por evento, consola y logs, no email, integración monitoring, 7 tests, nota futura canales Evento->Notification->Canal hoy LOG mañana EMAIL/DISCORD/SLACK/WEBHOOK
- 009 Scheduler Runtime, APScheduler real BackgroundScheduler ThreadPoolExecutor CronTrigger, 5 jobs independientes Discover/Monitor/Notify/Cleanup/HealthCheck, aislamiento fallos, traceback, reintento configurable desde YAML, cron parsing, 6 tests, núcleo arquitectónicamente completo, plataforma lista
- 010 Primer Provider Real Posterheroes, fetch httpx fallback chain 3 URLs, extract BeautifulSoup, normalize float, pipeline sin excepciones Plugin->Provider->Normalize->Fingerprint->History->Database->Notification->Logs->Metrics, 1 oportunidad real extraída deduplicación OK persistencia OK logs OK, fixture HTML 47KB + 7 tests robustez, fix economic_value float y candidate_urls genérico

**Total: 53-69 tests OK (según fase), Doctor OK**

**Fase actual:** Infraestructura principal cerrada formalmente, Fase 2 Providers Reales abierta como prueba de arquitectura. Mayor ROI viene de incorporar providers reales, endurecer parsers con fixtures, acumular datos reales (objetivo 300 antes de scoring).

**Próximos:**
- 011 Runway Real (playwright) validando deduplicación cross-source misma oportunidad en runway oficial + itsnicethat -> 1 registro alternate_links
- 012 Adobe Real + AI Film Festival + It's Nice That
- 013 Integration Test 50-100 opps reales

Ver `NEXT_TICKET.md` para Ticket 011.

---

## Backlog Técnico

Ver `BACKLOG_TECNICO.md`:

- Transacción atómica por oportunidad ✅ Implementado
- Idempotencia monitor_all crash rerun ✅ Implementado
- Escalabilidad duplicate approximate O(n) -> FTS5, deadline bucket, embeddings cuando >1k 📝 Documentado
- Reload sin leaks, concurrencia, close exception ✅ Implementado
- Canales notificación Evento->Notification->Canal hoy LOG mañana EMAIL/DISCORD/SLACK/WEBHOOK 📝 Documentado futuro
- Persistencia scheduler MemoryJobStore hoy MVP OK, producción SQLAlchemyJobStore 📝 Documentado futuro
- Observabilidad radar jobs tabla Discover OK Monitor OK Notify FAIL x2 📝 Documentado futuro
- Versionado snapshots y Event sourcing parcial 📝 Documentado futuro

---

## Roadmap

- **Fase 1: Fundación (Tickets 001-005)** ✅ COMPLETADA - Infraestructura principal
- **Fase 2: Inteligencia (Tickets 006-008)** ✅ COMPLETADA - Monitoring, History, Notification, métricas, logs, idempotencia
- **Fase 2b: Scheduler Runtime (Ticket 009)** ✅ COMPLETADA - Núcleo arquitectónicamente completo, plataforma lista
- **Fase 3: Primer Provider Real (Ticket 010)** ✅ COMPLETADA - Posterheroes 15 Still Human extraído real, arquitectura validada sin excepciones core
- **Fase 4: Providers Reales (Tickets 011-013)** - Próximo foco: Runway Real (playwright) cross-source, Adobe, AI Film Festival, Integration Test 50-100 opps
- **Fase 5: Headless UX + LLM On-Demand** - Digest mejorado, Ollama Qwen 7B
- **Fase 6: Producto (Futuro)** - API FastAPI local, Chrome Extension, Multi-user SaaS (después de 6 meses validado personal)

---

## Licencia

MIT - Ver LICENSE

## Autor

VillainsLabs / Radar Team

> Si funciona para vos personal 6 meses, tiene potencial para ser producto SaaS para creadores hispanos. Primero resolver tu problema impecable, después pensar en abrirlo a otros.
