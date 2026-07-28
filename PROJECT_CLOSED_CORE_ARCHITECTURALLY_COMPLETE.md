# Radar - Núcleo Arquitectónicamente Completo ✅ - Cierre Formal Fase Infraestructura

**Fecha:** 2026-07-27
**Veredicto:** Ticket 009 APROBADO - El núcleo de Radar queda arquitectónicamente completo
**Decisión:** Cerrar Fase Infraestructura, abrir Fase 2 – Providers Reales como prueba de arquitectura

---

## Validación Ticket 009 - Requisitos vs Estado

| Requisito | Estado |
|-----------|--------|
| APScheduler real | ✅ BackgroundScheduler, ThreadPoolExecutor max_workers 5, CronTrigger, MemoryJobStore, listeners EVENT_JOB_EXECUTED/ERROR |
| Jobs independientes | ✅ Discover, Monitor, Notify, Cleanup, HealthCheck cada uno en thread separado |
| Aislamiento entre jobs | ✅ Si un Job falla, los demás continúan - verificado con 3 jobs job1 success, job2 fail, job3 success aunque job2 falló |
| Traceback registrado | ✅ JobResult con error y traceback_str, logging en scheduler.log con traceback completo |
| Reintentos configurables | ✅ retries y retry_delay_seconds desde config.yaml jobs.<id>.retries, testeado flaky job |
| Parsing de cron | ✅ Válidos parseados, inválido fallback sin crashear |

**No hay requisitos faltantes.**

---

## Estado Infraestructura - Ya no es conjunto de componentes sueltos, es una plataforma

```
Plugin Loader          ✅ - Descubrimiento dinámico filesystem, validación manifest, aislamiento fallos, enable/disable YML, prioridades, sin listas manuales, sin imports manuales
Runtime                ✅ - Instanciación dinámica via importlib, lifecycle CREATED->INITIALIZED->RUNNING->STOPPED->FAILED, get_or_create_instance thread-safe, reload sin leaks 5 reloads, concurrencia 10 threads 0 crashes, close exception aislada
Monitoring             ✅ - Orquestador sin lógica negocio mezclada, flujo Provider->Normalize->Fingerprint->Database->Logs, transacción atómica BEGIN->update+history+alternate->COMMIT rollback si falla (crítica), idempotencia alternate solo si no existe + history check último mismo valores skip, métricas por source y globales, error isolation, sin scoring
History                ✅ - Subsistema propio separado Opportunity->OpportunityHistory, first_seen inmutable, last_seen siempre actualizado, nunca borrar solo status=closed, idempotencia, transacción atómica, 7 tests
Notification           ✅ - Motor con idempotencia exacta por evento (new_opportunity 1 ever, deadline_changed old->new exacto, deadline_reminder days_left por día, status_closed 1 ever, watchlist idempotencia por día), salida consola y logs monitor.log/notifications.log, no email, integración monitoring, 7 tests
Fingerprint            ✅ - API congelada v1, 12 funcs normalización independientes (invisible, whitespace, lower, accents, tracking params, URL, title basic y agresivo, org, deadline, type, country), solo info estable (no premios, descripción, IA), 2 niveles exacta hash SHA256[:16] y aproximada RapidFuzz threshold 0.85 configurable, 17 tests
Deduplicación          ✅ - Exact hash + approximate lógica estricta URL igual + title>=0.85 para deadline extendido o URL diferente + title>=0.95 + deadline mismo para cross-source, evita falsos positivos
Database               ✅ - SQLite WAL, FK ON, 9 tablas, vistas v_opportunities_ranked y v_watchlist_active, métodos find/insert/update/history/alternate/notifications/watchlist con idempotencia y UNIQUE handling
Scheduler              ✅ - BackgroundScheduler real, ThreadPoolExecutor, CronTrigger, MemoryJobStore, listeners, JobResult, with_retry_and_isolation decorador, 5 jobs Discover/Monitor/Notify/Cleanup/HealthCheck independientes con cron retries delay timeout desde YAML, add_jobs, start/shutdown, run_job_now para testing
Logs                   ✅ - Separados por job monitor.log, discover.log, scheduler.log, doctor.log, db.log, core.log, provider.log, notifications.log, RotatingFileHandler 5MBx3, formato senior timestamp|level|job|message
Métricas               ✅ - SourceMetrics y MonitoringMetrics con fetched, normalized, new, duplicate_exact, duplicate_approximate, updated, history_entries, alternate_links_added, errors, duration, to_dict
Idempotencia           ✅ - Transacción atómica por oportunidad, alternate_links solo si no existe, history verifica último mismo campo/valores skip, detect_changes asegura 2da pasada sin cambios no genera nada, monitor_all crash rerun no duplica
```

