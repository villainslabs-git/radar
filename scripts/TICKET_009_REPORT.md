# TICKET 009 - REPORT: Scheduler Runtime

**Estado:** COMPLETADO - Esperando validación HERMES
**Fecha:** 2026-07-27
**Objetivo:** Implementar APScheduler real, cada Job independiente (Discover, Monitor, Notify, Cleanup, HealthCheck), si un Job falla los demás continúan, registrar traceback, reintento configurable

## Resumen Ejecutivo

Se implementó `jobs/scheduler_runtime.py` (400 líneas) con APScheduler BackgroundScheduler real, ThreadPoolExecutor para aislamiento, CronTrigger parsing, retry decorator configurable desde config.yaml, listeners para logging, 5 jobs independientes, validado con simulación de fallos y aislamiento completo.

## Implementación

### 1. `config/config.yaml` - Scheduler sección añadida

```yaml
scheduler:
  enabled: true
  timezone: "America/Argentina/Buenos_Aires"
  max_workers: 5
  job_defaults:
    coalesce: true
    max_instances: 1
    misfire_grace_time: 3600
  jobs:
    discover: {enabled: true, cron: "0 3 * * 0", retries: 2, retry_delay_seconds: 60, timeout_seconds: 600}
    monitor: {enabled: true, cron: "0 */12 * * *", retries: 2, retry_delay_seconds: 30, timeout_seconds: 900, batch_size: 25}
    notify: {enabled: true, cron: "0 9 * * *", retries: 1, retry_delay_seconds: 30, timeout_seconds: 300}
    cleanup: {enabled: true, cron: "0 2 * * *", retries: 1, retry_delay_seconds: 60, timeout_seconds: 300}
    healthcheck: {enabled: true, cron: "0 * * * *", retries: 0, timeout_seconds: 120}
```

- `max_workers`: ThreadPoolExecutor para aislamiento
- `job_defaults`: coalesce, max_instances, misfire_grace_time
- Cada job: enabled, cron, retries, retry_delay_seconds, timeout_seconds, batch_size
- Retries configurables desde YAML, sin tocar código

### 2. `jobs/scheduler_runtime.py` - Runtime real (400 líneas)

**Librerías:**
- `BackgroundScheduler` (no bloqueante, corre en background thread)
- `ThreadPoolExecutor(max_workers=5)` para aislamiento: cada job en su propio thread, si uno falla no bloquea otros
- `MemoryJobStore` (memoria, simple para v1)
- `CronTrigger` para cron parsing
- `EVENT_JOB_EXECUTED` y `EVENT_JOB_ERROR` listeners para logging

**Clases:**

```python
@dataclass JobResult:
  job_id, success, duration, attempt, error, traceback_str, timestamp

def with_retry_and_isolation(retries, retry_delay_seconds, timeout_seconds, job_id):
  Decorador que envuelve job:
  - Intenta hasta retries+1 veces (1 inicial + retries)
  - Si falla, loguea traceback completo en scheduler.log
  - Espera retry_delay_seconds entre intentos
  - Si falla todos, retorna JobResult success=False con error y traceback
  - Nunca lanza excepción hacia afuera (aislamiento), retorna JobResult
```

**Clase SchedulerRuntime:**

- `__init__(config, db)`: lee scheduler config, inicializa BackgroundScheduler con executors, jobstores, job_defaults, timezone, listeners, jobs_config, job_results list, _running flag

- `_job_executed_listener(event)`: log info job executed successfully
- `_job_error_listener(event)`: log error job crashed con exception y traceback, no relanza (aislamiento)

- `_parse_cron(cron_str) -> CronTrigger`: parsea "0 3 * * 0" o "0 */12 * * *" a CronTrigger, maneja */12, si inválido usa fallback daily 09:00 y log warning

- `_wrap_job_with_retry(job_func, job_id, retries, retry_delay, timeout)`: envuelve con decorador with_retry_and_isolation

