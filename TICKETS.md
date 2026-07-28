# Radar - Backlog de Tickets

> Metodología: Tickets atómicos. Un ticket = un módulo que se puede testear aislado. Si algo se rompe, no rompe el resto.

### Naming: Proyecto se llama "Radar" (no "Radar de Concursos")
El mismo motor monitorea cualquier oportunidad: concursos, grants, residencias, becas, licitaciones, aceleradoras, fondos, hackathons, beta programs.

---

## FASE 1: Fundación (Core Engine) - COMPLETADA ✅

- [x] **TICKET 001: Bootstrap del proyecto [COMPLETADO 2026-07-26]**
  - Estructura carpetas, venv, requirements.txt, .gitignore, README
  - Renaming oficial: "Radar - Opportunity Intelligence Engine"

- [x] **TICKET 002: Núcleo reproducible del sistema [COMPLETADO 2026-07-26] - Redefinido por review senior**
  - plugins/ folder (9 plugins), core/provider.py, core/logger.py, core/config.py, core/db.py, core/doctor.py v1, cli/main.py, config/config.yaml, seeds YAML, scripts/init_db.py, scoring DISABLED

- [x] **TICKET 003: Fingerprint Engine v1 + Deduplicación Base [COMPLETADO 2026-07-26]**
  - Registro dinámico filesystem, doctor robusto v2, fingerprint estructura congelada v1, core agnóstico
  - core/fingerprint.py 800 líneas, API congelada generate/is_duplicate/compare, 12 funcs normalización, solo info estable, 2 niveles exacta/aproximada RapidFuzz
  - Tests 17 unit + 5 DB OK

- [x] **TICKET 004: Plugin Loader Real [COMPLETADO 2026-07-26]**
  - core/plugin_loader.py 400 líneas, boundary core<->plugins, registro dinámico filesystem sin lista manual, validación manifest, aislamiento fallos, respeta enable YML, integración scheduler, core agnóstico
  - jobs/scheduler.py, doctor v2.1 usa loader real, cli plugins/schedule
  - Tests 7 OK

- [x] **TICKET 005: Plugin Loader Runtime [APROBADO 2026-07-26] - Con nota hardening completada**
  - core/plugin_loader.py Runtime v2 (830 líneas): verdadero cargador dinámico, scan() sin lista manual, validar manifest, cargar Provider vía importlib sin from plugins.runway (AST 0 manual imports), instanciar Provider create_provider_instance, lifecycle ProviderInstance INITIALIZED->RUNNING->STOPPED->FAILED, get_or_create_instance, shutdown_all, instantiate_all_enabled, validate_runtime()
  - Soporta enable/disable: 5 enabled (runway, posterheroes, adobe, itsnicethat, ai-film-festival) 4 disabled ignorados, prioridades orden desc runway=10 adobe=9
  - Aislamiento: 1 bueno + 2 rotos (syntax error + init failure) good sigue OK, sistema no roto
  - Tests: 9 tests OK + Hardening 3 tests OK reload sin leaks 5 reloads, concurrencia 10 threads 0 crashes, excepción Provider.close() aislada
  - Validación: doctor OK 9/9/5/5, registry OK 9, loader OK 9/5/5, 5 instantiated OK, 4 ignorados, 0 manual imports

- [x] **TICKET 006: Monitoring Engine [APROBADO CON OBSERVACIONES MENORES 2026-07-26]**
  - core/history.py (150 líneas): HistoryTracker detect_changes, change_type deadline_extended/shortened/prize_updated/status_changed/info_updated
  - core/db.py extendido: find_organization_by_slug, find_opportunity_by_fingerprint, insert_opportunity UNIQUE handling, update_opportunity, add_alternate_link limite 20, insert_history
  - core/monitoring_engine.py (600 líneas, hardening transacción atómica): SourceMetrics, MonitoringMetrics, monitor_source Provider->Normalize->Fingerprint->Database->Logs, process_opportunity fingerprint exact + approximate lógica estricta (URL igual + title>=0.85 para deadline extendido, URL diferente + title>=0.95 + deadline mismo para cross-source), _handle_duplicate con TRANSACCIÓN ATÓMICA BEGIN->update+history+alternate->COMMIT rollback si falla (crítica), idempotencia alternate solo si no existe + history check último mismo valores skip, escalabilidad duplicate approximate documentada como optimización futura
  - jobs/monitoring.py: run_monitoring() real, cli/monitoring tabla Rich
  - Tests: 6 tests OK ejecutar providers, deduplicación exact/approximate, registrar cambios deadline extendido update history 2, errores aislados good+bad, logs y métricas, flujo completo sin scoring
  - Resultado: Motor orquestador sin lógica negocio mezclada, history separado, error isolation, métricas, sin scoring

