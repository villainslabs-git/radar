# HANDOVER TO HERMES AGENT - Radar Opportunity Intelligence Engine

**Fecha:** 2026-07-26
**De:** Agente Principal (Tickets 001-004 completados)
**Para:** HERMES AGENT (continuará orquestando tickets mientras owner no está)
**Proyecto:** Radar - Opportunity Intelligence Engine (no "Radar de Concursos")

---

## 1. Visión y Filosofía (NO PERDER)

**Nombre oficial:** `Radar - Opportunity Intelligence Engine` (cambio estratégico Ticket 001 aprobado como mejor decisión)

**Ya no es scraper de concursos.** Es motor genérico que monitorea:
- concursos, grants, residencias, becas, fellowships
- aceleradoras, hackathons, beta programs, challenges
- calls for artists, licitaciones creativas, festivales, aggregators

Mismo motor: `organizations`, `fingerprint`, `notifications`, `watchlist`. Solo cambian fuentes y selectors.

**Potencial producto:** Si funciona para owner 6 meses, puede ser SaaS hispano para creadores IA. Hoy no hay nada que deduplique, siga cambios y priorice por perfil en español. Construir con mentalidad producto desde día 0, pero primero resolver problema personal impecable.

**Principios arquitectura (congelados):**
1. **Organization-Centric, no Opportunity-Centric:** Oportunidades mueren, orgs perduran. Todo cuelga de `organizations`
2. **Two Clocks:** Discovery semanal (busca nuevas orgs/sources) separado de Monitoring cada 12h (vigila fuentes conocidas). No rastrear Google cada 12h.
3. **Fingerprint, not URL:** Misma oportunidad en 5 URLs (revista, oficial, PDF, IG, LinkedIn) = 1 registro con `alternate_links_json`. Hash SHA256(org|title_agresivo|deadline|type|country|url_normalizada) + RapidFuzz
4. **Everything has a history:** `opportunity_history` registra cada cambio deadline, prize, status. No sobreescribir. Info oro para watchlist.
5. **Assistant, not Search Engine:** Valor no es "encontré 20", es "te avisé T-7 de la que te interesaba y detecté que extendieron plazo". `watchlist` + `notifications` T-30,15,7,3,1
6. **Config over Code:** `config/config.yaml` gobierna TODO: plugins enabled/schedule/priority, logging, scoring, etc. Cero tocar código para activar conector.
7. **Headless First:** UI última. Agente vive semanas headless con CLI: `python -m radar digest` -> "Hay 3 nuevas, 1 cambió deadline, 2 cerraron". Suficiente para núcleo funcionando.
8. **Core Agnostic:** Ninguna regla específica de org en core/. Toda lógica org en `plugins/<slug>/`. Loader como boundary.
9. **Scoring deshabilitado hasta 300 opps:** Senior advice. No programar heurística basada en intuición. Juntar 300 oportunidades reales, ver cuáles se presentan, recién ahí construir score.

---

## 2. Estado Actual - Tickets Completados

### TICKET 001: Bootstrap [COMPLETADO]
- Estructura carpetas: `config/`, `data/`, `data/db/`, `data/raw/`, `data/seed/`, `core/`, `jobs/`, `cli/`, `scrapers/`, `plugins/`, `plugins/*/`, `logs/`, `scripts/`, `tests/unit/`, `radar/`
- `requirements.txt` mínimo (pyyaml, rapidfuzz, httpx, beautifulsoup4, playwright, apscheduler, rich, typer, unidecode, etc)
- `README.md` con filosofía Opportunity Intelligence Engine
- `TICKETS.md` backlog hasta 017
- `data/radar.db` creado, 10 tablas, 9 orgs seed, 9 sources seed
- `radar/` package entry para `python -m radar`
- Renaming oficial Radar