- **Jobs definitions (5 jobs independientes):**

  - `discover_job()`: Semanal, busca nuevas orgs/sources, por ahora solo scan loader y log discovered plugins, placeholder para futuro jobs/discovery.py, sleep 0.5, log, raise si falla

  - `monitor_job(batch_size)`: Cada 12h, ejecuta providers -> fingerprint -> DB via jobs/monitoring.py run_monitoring, métricas, log

  - `notify_job()`: Diario 09:00, watchlist reminders, deadline upcoming, pending notifications, usa NotificationEngine, log

  - `cleanup_job()`: Diario 02:00, limpia data/raw viejos >30 días (solo cuenta, no borra en test), archiva notificaciones leídas viejas >30 días UPDATE is_archived=1, log

  - `healthcheck_job()`: Cada hora, doctor checks via db.validate_integrity y plugin status, logs dir writable check, log OK o warning con issues

- `add_jobs()`: Lee jobs_config desde config.yaml, para cada job_id en [discover, monitor, notify, cleanup, healthcheck] si enabled, parsea cron, envuelve con retry, agrega a scheduler via `scheduler.add_job(wrapped_func, trigger, id, name, replace_existing=True)`, log added job con cron retries delay timeout

- `start()`: add_jobs(), scheduler.start(), _running True, log started con num jobs y next_run_time

- `shutdown(wait=True)`: scheduler.shutdown, _running False, log

- `get_jobs()`: retorna lista jobs programados si running

- `run_job_now(job_id) -> JobResult`: ejecuta un job inmediatamente (útil para testing y validación), obtiene función original, config retry, envuelve y ejecuta, guarda en job_results, retorna JobResult

- `get_job_results() -> List[JobResult]`

**Singleton:** `get_scheduler_runtime(config, db)` singleton

**Aislamiento garantizado:**

- Cada job corre en ThreadPoolExecutor thread separado (max_workers 5)
- Si un job falla, `_job_error_listener` loguea traceback pero no detiene scheduler ni otros jobs (APScheduler por defecto continúa)
- `with_retry_and_isolation` captura excepción, loguea traceback, no lanza hacia afuera, retorna JobResult con success=False
- Test `test_aislamiento_fallos` verifica: job1 success, job2 failing, job3 success -> job3 success aunque job2 falló, aislamiento completo

**Traceback registrado:**

- `JobResult` contiene error y traceback_str con `traceback.format_exc()`
- Logs en `logs/scheduler.log` con formato `[SCHEDULER] Job {job_id} attempt {attempt} FAILED ... {traceback}`
- Listener `_job_error_listener` también loguea `Job {job_id} crashed: {exception}\nTraceback: {traceback}`

**Reintento configurable:**

- Desde config.yaml `jobs.<id>.retries` y `retry_delay_seconds`
- Decorador `with_retry_and_isolation` intenta hasta retries+1 veces, espera delay entre intentos
- Testeado con flaky job que falla 2 veces y luego success: con retries=2 debe success en 3er intento, con retries=1 debe fail

### 3. Tests: `tests/unit/test_scheduler_runtime.py` - 6 tests, todos OK

1. **scheduler_creacion_y_jobs:** Scheduler se crea, add_jobs agrega 5 jobs habilitados desde config (discover, monitor, notify, cleanup, healthcheck), job_ids verificados

2. **jobs_independientes:** Cada job (discover, monitor, notify, cleanup, healthcheck) se ejecuta independientemente via run_job_now, retorna JobResult, no lanza excepción hacia afuera, 5 jobs ejecutados cada uno retorna JobResult (en test real monitor_job ejecuta 9 sources con 0 oportunidades porque skeleton, pero no falla)

3. **aislamiento_fallos:** Simula 3 jobs: job1 success, job2 failing (raise RuntimeError), job3 success. Verificación:
   - failing job success=False, error contiene "Simulated job failure", traceback_str contiene Traceback y ValueError
   - successful job después de failing success=True aunque anterior falló
   - Lista de 3 jobs: job1 success True, job2 fail False, job3 success True aunque job2 falló -> aislamiento completo verificado

4. **traceback_registrado:** Failing job con ValueError, verifica JobResult error no None, contiene "Test traceback logging", traceback_str no None, contiene "Traceback" o "ValueError" y nombre función

5. **reintento_configurable:** Flaky job que falla 2 veces y luego success:
   - Con retries=2: debe intentar 3 veces (1+2) y luego success en 3er intento, attempt_count 3, success True, attempt 3
   - Con retries=1: mismo flaky que falla 2 veces debe finalmente fail, attempt_count 2, success False
   - Testeado con retry_delay 0 para no esperar en tests