**Tests:** 53 OK
- test_fingerprint: 17 OK
- test_plugin_loader: 7 OK
- test_plugin_loader_hardening: 3 OK (reload sin leaks, concurrencia, close exception)
- test_plugin_loader_runtime: 9 OK (discovery, manifest, dynamic load 0 manual imports, instanciar, lifecycle, enable/disable, prioridades, errores sin detener, validaciones)
- test_monitoring_engine: 6 OK (ejecutar providers, deduplicación exact+approximate, registrar cambios, errores aislados, logs y métricas, flujo completo sin scoring)
- test_opportunity_history: 7 OK (primera/última aparición, deadline, URL, estado, descripción, nunca perder historial, historial completo 7 eventos)
- test_notification_engine: 7 OK (nuevas, deadline cambiado, deadline próximo, cerrada, watchlist, consola y logs, exactamente una por evento)
- test_scheduler_runtime: 6 OK (creación y jobs, independientes, aislamiento fallos, traceback, reintento configurable, cron parsing)

**Doctor:** OK (WARN playwright optional expected) - 9 discovered dynamic, 9 valid, 5 enabled, 5 loadable, 5 instantiated, fingerprint API frozen, scheduler jobs, etc

**Scoring:** DISABLED hasta 300 opps reales (senior advice respetado)

---

## Lo que NO hacer (decisión senior)

No agregar ahora:

- otro Engine
- otro Manager
- otro Runtime
- otro Loader
- otra capa de abstracción

Cada uno agregaría complejidad sin aportar valor hasta que existan datos reales.

**Fase infraestructura terminada. Riesgo principal ya no está en core, está en providers reales.**

---

## Mejoras futuras documentadas (no implementar ahora)

### 1. Persistencia del scheduler (observación Ticket 009)

**Hoy:** `MemoryJobStore` - jobs en memoria, se pierden al reiniciar proceso. Está bien para MVP.

**En producción probablemente:** `SQLAlchemyJobStore` o similar para sobrevivir reinicios, guardar next_run_time, estado, etc.

**No implementar todavía:** MVP con MemoryJobStore es suficiente, no complejidad extra hasta que haya providers reales funcionando y necesidad de sobrevivir reinicios sin perder schedule.

**Documentado en:** config.yaml scheduler.job_defaults y BACKLOG_TECNICO.md

### 2. Observabilidad (observación Ticket 009)

**Hoy:** Logs por job y `python -m radar schedule` muestra schedule, `python -m radar doctor` muestra validación.

**Más adelante útil:**

```
radar jobs

Discover      OK last 2026-07-27 03:00 next 2026-08-03 03:00
Monitor       OK last 2026-07-27 12:00 next 2026-07-28 00:00 duration 20s new 5
Notify        FAIL x2 last 2026-07-27 09:00 next 2026-07-28 09:00 error: SMTP timeout
Cleanup       OK last 2026-07-27 02:00
HealthCheck   OK last 2026-07-27 05:00
```

Comando `radar jobs` o `radar status` con tabla Rich que muestre cada job, último run, próximo run, estado OK/FAIL, duración, retries, etc. Basado en `get_scheduler_runtime().get_jobs()` + `get_job_results()`.

**No implementar todavía:** Puede venir mucho después, cuando haya providers reales y necesidad de monitorear scheduler en producción.

**Documentado en:** BACKLOG_TECNICO.md y PROJECT_STATUS_INFRA_READY.md

### 3. Mejoras futuras ya documentadas previamente

- **Canales Notificación:** Evento -> Notification -> Canal, hoy solo LOG, mañana EMAIL/DISCORD/SLACK/WEBHOOK sin tocar resto (Ticket 008 nota)
- **Escalabilidad duplicate approximate:** O(n) con 300 OK, con 30k-500k cuello de botella, optimizar con FTS5, deadline bucket, embeddings cuando volumen >1k (Ticket 006 observación 3 documentada en BACKLOG_TECNICO.md)
- **Versionado y Event Sourcing parcial:** first_seen/last_seen + history ya tiene forma Event Log (created, deadline_extended, status_changed), futuro snapshots para reconstruir estado en cualquier fecha, no ahora (Ticket 007 nota futuro)

Todas documentadas como mejora futura, no para implementar ahora.

---

## Cierre Formal Fase Infraestructura

**Tickets infraestructura aprobados:**