### TICKET 002: Núcleo reproducible [COMPLETADO - redefinido por review senior]
- `plugins/` folder (9 plugins: runway, posterheroes, adobe, leonardo, openai, itsnicethat, filmfreeway, ai-film-festival, pika) cada con manifest.yaml + plugin.py skeleton
- `core/provider.py`: Interfaz abstracta `Provider` con `fetch()` -> `FetchResult`, `extract()` -> `List[RawOpportunity]`, `normalize()` -> `NormalizedOpportunity`, `validate()`, `run()` pipeline. Desacopla scraping de HTML vs RSS vs API vs MCP futuro. `RSSProvider` ejemplo futuro
- `core/logger.py`: `setup_logger(name, log_file, level)` con RotatingFileHandler 5MBx3, formato senior `timestamp | level | job | message`, factories `monitor_logger()`, `discover_logger()`, `get_logger(name)`
- `core/config.py`: `Config` class con dot notation `get("plugins.runway.enabled")`, `get_plugins()`, `is_plugin_enabled()`, `get_plugin_schedule()`, `validate()`, hot-reload, singleton `get_config()`
- `core/db.py`: `RadarDB` wrapper con context manager WAL+FK ON, `validate_integrity()` tablas, counts, FK check, views, `insert_organization()`, `insert_source()`
- `core/doctor.py` v1: checks Python, deps, SQLite, Playwright, DB file, tables, FK, config, plugins, logs dir, scheduler
- `cli/main.py`: Typer+Rich CLI con `doctor`, `init-db`, `stats`, `digest`, `monitor` placeholder, `discover` placeholder, `version`
- `config/config.yaml`: gobernado TODO, plugins enabled/schedule/priority, opportunity_types genérico, scoring.enabled=false, deduplication thresholds
- `data/seed/organizations.yaml` (9 orgs) y `sources.yaml` (9 sources)
- `scripts/init_db.py`: recreation reproducible con backup, carga seeds, validación
- `logs/.gitkeep`

Comandos validados:
```
python scripts/init_db.py -> OK 9 orgs 9 sources
python -m radar doctor -> All systems OK
python -m radar stats -> tabla counts + plugins
python -m radar digest -> headless MVP
```

### TICKET 003: Fingerprint Engine v1 [COMPLETADO]
- **Observaciones Ticket 002 incorporadas:** registro dinámico filesystem sin listas manuales, doctor robusto v2 (chromium cache, manifest invalid, enabled without code, schema incorrect, perms), fingerprint structure frozen v1, core agnostic
- **`core/fingerprint.py` (800 líneas, independiente, sin scoring, sin scrapers):**
  - Funciones independientes testeables: `remove_invisible_chars`, `normalize_whitespace`, `to_lowercase`, `remove_accents` (unidecode fallback), `strip_tracking_params` (utm_*, fbclid, gclid, igshid... + sort query), `normalize_url` (lower host, remove www., default ports, trailing slash, fragment, tracking, sort query, lower path), `normalize_title` (invisible+whitespace+lower+accents), `normalize_title_for_hash` (solo alfanum [a-z0-9] trunc 60 -> "Poster Heroes 2026" == "posterheroes2026"), `normalize_org` (agresivo), `normalize_deadline` (datetime, date, timestamp, ISO, fuzzy), `normalize_opportunity_type`, `normalize_country`
  - Solo info estable: URL normalizada, Org, Título, Deadline, Tipo, País. NO premios, descripción, IA, scoring
  - Hash: `SHA256(org|title_hash_agresivo|deadline|type|country|url)[:16]`
  - Dos niveles: Nivel1 exacta hash idéntico -> 1.0, Nivel2 aproximada RapidFuzz `ratio + token_sort_ratio` (Posterheroes vs Poster Heroes), deadline dentro delta 15 días, org match 0.3 peso si org diferente evita falsos positivos, overall `title*0.7 + deadline*0.15 + type*0.10 + country*0.05`, URL exact boost 0.95, threshold configurable `deduplication.title_similarity_threshold 0.85` desde config.yaml
  - Preparado para embeddings futuros sin romper API: `Fingerprint.metadata` dict, `compare()` puede incorporar semántica después
  - API congelada:
    ```python
    engine = FingerprintEngine()
    fp = engine.generate(opportunity) # dict, NormalizedOpportunity, object
    duplicate = engine.is_duplicate(fp, database) # List[Fingerprint] | RadarDB | sqlite conn | Path
    similarity = engine.compare(fp1, fp2) # float 0-1
    ```
  - Dataclasses: `Fingerprint` frozen (hash, normalized_url, normalized_title, normalized_title_hash, normalized_org, normalized_deadline, normalized_type, normalized_country, version, metadata), `DuplicateResult` (is_duplicate, level exact/approximate/none, existing, similarity, matched_on)