- [x] **TICKET 007: Opportunity History [APROBADO 2026-07-27]**
  - core/opportunity_history.py (250 líneas): sistema historial nunca pierde, record_first_appearance idempotente first_seen_at nunca cambia, record_last_appearance last_seen_at siempre, record_change idempotente con conn para transacción atómica, record_deadline_change/url/status/description, get_history ORDER BY detected_at ASC id ASC, get_first/last_appearance, never_lose_history COUNT>=1, nunca DELETE solo UPDATE status
  - Tests: 7 tests OK primera/última aparición, deadline extended/shortened, URL official y alternate, estado open->closed, descripción, nunca perder historial aunque closed, historial completo simulado 7 eventos ordenados
  - Validación: primera inmutable, última siempre actualizada, deadline, URL, estado, descripción, nunca perder, cada modificación evento, ordenado

## INFRAESTRUCTURA PRINCIPAL COMPLETA ✅
```
Plugin Loader         ✅
Runtime               ✅
Monitoring            ✅
History               ✅
Fingerprint           ✅
Deduplicación         ✅
Métricas              ✅
Logs                  ✅
```
- Tests: 17+7+3+9+6+7+7+6+1 = 53 tests OK + 1 provider real validado (Posterheroes)
- Doctor: OK (WARN playwright optional expected)
- Decisión senior: detener core, pasar a providers reales

## FASE 2: Inteligencia y Providers Reales - Mixta

- [x] **TICKET 008: Notification Engine [APROBADO 2026-07-27] - Con nota canales futuro**
  - core/db.py extendido: insert_notification, find_notification, find_notification_exact (metadata old/new, days_left), get_pending_notifications orden prioridad urgent/high/normal, get_notifications_by_type, get_notifications_count, add_to_watchlist, get_watchlist, get_watchlist_with_days_left (julianday deadline)
  - core/notification_engine.py (400 líneas): NotificationEngine con idempotencia exacta por evento, _check_idempotence (new_opportunity solo una ever, deadline_changed verifica old/new exactos, deadline_reminder verifica days_left y created_at hoy, status_closed solo una ever, watchlist idempotencia por día), _log_notification (nivel según prioridad urgent->error high->warning normal->info, logs/monitor.log y logs/notifications.log), create_notification (valida type/title/message, idempotencia check, insert, log, retorna dict o None si ya existe), notify_new_opportunity (title Nueva oportunidad, message org+deadline+source, priority normal, metadata org/deadline/source/fingerprint), notify_deadline_changed (old/new deadline, change_type extended/shortened, title extendido/acortado, message buenas noticias/atención, priority high/urgent, metadata old/new), notify_deadline_upcoming (days_left <=1 último día urgent, <=3 high, <=7 high, else normal, title Deadline en X días, metadata days_left), notify_status_closed (open->closed, title Cerrada, message ya no se puede aplicar, metadata old/new status), notify_watchlist_reminder (watchlist_id, days_left, title [Watchlist] X días, message watchlist status, priority urgent <=3 high <=7, metadata days_left/watchlist_status/org/is_watchlist), check_watchlist_reminders (thresholds desde config notifications.deadline_days [30,15,7,3,1], query watchlist_with_days_left, si days_left in thresholds llama notify_watchlist_reminder con idempotencia), check_deadline_upcoming (todas opps abiertas, thresholds [7,3,1] para no spamear), get_pending, get_by_type, singleton get_notification_engine
  - core/monitoring_engine.py integrado: import lazy notification_engine, __init__ con notification_engine opcional, process_opportunity después de insert new llama notify_new_opportunity, _handle_duplicate después de detectar changes deadline llama notify_deadline_changed y status closed llama notify_status_closed con try/except para no romper monitoring
  - Salida consola y logs, no email: cada notificación logueada formato [TYPE][priority] Opp id: title - message, nivel error/warning/info según prioridad, logs/monitor.log y logs/notifications.log, no email todavía (solo db + log)
  - Tests: tests/unit/test_notification_engine.py 7 tests OK: nuevas oportunidades 1 notificación idempotencia DB COUNT 1, deadline cambiado 15->30 extended high 1 + mismo 15->30 duplicate None + 30->20 shortened urgent 1 DB COUNT 2, deadline próximo 7 días 1 + mismo 7 días hoy None + 3 días 1 DB COUNT 2, oportunidad cerrada 1 + duplicate None DB COUNT 1, watchlist 7 días 1 con watchlist_id + mismo 7 días None + 3 días 1 DB COUNT 2 + check_watchlist_reminders no duplica mismo día, consola y logs 4 tipos creadas sin excepción no email, exactamente una por evento 9 intentos 6 únicos + 3 duplicados -> 6 creadas DB COUNT 6 verificado
  - Validación: simular múltiples escenarios, cada evento exactamente una notificación, idempotencia por evento, consola y logs, no email
  - Resultado: Motor notificaciones con idempotencia exacta, salida consola y logs, integrado con monitoring, base para watchlist