6. **cron_parsing:** Cron válidos "0 3 * * 0", "0 */12 * * *", "0 9 * * *" parseados a CronTrigger, cron inválido "invalid cron" usa fallback sin crashear (daily 09:00)

**Todos los tests verifican aislamiento completo: si un job falla, los demás continúan, traceback registrado, retry configurable**

## Validación requerida por Ticket 009

- **APScheduler real:** BackgroundScheduler, ThreadPoolExecutor, CronTrigger, MemoryJobStore, listeners EVENT_JOB_EXECUTED/ERROR, max_workers 5, timezone America/Argentina/Buenos_Aires, job_defaults coalesce/max_instances/misfire_grace_time
- **Cada Job independiente:** Discover, Monitor, Notify, Cleanup, HealthCheck cada uno en su propio thread, si uno falla no bloquea otros (verificado con 3 jobs, job2 falla, job3 success)
- **Si un Job falla los demás continúan:** Testeado en test_aislamiento_fallos, job1 success, job2 fail, job3 success aunque job2 falló
- **Registrar traceback:** JobResult contiene error y traceback_str con traceback.format_exc(), logs en scheduler.log con formato [SCHEDULER] Job {id} attempt {attempt} FAILED ... Traceback
- **Reintento configurable:** retries y retry_delay_seconds desde config.yaml jobs.<id>.retries, testeado con flaky job que falla 2 veces y luego success: retries=2 -> 3 intentos y success, retries=1 -> 2 intentos y fail
- **Cron parsing:** "0 3 * * 0", "0 */12 * * *" parseados, inválido usa fallback daily 09:00 sin crashear

**Integración con infra existente:**

- Discover job usa PluginLoader scan y log discovered plugins
- Monitor job usa MonitoringEngine monitor_all (que ya usa PluginLoader runtime, Fingerprint, History, Notification)
- Notify job usa NotificationEngine check_watchlist_reminders y check_deadline_upcoming
- Cleanup job archiva notificaciones leídas >30 días
- HealthCheck job usa db.validate_integrity y plugin status report

**Sin romper infra existente:**

- Todos tests anteriores siguen OK: fingerprint 17, loader 7, hardening 3, monitoring 6, history 7, notification 7, scheduler 6 -> total 53 tests OK
- Doctor OK (WARN playwright optional)

## Archivos modificados/creados

- `config/config.yaml` añadido sección scheduler con enabled, timezone, max_workers, job_defaults, jobs discover/monitor/notify/cleanup/healthcheck cada con enabled, cron, retries, retry_delay_seconds, timeout_seconds, batch_size
- `jobs/scheduler_runtime.py` (400 líneas): SchedulerRuntime con BackgroundScheduler, ThreadPoolExecutor, CronTrigger, with_retry_and_isolation decorador, JobResult dataclass, 5 jobs definitions, add_jobs, start, shutdown, get_jobs, run_job_now, get_job_results, singleton get_scheduler_runtime
- `tests/unit/test_scheduler_runtime.py` (6 tests): creación y jobs, independientes, aislamiento fallos, traceback registrado, reintento configurable, cron parsing
- `scripts/TICKET_009_REPORT.md` (este archivo)

## Canales Futuro - Mejora no bloqueante anotada (Ticket 008 nota)

Hoy existe Notification Engine con salida LOG (monitor.log, notifications.log)

Sería bueno que internamente piense en:

```
Evento
  ↓
Notification
  ↓
Canal
```

Donde hoy único canal es LOG, mañana EMAIL, DISCORD, SLACK, WEBHOOK sin tocar resto.

**No implementar ahora, solo anotar como mejora futura:**

- En NotificationEngine, separar `create_notification` (crea en DB) de `dispatch` (envía por canales)
- `channels: ["db", "log"]` ya existe en config.yaml notifications.channels
- Futuro: channels ["db", "log", "email", "discord", "slack", "webhook"]
- Cada canal implementa `send(notification)` interface
- `dispatch` itera canales y envía, con try/except por canal para aislamiento (si email falla, log sigue)
- Sin tocar resto: solo agregar nuevo canal class y registrar en config