- **Tests:** `tests/unit/test_fingerprint.py` 17 OK (invisible, whitespace, lower, accents, tracking, URL, title, title_hash, org, deadline, consistente, exacta, URLs equivalentes, títulos aproximados, distintos, is_duplicate lista, no usa premios, API estable) + `scripts/test_fingerprint_db.py` 5 OK con DB real (tracking removal exact duplicate, approximate, distinto no duplicado)
- **Resultado:** Cuando scrapers traigan 300 opps desde múltiples fuentes, 1 representación única con `alternate_links_json`

### TICKET 004: Plugin Loader Real [COMPLETADO]
- **`core/plugin_loader.py` (400 líneas):** Boundary real core<->plugins
  - **Registro dinámico 100% filesystem:** `scan()` recorre `plugins/`, lee `manifest.yaml`, sin lista manual en core. Si no hay manifest.yaml, skip. YAML parse error -> manifest inválido para reporte doctor. `validate_manifest()` verifica required fields (name, slug, provider_type), slug==folder, provider_type permitido, opportunity_types permitidos.
  - **Aislamiento fallos:** `_load_plugin_class()` con `importlib.util.spec_from_file_location`, `exec_module` wrapped try/except + traceback, nunca lanza hacia core, retorna (cls, error). Un plugin roto con SyntaxError marca LOAD_FAILED pero otros 2 buenos siguen loadable.
  - **Respeta enable por YML:** `load_all()` lee `config.yaml plugins.<slug>.enabled, schedule, priority`, por defecto DISABLED seguro, `get_enabled_plugins()` solo enabled, `get_loadable_plugins()` solo is_loadable (enabled+valid+has_code+LOADED+class not None)
  - **Integración scheduler:** `get_jobs()` retorna jobs con slug, name, schedule, priority, provider_type, opportunity_types, enabled, status, version, folder, ordenados por schedule (hourly<every 6h<every12h<daily<weekly) y priority desc, solo enabled válidos. `jobs/scheduler.py` delega 100% a loader: `get_schedule_by_frequency()`, `print_schedule()`, `validate_schedules()`, `get_next_run_info()`
  - **Core agnóstico:** sin if slug=="runway", verificado grep y doctor Core:agnostic OK
  - **Dataclasses:** `PluginManifest`, `LoadedPlugin` (is_loadable, to_job_definition), `PluginStatus` Enum (VALID, INVALID_MANIFEST, MISSING_CODE, LOAD_FAILED, DISABLED, ENABLED, LOADED), `get_status_report()` con total_discovered, enabled, loadable, invalid, missing_code, load_failed, orphans, jobs
  - **Hot-reload:** `reload()` filesystem + config
  - **Singleton:** `get_plugin_loader()`, `get_enabled_plugins()`, `get_loadable_plugins()`, `get_jobs_for_scheduler()`
- **`jobs/scheduler.py`:** `RadarScheduler` usa loader, jobs independientes discover->monitor->score(disabled)->notify
- **`core/doctor.py` v2.1:** ahora usa `PluginLoader` real: Plugins:Discovered 9 dynamic, Valid, Enabled respeta YML, Loadable, detecta manifest inválidos FAIL, missing_code WARN, load_failed FAIL aislado, orphans WARN, PluginLoader OK, Scheduler:jobs OK 5 jobs from loader respeta enable YML
- **`cli/main.py`:** nuevos comandos `radar plugins` (all discovered dynamic), `radar plugins --enabled` (respeta YML), `radar schedule` (agrupado por frecuencia + system jobs), `stats` usa loader real
- **Tests:** `tests/unit/test_plugin_loader.py` 7 OK: discovery dinámico sin lista manual, validación manifests detecta inválidos y slug mismatch, enable por YML 5 enabled, aislamiento fallos (broken no rompe core), integración scheduler (jobs con schedule/priority respetando enable), core agnóstico, reload hot-reload
- **Validación:** `radar doctor` OK, `radar plugins` 9 discovered 5 enabled 5 loadable, `radar schedule` DAILY 5 jobs priority orden