- [x] **TICKET 009: Scheduler Runtime [APROBADO 2026-07-27] - Núcleo arquitectónicamente completo**
  - config/config.yaml añadida sección scheduler con enabled, timezone, max_workers, job_defaults, jobs discover/monitor/notify/cleanup/healthcheck cada con enabled, cron, retries, retry_delay_seconds, timeout_seconds
  - jobs/scheduler_runtime.py (400 líneas): BackgroundScheduler real, ThreadPoolExecutor max_workers 5 para aislamiento, CronTrigger, MemoryJobStore, listeners EVENT_JOB_EXECUTED/ERROR, JobResult dataclass con success/duration/attempt/error/traceback, with_retry_and_isolation decorador con retry configurable desde YAML y aislamiento, 5 jobs definitions discover/monitor/notify/cleanup/healthcheck cada independiente, add_jobs desde config, start/shutdown, get_jobs, run_job_now para testing, get_job_results, singleton
  - Tests: 6 tests OK creación y jobs 5 agregados, independientes cada retorna JobResult, aislamiento fallos job que falla no detiene otros traceback registrado, traceback registrado error y traceback_str, reintento configurable retries=2 permite 3 intentos total, cron parsing válidos e inválido fallback sin crashear
  - Validación: APScheduler real BackgroundScheduler ThreadPoolExecutor CronTrigger, cada Job independiente, si falla los demás continúan aislamiento completo verificado 3 jobs, registrar traceback JobResult y logs scheduler.log, reintento configurable desde config.yaml, cron parsing
  - Canales futuro: Evento -> Notification -> Canal, hoy solo LOG, mañana EMAIL/DISCORD/SLACK/WEBHOOK sin tocar resto, documentado como mejora futura no para este ticket
  - Resultado: Scheduler Runtime real listo para probar providers reales ya dentro del runtime definitivo, próximo Ticket 010 será primer provider real Posterheroes usando pipeline ya construido

- [x] **TICKET 010: Primer Provider Real - Posterheroes [APROBADO 2026-07-27] - Arquitectura validada con caso real + 2 observaciones menores corregidas**
  - plugins/posterheroes/plugin.py real (300 líneas, sin excepciones): fetch httpx con candidate_urls() genérico + fetch_first_success() (fallback chain 3 URLs: posterheroes.org/competition/ 404 -> www.posterheroes.org/competition/ 404 -> www.posterheroes.org/ 200 47824 bytes), extract BeautifulSoup lxml deadline 31st July 2026 regex, awards €2,500/€1,500 economic_value float, description boundary, brief links, normalize a NormalizedOpportunity
  - Pipeline sin excepciones: Plugin (manifest.yaml) -> Provider (fetch -> extract -> normalize via provider.run) -> Normalize -> Fingerprint (hash 6f180fb467666424) -> History (first_seen) -> Database (insert only new transacción atómica idempotencia) -> Notification (new_opportunity) -> Logs (monitor.log [NEW] [MONITOR]) -> Métricas (SourceMetrics)
  - Validación: extraer oportunidades reales 1 de www.posterheroes.org/ 47824 bytes title Posterheroes 15 - Still Human deadline 31st July 2026 awards €2,500/€1,500 link https://www.posterheroes.org/, deduplicación 2da vez new 0 DB count 1 (no duplicados), persistencia DB id 5, logs monitor.log [NEW], notificaciones new_opportunity 1 idempotencia, sin excepciones core 0 manual imports, funciona igual que cualquier plugin futuro
  - Fix 1 - economic_value normalization bug corregido: antes updated=1 por 2500.0 -> 2500 falso, ahora siempre float float(max(values)) y HistoryTracker detect_changes compara float con tolerancia 0.01, 2500.0 vs 2500 no es cambio, 2500 vs 2600 sí, evita ensuciar History/Notifications/Metrics
  - Fix 2 - fallback URLs genérico: antes hardcodeado competition/ -> www -> root en fetch(), ahora Provider base con candidate_urls() -> List[str] y fetch_first_success() genérico que itera lista hasta primer éxito, cualquier plugin futuro puede definir [competitions, open-call, calls, root, archive] sin tocar base Provider, Posterheroes override candidate_urls() con 5 candidatos
  - Fix 3 - test fixture HTML: tests/plugins/posterheroes/posterheroes_2026.html 47KB guardado + test_posterheroes_extract.py 7 tests con asserts title, deadline, awards, description, normalize, candidate_urls, economic_value float, protege contra cambio HTML, cambio parser, refactor, hace scraper robusto
  - Hardening DB: busy_timeout 5000 y timeout 10.0 para evitar database is locked
  - Resultado: Primer provider real validado como prueba de arquitectura, base para Runway, Adobe, etc., arquitectura soporta caso real sin excepciones en core