**Documentado en BACKLOG_TECNICO.md como mejora futura, no para este ticket.**

## Criterios de aceptación Ticket 009

- [x] APScheduler real implementado (BackgroundScheduler, ThreadPoolExecutor max_workers 5, CronTrigger, MemoryJobStore, listeners)
- [x] Cada Job independiente (discover, monitor, notify, cleanup, healthcheck) cada uno en su thread, si uno falla no bloquea otros
- [x] Si un Job falla los demás continúan (aislamiento completo verificado con 3 jobs, job1 success, job2 fail, job3 success aunque job2 falló)
- [x] Registrar traceback (JobResult error y traceback_str, logs scheduler.log con traceback completo)
- [x] Reintento configurable (retries, retry_delay_seconds desde config.yaml, testeado flaky job con retries 2 -> 3 intentos success, retries 1 -> 2 intentos fail)
- [x] Cron parsing y validación (válidos parseados, inválido fallback sin crashear)
- [x] Detenerse aquí y validar antes de continuar (no se implementó Ticket 010 provider real todavía)

## Próximos pasos (esperando validación)

Si aprueba Ticket 009, siguiente es **Ticket 010 - Primer Provider Real (Posterheroes)** utilizando exactamente pipeline ya construido:

- Scheduler Runtime con 5 jobs independientes ya validado
- Monitoring Engine con transacción atómica, idempotencia, métricas ya validado
- History que nunca pierde eventos ya validado
- Notification Engine con idempotencia exacta ya validado
- Fingerprint API congelada ya validado
- Plugin Loader Runtime con lifecycle y aislamiento ya validado

Provider real (Posterheroes) debe probarse ya dentro del runtime definitivo, con Scheduler funcionando, sin introducir excepciones ni lógica específica dentro de core, como recomendaste.

Después Runway (playwright), Adobe, AI Film Festival, It's Nice That.

Pero detenerse aquí para validación de Ticket 009.

## Decisiones de arquitectura

1. **BackgroundScheduler + ThreadPoolExecutor para aislamiento:** Cada job en su propio thread, si uno falla no bloquea otros. max_workers 5 para 5 jobs, suficiente. Si un job tarda mucho (ej. monitor con 25 sources), no bloquea healthcheck que debe correr cada hora.

2. **with_retry_and_isolation decorador:** Envuelve cada job con retry configurable desde YAML, loguea traceback completo, no lanza excepción hacia scheduler (retorna JobResult con success=False), así otros jobs continúan. Retry delay configurable para no spamear si falla por red temporal.

3. **Cron parsing con fallback:** Si cron string inválido, usa fallback daily 09:00 y log warning, no crashea scheduler. Importante para robustez si config.yaml tiene typo.

4. **JobResults tracking:** Lista de JobResult con job_id, success, duration, attempt, error, traceback, timestamp. Útil para monitoring y para tests que verifican aislamiento y retry.

5. **Integración con infra existente sin romper:** Discover usa loader, Monitor usa run_monitoring (que usa loader runtime, fingerprint, history, notification), Notify usa notification_engine, Cleanup archiva notificaciones, HealthCheck usa db.validate_integrity y loader status. Todos usan componentes ya validados.

6. **Canales futuro:** Dejado como mejora futura anotada, no implementado ahora. Hoy solo LOG, mañana EMAIL/DISCORD/SLACK/WEBHOOK sin tocar resto, mediante separación create_notification vs dispatch por canales.

## Resultado

Al finalizar Ticket 009, Radar dispone de Scheduler Runtime real con APScheduler:

- 5 jobs independientes: discover (semanal), monitor (cada 12h), notify (diario 09:00), cleanup (diario 02:00), healthcheck (cada hora)
- Si un job falla, los demás continúan (aislamiento completo verificado)
- Traceback registrado en scheduler.log y JobResult
- Reintento configurable desde config.yaml (retries, retry_delay_seconds)
- Cron parsing con fallback
- Base sólida para probar providers reales ya dentro del runtime definitivo

Listo para Ticket 010 - Primer Provider Real.

---

*Ticket 009 completado - Esperando validación HERMES antes de continuar*
*Detenerse aquí según instrucción*