---

## 3. Estructura Actual de Carpetas (para HERMES)

```
.
├── config/
│   └── config.yaml # Fuente verdad, gobierna plugins enabled/schedule/priority, logging, scoring.enabled=false, deduplication thresholds
├── data/
│   ├── radar.db # SQLite 128KB, 9 orgs, 9 sources, 0 opps (fase recolección)
│   ├── schema.sql # DDL 10 tablas + vistas
│   ├── seed/
│   │   ├── organizations.yaml # 9 orgs seed
│   │   └── sources.yaml # 9 sources seed
│   ├── db/.gitkeep
│   └── raw/.gitkeep # HTML crudo debug
├── core/
│   ├── __init__.py # __version__ 3.0.0
│   ├── logger.py # setup_logger, RotatingFileHandler, get_logger
│   ├── provider.py # Provider ABC fetch/extract/normalize/validate/run, FetchResult, RawOpportunity, NormalizedOpportunity
│   ├── config.py # Config loader dot notation, singleton
│   ├── db.py # RadarDB wrapper, validate_integrity, CRUD helpers
│   ├── fingerprint.py # FingerprintEngine v1 API congelada, 12 funcs normalización independientes
│   ├── plugin_loader.py # Plugin Loader Real v1, boundary, dynamic filesystem, isolation
│   └── doctor.py # Doctor v2.1 robusto, usa loader real
├── plugins/
│   ├── base.py # Re-export Provider
│   ├── registry.py # Old registry, aún usado fallback, pero loader es nuevo real (mantener para compat)
│   ├── runway/ # contest, grant, beta, festival, playwright, priority 10, enabled true
│   │   ├── manifest.yaml # name, slug, provider_type, opportunity_types, version, description
│   │   └── plugin.py # RunwayProvider skeleton (httpx fetch, extract empty)
│   ├── posterheroes/ # contest, festival, beautifulsoup, priority 10, enabled true
│   ├── adobe/ # residency, grant, beta, priority 9, enabled true
│   ├── leonardo/ # contest, beta, priority 7, enabled false
│   ├── openai/ # grant, residency, beta, accelerator, api, priority 7, enabled false, sin plugin.py (skeleton)
│   ├── itsnicethat/ # aggregator, daily, enabled true
│   ├── filmfreeway/ # aggregator, playwright, weekly, enabled false
│   ├── ai-film-festival/ # festival, contest, daily, enabled true
│   └── pika/ # contest, beta, weekly, enabled false
├── jobs/
│   ├── __init__.py
│   └── scheduler.py # RadarScheduler usa loader.get_jobs(), print_schedule()
├── cli/
│   ├── __init__.py
│   └── main.py # Typer+Rich CLI: doctor, init-db, stats, plugins, schedule, digest, monitor, discover, version
├── radar/
│   ├── __init__.py
│   └── __main__.py # Entry python -m radar -> cli.main.app
├── scripts/
│   ├── setup_venv.sh
│   ├── init_db.py # Recreation reproducible
│   ├── test_fingerprint_db.py # Integración DB fingerprint
│   ├── TICKET_001_REPORT.md
│   ├── TICKET_002_REPORT.md
│   ├── TICKET_003_REPORT.md
│   └── TICKET_004_REPORT.md
├── tests/
│   └── unit/
│       ├── test_fingerprint.py # 17 tests
│       └── test_plugin_loader.py # 7 tests
├── logs/
│   ├── .gitkeep
│   ├── db.log # 1183 bytes
│   ├── doctor.log
│   ├── core.log
│   └── ... # monitor.log, discover.log, scheduler.log, provider.log se crean en primer run
├── requirements.txt # pyyaml, unidecode, rapidfuzz, httpx, bs4, lxml, playwright, readability-lxml, apscheduler, rich, typer, ollama, openai, pytest
├── .gitignore
├── README.md # Visión Opportunity Intelligence Engine
├── TICKETS.md # Backlog hasta 017, 004 completados
├── architecture_description_v3.md # Arquitectura v3.0 Radar (10/10 objetivo)
├── schema.sql # Copia root de DDL
├── IMPLEMENTATION_GUIDE.md # Guía rápida implementación v3.0
└── HANDOVER_TO_HERMES.md # Este archivo
```