- [ ] **TICKET 011: Scraper Runway Real (playwright) - Validación cross-source**
  - plugins/runway/plugin.py real playwright, valida deduplicación cross-source misma oportunidad en runway oficial + itsnicethat aggregator -> 1 registro alternate_links + notificación

- [ ] **TICKET 012: Scraper Adobe Real + AI Film Festival + It's Nice That**

- [ ] **TICKET 013: Integration Test con datos reales**
  - Ejecutar monitor con 5 plugins reales, verificar 50-100 oportunidades reales deduplicadas, con history, notificaciones, métricas, logs

## FASE 3: Inteligencia Adicional

- [ ] **TICKET 013: `core/watchlist.py` mejorado + digest**
  - Watchlist ya tiene add_to_watchlist y get_watchlist_with_days_left en db.py, mejorar con notas, prioridad, reminder config, digest diario

- [ ] **TICKET 014: `jobs/discovery.py` - El Explorador**
  - Seeds -> extractor links externos -> org resolver -> nuevas orgs y sources pending

- [ ] **TICKET 015: `jobs/notifier.py` + Scheduler APScheduler**
  - Watchlist scanner diario, urgent scanner, digest builder

- [ ] **TICKET 016: CLI Digest mejorado + llm_service On-Demand**
  - Hay 3 nuevas, 1 cambió deadline..., Ollama Qwen 7B para resumir bases bajo demanda

## FASE 4: Producto (Futuro - después de 6 meses validado personal)

- [ ] API FastAPI local
- [ ] Chrome Extension
- [ ] Multi-user / SaaS mode

---

### Definición de Done por Ticket
1. Código en su módulo, con type hints
2. Tests en tests/unit/ o scripts/test_*.py
3. No rompe tickets anteriores (doctor OK + tests anteriores OK)
4. Actualiza TICKETS.md marcando [x]
5. Genera scripts/TICKET_XXX_REPORT.md con mismo nivel detalle
6. Ejecutar tests + radar doctor + corregir regresión antes de continuar
7. Si debe modificarse arquitectura previa, detenerse y documentarlo primero

### Reglas obligatorias para HERMES (orquestador)
- No comenzar siguiente ticket hasta completar actual
- Al finalizar cada ticket generar TICKET_XXX_REPORT.md con mismo nivel detalle
- Ejecutar tests + radar doctor, corregir regresión antes de continuar
- Si debe modificarse arquitectura previa, detenerse y documentarlo primero
- Detenerse aquí para validar ticket antes de comenzar siguiente

### Backlog Técnico (hardening no bloqueante)
Ver BACKLOG_TECNICO.md:
- Transacción atómica por oportunidad ✅ Implementado Ticket 006 hardening
- Idempotencia monitor_all crash rerun ✅ Implementado
- Escalabilidad duplicate approximate O(n) -> optimizar con FTS5, deadline bucket, embeddings cuando >1k por org 📝 Documentado, no implementar hasta volumen lo justifique
- Reload sin leaks, concurrencia, close exception ✅ Implementado Ticket 005 hardening

### Estado Actual - Infraestructura Lista
- Doctor: OK (WARN playwright optional)
- Plugins: 9 discovered dynamic, 5 enabled, 5 loadable, 5 instantiated OK
- DB: 9 orgs, 9 sources, 0 opps prod (fase recolección), tests usan DB temp
- Fingerprint: v1 API congelada, 17 tests OK
- Plugin Loader Runtime: v2, 7 tests loader + 9 runtime + 3 hardening = 19 tests OK, 0 manual imports
- Monitoring Engine: 6 tests OK, transacción atómica, idempotencia, métricas, logs separados, flujo completo sin scoring
- Opportunity History: 7 tests OK, primera inmutable, última siempre, nunca perder historial, eventos completos
- Total: 53 tests OK (17 fingerprint + 7 loader + 3 hardening + 9 runtime + 6 monitoring + 7 history + 7 notification + 6 scheduler) + 1 provider real (Posterheroes) extraído real 1 opp deduplicación OK
- Scoring: DISABLED hasta 300 opps
- Fase: Infraestructura principal completa, detener core, pasar a providers reales (Posterheroes, Runway, Adobe, etc.)
- Notas futuro (no implementar ahora): Versionado (snapshots), Event sourcing parcial (created, deadline_extended, status_changed ya tienen forma Event Log)