- ✅ Ticket 005: Plugin Loader Runtime - APROBADO con hardening reload sin leaks, concurrencia, close exception
- ✅ Ticket 006: Monitoring Engine - APROBADO CON OBSERVACIONES MENORES - transacción atómica, idempotencia, escalabilidad documentada, regla URL igual + deadline distinta -> UPDATE evita falsos positivos
- ✅ Ticket 007: Opportunity History - APROBADO - historial subsistema propio, first_seen inmutable, last_seen siempre, nunca borrar solo status=closed, idempotencia, transacción atómica
- ✅ Ticket 008: Notification Engine - APROBADO con nota canales futuro Evento->Notification->Canal hoy LOG mañana EMAIL/DISCORD/SLACK/WEBHOOK
- ✅ Ticket 009: Scheduler Runtime - APROBADO - APScheduler real, jobs independientes, aislamiento completo, traceback, reintento configurable, cron parsing

**Con estos 5 tickets, fase infraestructura terminada arquitectónicamente.**

---

## Apertura Nueva Fase: Fase 2 – Providers Reales

**Objetivo ya no es construir infraestructura, sino demostrar que infraestructura soporta múltiples organizaciones reales sin modificaciones en core.**

**Definición Ticket 010 como prueba de arquitectura:**

Si Posterheroes funciona usando exactamente:

```
Plugin
  ↓
Provider
  ↓
Normalize
  ↓
Fingerprint
  ↓
History
  ↓
Database
  ↓
Notification
```

**Sin agregar una sola excepción dentro de `core/`**, entonces arquitectura queda validada de verdad.

**Próximos tickets Fase 2 (recomendados):**

- **Ticket 010: Scraper Posterheroes Real (PRÓXIMO - Prueba de Arquitectura)**
  - `plugins/posterheroes/plugin.py` real: fetch httpx, extract BeautifulSoup con selectors reales, normalize dateparser
  - Flujo validado Provider->Normalize->Fingerprint->Database->Logs ya probado en Ticket 006, History ya probado en Ticket 007, Notification ya probado en Ticket 008, Scheduler Runtime ya probado en Ticket 009
  - Validar con https://posterheroes.org/competition/ o HTML guardado data/raw/
  - Validación: Doctor OK, 53 tests OK no regresión, `python -m radar monitor --batch-size 1` source posterheroes fetched >0 new >=1 insertado DB, history evento created, notif new_opportunity 1, logs monitor.log, métricas, segunda ejecución dup_exact >=1 no duplicados, simular cambio deadline HTML mock 2026-09-15->2026-09-30 debe detectar updated 1 history deadline_extended, digest muestra nueva, logs separados, no manual imports
  - No scoring, no más managers/engines/capas/abstracciones

- **Ticket 011: Scraper Runway Real (playwright)** - valida deduplicación cross-source misma oportunidad en runway oficial + itsnicethat aggregator -> 1 registro alternate_links + notificación

- **Ticket 012: Scraper Adobe Real + AI Film Festival + It's Nice That**

- **Ticket 013: Integration Test con datos reales** - Ejecutar monitor con 5 plugins reales, verificar 50-100 oportunidades reales deduplicadas, con history, notificaciones, métricas, logs

**Cambio de enfoque:** De construir infraestructura a ejercitarla con datos reales. Mayor valor vendrá de providers reales, más que seguir ampliando core.

---

## Comandos para Fase 2

```bash
# Validar infra lista (53 tests OK)
python -m radar doctor # RESULT OK
python tests/unit/test_fingerprint.py # 17 OK
python tests/unit/test_plugin_loader.py # 7 OK
python tests/unit/test_plugin_loader_hardening.py # 3 OK
python tests/unit/test_plugin_loader_runtime.py # 9 OK
python tests/unit/test_monitoring_engine.py # 6 OK
python tests/unit/test_opportunity_history.py # 7 OK
python tests/unit/test_notification_engine.py # 7 OK
python tests/unit/test_scheduler_runtime.py # 6 OK

# Ver estado infra
python -m radar plugins --enabled # 5 enabled
python -m radar schedule # 5 jobs con cron retries
python -m radar stats # DB counts
python -m radar digest # Headless MVP

# Fase 2 - Cuando Posterheroes real esté listo
python -m radar monitor --batch-size 1 --verbose # Debe fetched >0 new >=1
python -m radar digest # Debe mostrar nueva oportunidad
ls logs/monitor.log # Debe contener [NEW] y [MONITOR]
```

---

*Infraestructura principal cerrada formalmente - 53 tests OK - Doctor OK - Plataforma lista*
*Próxima fase: Providers reales como prueba de arquitectura sin excepciones en core*
*Cierre: Tickets 005,006,007,008,009 aprobados - Fase infra terminada*