---

## 4. Comandos Clave (para HERMES, usar siempre)

### Validación rápida (antes de cualquier ticket)
```bash
python3 -m radar doctor # Debe decir RESULT: OK (with WARN expected) - playwright optional es WARN ok
python3 -m radar plugins # 9 discovered dynamic, 5 enabled
python3 -m radar plugins --enabled # solo 5 respetando config.yaml
python3 -m radar schedule # DAILY 5 jobs priority orden
python3 -m radar stats # DB counts + plugins discovered/enabled/loadable
python3 -m radar digest # Headless MVP "Total oportunidades: 0 - Fase recolección"
python scripts/init_db.py # Recrea DB si schema cambia
```

### Tests (correr después de cada ticket)
```bash
python3 tests/unit/test_fingerprint.py # 17 tests OK
python3 tests/unit/test_plugin_loader.py # 7 tests OK
python3 scripts/test_fingerprint_db.py # 5 tests DB OK
```

### Configuración
```bash
cat config/config.yaml # Fuente verdad
# Para activar/desactivar plugin, editar enabled true/false, no tocar código
# plugins:
#   runway: {enabled: true, schedule: daily, priority: 10}
```

---

## 5. Convenciones de Trabajo - Tickets Pequeños (MANTENER)

**Metodología owner:**
- Tickets muy pequeños, como dev senior trabajando en repo
- Un ticket = un módulo testeable aislado. Si algo se rompe, no rompe resto. Corregir módulo sin romper resto.
- Definición Done por ticket:
  1. Código en su módulo con type hints
  2. Test manual o script en `scripts/test_ticket_XXX.py` o `tests/unit/`
  3. No rompe tickets anteriores (correr tests)
  4. Actualiza `TICKETS.md` marcando [x]
  5. Crea `scripts/TICKET_XXX_REPORT.md` con qué se hizo, validación, decisiones senior
  6. `radar doctor` sigue OK

**Cómo pedir ticket:**
- Usuario: "Ejecutar TICKET 005" con descripción
- Agente: Implementa solo ese ticket, entrega archivos + prueba, no hace más

**Filosofía tickets:**
- Headless first: UI última, motor por consola 2 meses, UI después es cliente del motor
- Requirements mínimos: no agregar 20 frameworks, mantener entendible
- Logs desde día 0: `core/logger.py` con `get_logger("monitor")`, no print()
- Provider interface desde día 0: `core/provider.py` con fetch/extract/normalize, futuro RSS, API, JSON, Github, Google Alerts, MCP sin romper
- Scoring NO implementar hasta 300 opps reales (senior advice). Acumular 300, ver cuáles se presentan, recién ahí construir score. Evitar heurística basada en intuición.
- Core agnóstico: ninguna regla org en core, toda en plugins/
- Config gobierna TODO: plugins enabled/schedule/priority, logging, etc
- Jobs independientes: discover -> monitor -> score(disabled) -> notify, nunca uno gigante, facilita debugging

---

## 6. Backlog de Tickets (para HERMES continuar)

Ver `TICKETS.md` para lista completa hasta 017.

**Tickets completados 001-004** (no repetir).

**Tickets pendientes sugeridos (en orden recomendado):**

- [ ] **TICKET 005: `core/history.py` + `core/notifications.py` + `core/watchlist.py`?**
  - history tracker: detecta cambios campo por campo (deadline, prize, status) y escribe en `opportunity_history`, genera notificación si en watchlist y cambio deadline
  - Pero owner dijo scoring NO todavía, y history es importante. Podría ser Ticket 005: history tracker + notifications base (sin scoring)
  - O según TICKETS.md original: Ticket 005 scoring, pero con senior advice scoring deshabilitado. Mejor posponer scoring a Ticket 012+ y hacer history en 005

- [ ] **TICKET 006: `core/db.py` mejorado + tests**
  - Wrapper con métodos: `insert_opportunity()`, `update_opportunity()`, `find_by_fingerprint()`, `add_alternate_link()`, etc usando fingerprint engine

- [ ] **TICKET 007: `scrapers/base.py` - Interfaz BaseScraper?** Ya tenemos Provider, pero scraper base puede ser wrapper
  - Realmente Provider es base. Este ticket podría ser formalizar `scrapers/` vs `plugins/` distinción: plugins usa Provider, scrapers son implementaciones? Decisión: mantener plugins/ como plugins, cada plugin implementa Provider

- [ ] **TICKET 008-009: Scraper Posterheroes (primer scraper real)**
  - Implementar `plugins/posterheroes/plugin.py` real: fetch con httpx, extract con BeautifulSoup usando selectors, normalize con dateparser
  - Usar FingerprintEngine para deduplicación: `generate()` + `is_duplicate()` contra DB
  - Usar history tracker para detectar cambios
  - Test con URL real `https://posterheroes.org/competition/`

- [ ] **TICKET 010: Scraper Runway**
  - Segundo scraper, playwright, valida deduplicación cross-source (misma oportunidad en runway oficial + itsnicethat aggregator -> 1 registro)

- [ ] **TICKET 011: Scraper genérico grants/residencias**

- [ ] **TICKET 012: `jobs/monitoring.py` - El Vigilante**
  - Selector `SELECT * FROM sources WHERE status='active' ORDER BY priority DESC, last_scraped_at ASC LIMIT batch_size`
  - Para cada source, `loader.get_plugin(slug)` -> `provider = plugin_class(org_slug)` -> `provider.run(url)` -> fingerprint -> history -> notifications

- [ ] **TICKET 013: `jobs/discovery.py` - El Explorador**
  - Seeds -> extractor links externos que contienen keywords (open call, convocatoria, grant, etc) -> org resolver -> crea organization y source pending

- [ ] **TICKET 014: `jobs/notifier.py` + Scheduler APScheduler**
  - Watchlist scanner diario 09:00, urgent scanner cada hora, digest builder

- [ ] **TICKET 015: `cli/main.py` - Digest + CLI mejorado**
  - `radar digest` ya funciona, pero mejorar con "Hay 3 nuevas, 1 cambió deadline..."
  - `radar list --top 10 --score-min 0.6`

- [ ] **TICKET 016: `core/llm_service.py` - On-Demand**
  - Ollama Qwen 7B para resumir bases bajo demanda, solo cuando usuario pide, no en jobs automáticos

**Nota owner:** Si Ticket 004 es Plugin Loader real, Ticket 005 debería consolidar uno de componentes más importantes antes de scrapers completos, para que base de datos sea confiable. Eso fue Fingerprint en Ticket 003, siguiente podría ser history tracker o mejorar loader con scheduler real. Owner dijo: "No implementaría todavía scoring". Mantener.

**Sugerencia para HERMES:** Preguntar a owner cuál quiere como Ticket 005 antes de implementar, o proponer: Ticket 005 = `core/history.py` + `core/watchlist.py` + `core/notifications.py` base (sin scoring), para que cuando scrapers empiecen a traer datos, sistema ya tenga memoria de cambios y avisos.

---

## 7. Arquitectura v3.0 Resumen (para HERMES)

Ver `architecture_description_v3.md` para diagrama completo, pero resumen:

**Componentes separados:**
- `Scheduler`: Dos relojes independientes (Discovery semanal, Monitoring cada 12h, Notifier diario 09:00)
- `Job Discovery` (El Explorador): Seeds -> Explorer busca nuevas Orgs/Festivales -> Validator si es oficial -> output nuevas orgs y sources pending_validation
- `Job Monitoring` (El Vigilante): Selector sources activas por prioridad -> Scraper Playwright+BeautifulSoup -> Extractor normalizador -> Deduplicador fingerprint -> Change Tracker history -> Scoring (disabled) -> Detector eventos notifications
- `Core`: fingerprint, history, scoring (disabled), notifications, watchlist, provider, plugin_loader, db, logger, config, doctor
- `DB`: organizations (raíz), sources (pertenece a org), opportunities (org+source+fingerprint_hash UNIQUE), opportunity_history, opportunity_scores (3 métricas simplificadas pero disabled), watchlist, notifications, opportunity_tags, raw_extractions + vistas v_opportunities_ranked, v_watchlist_active
- `Interfaces`: CLI Summary headless MVP, API local futura, On-Demand LLM

**Modelo datos v3.0:** Ver `schema.sql` y `architecture_description_v3.md` Sección 3. Tablas: organizations, sources (organization_id FK), opportunities (organization_id, source_id, fingerprint_hash, is_duplicate_of self FK, alternate_links_json), opportunity_history (field_name, old_value, new_value, change_type), opportunity_scores (relevance, prize, urgency, final_score generated), watchlist (opportunity_id UNIQUE, status, reminder_days_json), notifications (opportunity_id, type, title, message, scheduled_for, is_read), opportunity_tags, raw_extractions

**Fingerprint v1:** Ver `core/fingerprint.py` Sección 4 handover

**Plugin Loader v1:** Ver `core/plugin_loader.py` Sección Ticket 004

**Config v3.0:** `config/config.yaml` - project, logging, scan.monitoring, scan.discovery, plugins (enabled, schedule, priority, provider, opportunity_types), notifications, scoring.enabled false, deduplication thresholds, watchlist, countries, languages, categories, opportunity_types genérico, organizations, llm, environments

---

## 8. Reglas de Oro para HERMES (NO ROMPER)

1. **Nunca agregar lista manual de plugins en core.** Siempre filesystem scan + manifest.yaml. Si necesitas nuevo plugin, crear carpeta `plugins/nuevo_slug/` con `manifest.yaml` y `plugin.py`, y agregar entrada en `config/config.yaml` plugins.nuevo_slug.enabled.

2. **Nunca poner reglas específicas de org en core.** Si Runway necesita lógica distinta (ej. parsear fecha con formato raro), va en `plugins/runway/plugin.py` `normalize()` override, no en `core/fingerprint.py` ni `core/db.py`.

3. **Mantener API Fingerprint congelada.** `generate()`, `is_duplicate()`, `compare()` firmas no cambian. Si necesitas embeddings futuros, agregar en `metadata` y métodos internos, no romper firma.

4. **Scoring deshabilitado hasta 300 opps.** No implementar `core/scoring.py` aún. Si owner pregunta, explicar que acumular 300 reales primero, ver cuáles se presentan, recién heurística basada en data real.

5. **Logs, no prints.** Usar `from core.logger import get_logger; logger = get_logger("monitor")` + `logger.info()`, `logger.warning()`, `logger.error()`. Archivos separados por job.

6. **Config gobierna TODO.** Si necesitas nuevo parámetro (threshold, batch_size, etc), poner en `config/config.yaml` y leer via `get_config().get("deduplication.xxx")`, no hardcodear.

7. **Tickets atómicos verificables.** Cada ticket debe tener test en `tests/unit/` o `scripts/test_*.py`, `radar doctor` OK después, no romper tests anteriores, actualizar `TICKETS.md` y crear `scripts/TICKET_XXX_REPORT.md`.

8. **Headless first.** CLI `python -m radar digest` es UI inicial. No hacer frontend hasta que motor funcione 2 meses headless.

9. **Provider interface agnóstico.** `fetch()` trae raw (html, json, rss...), `extract()` lista semi-estructurada, `normalize()` canónica. Futuro RSS, API, MCP sin romper.

10. **Seguridad producto:** `.gitignore` tiene `data/*.db`, `data/raw/*`, `.env`, etc. No subir DB real ni API keys. `data/seed/` sí sube (seeds orgs/sources).

---

## 9. Cómo continuar orquestando tickets (instrucciones para HERMES)

**Cuando owner diga:** "Ejecutar TICKET 005" con descripción

**HERMES debe:**
1. Leer `TICKETS.md` para contexto backlog
2. Leer `HANDOVER_TO_HERMES.md` (este archivo) para filosofía y estado
3. Leer archivos relevantes (ej. si Ticket 005 es history tracker, leer `core/fingerprint.py`, `core/db.py`, `schema.sql` opportunity_history)
4. Implementar SOLO ese ticket, nada más. Código en su módulo con type hints.
5. Crear tests en `tests/unit/test_*.py` o `scripts/test_*.py` verificando criterios aceptación del ticket
6. Correr tests + `python -m radar doctor` + `python -m radar plugins` para asegurar no rompe anteriores
7. Actualizar `TICKETS.md` marcando [x] completado con resumen
8. Crear `scripts/TICKET_XXX_REPORT.md` con qué se hizo, validación, decisiones senior, criterios aceptación
9. Presentar reporte final al usuario con comandos para probar

**Ejemplo de respuesta HERMES:**
```
TICKET 005 COMPLETADO - History Tracker
- Implementado core/history.py con track_changes()
- Tests 5 OK
- Doctor OK
- Reporte en scripts/TICKET_005_REPORT.md
Listo para TICKET 006
```

**Si owner no especifica ticket, proponer:** Basado en backlog, sugerir siguiente lógico (ej. history tracker antes de scrapers para que DB sea confiable) y preguntar si quiere ese.

**Comunicación:** Usar mismo estilo senior, explicar decisiones arquitectura, mantener tickets pequeños verificables.

---

## 10. Contacto y Handoff

**Owner:** Trabaja en `America/Buenos_Aires`, necesita sistema que descubra oportunidades automáticamente, deduplique, siga cambios y priorice según perfil argentino AI video/motion.

**Repo actual:** Todo en `/home/user` workspace. No git remoto configurado aún (según .gitignore no hay .git/config). Si owner quiere abrir a otros en 6 meses, preparar para `pip install -e .` y FastAPI local.

**Estado DB actual (2026-07-26):**
```
Tables: 10, Orgs: 9, Sources: 9, Opportunities: 0, History: 0, Scores: 0, Watchlist: 0, Notifications: 0
Plugins: 9 discovered, 5 enabled, 5 loadable
Doctor: OK (with WARN expected playwright optional)
Tests: fingerprint 17 OK + plugin_loader 7 OK + DB 5 OK
Scoring: DISABLED
Fase: Recolección inicial, objetivo 300 antes de scoring
```

**Próximo hito:** Cuando Ticket 010-012 scrapers estén listos, ejecutar `python -m radar monitor` debería traer primeras 50-100 oportunidades reales, deduplicadas por fingerprint, con history tracker listo.

**Importante para HERMES:** Mantener visión Opportunity Intelligence Engine, no volver a "Radar de Concursos". Motor genérico agnóstico. Si owner menciona nuevo tipo oportunidad (ej. "quiero monitorear grants de Sundance"), solo agregar nuevo plugin `plugins/sundance/` con manifest opportunity_types: ["grant"] y enabled true en config.yaml, sin tocar core.

---

## 11. Checklist para HERMES al iniciar

- [ ] Leer este HANDOVER completo
- [ ] Leer `README.md`, `TICKETS.md`, `architecture_description_v3.md` (resumen)
- [ ] Ejecutar `python -m radar doctor` y `python -m radar plugins` y `python tests/unit/test_fingerprint.py` y `test_plugin_loader.py` para verificar estado
- [ ] Leer `config/config.yaml` para entender plugins enabled y thresholds
- [ ] Revisar `core/plugin_loader.py`, `core/fingerprint.py`, `core/provider.py` para entender boundaries
- [ ] Esperar Ticket 005 del owner o proponer siguiente

**Listo para continuar orquestando tickets mientras owner no está.**

---

*Generado por Agente Principal - TICKET 004 completado - Handover a HERMES AGENT*
*Radar v3.0 - Opportunity Intelligence Engine*
*Headless First - Config over Code - Core Agnostic - Fingerprint not URL - Assistant not Search*
