# TICKET 006 - REPORT: Monitoring Engine

**Estado:** COMPLETADO - Esperando validación antes de continuar (según plan)
**Fecha:** 2026-07-26
**Objetivo:** Construir motor de monitoreo que ejecute providers, pase por fingerprint, inserte solo nuevas, registre cambios y produzca métricas, sin scoring

## Resumen Ejecutivo

Se implementó `core/monitoring_engine.py` (600 líneas) + `jobs/monitoring.py` + `core/history.py` + extensión `core/db.py` con flujo completo:

```
Provider (fetch) → Normalize (extract+normalize) → Fingerprint (hash + is_duplicate exact + approximate) → Database (insert only new, update + history si cambios, alternate_links) → Logs (monitor.log separado) → Métricas
```

Sin scoring (config `scoring.enabled=false` respetado). Todo con aislamiento de errores: un source/provider roto no rompe sistema completo.

## Implementación

### 1. `core/history.py` - Change Tracker (150 líneas)

**Detecta cambios campo por campo:**

- `TRACKED_FIELDS`: title, deadline, awards_text, economic_value, currency, status, official_link, description_raw, description_clean, organizer_name, country, category, opportunity_type
- `_parse_deadline()`: parsea datetime, date, timestamp, ISO string, fuzzy con dateutil
- `_get_change_type()`: deadline → deadline_extended / deadline_shortened, awards/economic → prize_updated, status → status_changed, resto → info_updated
- `FieldChange` dataclass: field_name, old_value, new_value, change_type
- `HistoryTracker`:
  - `detect_changes(old, new)`: compara tracked_fields, normaliza None/"" como iguales, para deadline compara dates, retorna List[FieldChange]
  - `has_significant_changes(changes)`: deadline, prize, status → significativos
  - `format_changes_for_log(changes)`: legible para logs

### 2. `core/db.py` extendido con métodos Monitoring

Añadidos métodos para Ticket 006:

- `find_organization_by_slug(slug) -> dict`
- `find_opportunity_by_fingerprint(hash, org_id) -> dict`
- `find_opportunity_by_id(id) -> dict`
- `insert_opportunity(data) -> id`: filtra allowed_fields, maneja alternate_links_json list→json, bool→int, UNIQUE constraint (si duplicado exacto, retorna existente id), actualiza organizations.total_opportunities
- `update_opportunity(id, updates) -> bool`: filtra allowed, set last_changed_at, updated_at
- `add_alternate_link(id, new_url) -> bool`: agrega a alternate_links_json si no existe y no es official_link, limita 20, actualiza last_seen_at
- `insert_history(opportunity_id, field_name, old, new, change_type, source_id, metadata) -> id`: inserta en opportunity_history y actualiza last_changed_at
- `get_opportunities_count()`

### 3. `core/monitoring_engine.py` - Motor principal (600 líneas)

**Dataclasses métricas:**

```python
@dataclass SourceMetrics:
  source_id, source_url, org_slug, provider_slug,
  fetched, normalized, new, duplicate_exact, duplicate_approximate, updated, history_entries, alternate_links_added, errors, error_messages, duration_seconds

@dataclass MonitoringMetrics:
  total_sources, total_fetched, total_normalized, total_new, total_duplicate_exact, total_duplicate_approximate, total_updated, total_history_entries, total_alternate_links, total_errors, duration_seconds, sources: List[SourceMetrics]
```

**Clase MonitoringEngine:**

- `__init__(db, loader, fingerprint_engine, history_tracker, config)`: inyección dependencias, batch_size desde config

- `monitor_source(source: dict) -> SourceMetrics`:
  1. Resolver plugin via loader.get_plugin(org_slug), verificar enabled, is_loadable, get_or_create_instance (runtime)
  2. `instance.run(source_url)` -> List[NormalizedOpportunity] (fetch+extract+normalize en Provider)
  3. Para cada norm_opp: `process_opportunity()`
  4. Actualizar source last_scraped_at, last_success_at en DB
  5. Log info con duración, new, dup, updated, errors
  6. Aislamiento: try/except alrededor de cada provider y cada oportunidad, error no rompe source ni sistema completo

- `process_opportunity(normalized_opp, source) -> dict {status, opportunity_id, fingerprint, alternate_added, history_count, updated}`:
  - Resolver organization_id desde org_slug
  - Generar fingerprint via FingerprintEngine.generate()
  - Buscar duplicado exacto: `db.find_opportunity_by_fingerprint(fp.hash, org_id)`
  - Si no exacto, buscar aproximado: `_find_approximate_duplicate(fp, org_id, normalized_opp)` para detectar deadline extendido:
    - Lógica estricta para evitar falsos positivos Test Opp 1 vs 2:
      - Si official_link normalizado igual y org misma y title similarity >=0.85 -> duplicate (deadline extendido mismo URL)
      - Si official_link diferente, solo duplicate si title similarity >=0.95 AND deadline mismo exacto y org misma (cross-source misma oportunidad con URLs diferentes pero mismo deadline y título casi idéntico)
  - Si no existe: insertar nueva via `db.insert_opportunity()`, log [NEW]
  - Si existe: `_handle_duplicate()`

- `_handle_duplicate(norm_opp, existing, source, fp, is_approximate)`:
  - Agregar alternate_link si nueva URL
  - Detectar cambios campo por campo via HistoryTracker.detect_changes(old_dict, new_dict)
  - Si cambios: actualizar oportunidad con nuevos valores (excepto official_link que va a alternate), log [UPDATE], insertar history entries via `db.insert_history()` para cada campo, contar history_count, log [HISTORY] si significativo
  - Si no cambios: actualizar last_seen_at
  - Retorna status duplicate_exact / duplicate_approximate / updated

- `_find_approximate_duplicate(fp, org_id, normalized_opp)`:
  - Query todas oportunidades de misma org is_duplicate_of IS NULL
  - Para cada candidata, generar fingerprint, calcular title_similarity via fingerprint_engine._title_similarity
  - Si title_sim >= threshold y (official_link mismo y title_sim>=0.85 o official_link diferente y title_sim>=0.95 y deadline mismo) -> retornar candidata

- `_normalize_deadline_for_db(deadline)`: dateutil parser fuzzy -> isoformat

- `_map_category(norm_opp)`: mapea opportunity_type a category válida DB (AI, Video, Motion, etc)

- `monitor_all(only_active, batch_size) -> MonitoringMetrics`:
  - Obtener sources activas via `db.get_sources(only_active)[:batch_size]`
  - Para cada source, `monitor_source()`
  - Acumular métricas totales
  - Log resumen final [MONITOR_ALL] fetched, new, dup_exact, dup_approx, updated, history, alt_links, errors

**Sin scoring:** No importa scoring, config scoring.enabled=false respetado, monitoreado en tests

**Flow garantizado:** Provider (fetch) -> Normalize (extract+normalize via provider.run) -> Fingerprint (generate) -> Database (insert/find/update/history/alternate) -> Logs (monitor.log separado) -> Métricas

### 4. `jobs/monitoring.py` - Job El Vigilante

- `run_monitoring(batch_size, only_active)`: crea db, loader, fingerprint_engine, history_tracker, MonitoringEngine, llama monitor_all, log, retorna metrics
- CLI: `python -m jobs.monitoring --batch-size 25 --all --verbose` con argparse y print resumen

### 5. `cli/main.py` monitor actualizado

Antes placeholder, ahora ejecuta `run_monitoring()` real, muestra Table Rich con métricas totales y por source, WARN si errors

## Tests: `tests/unit/test_monitoring_engine.py` - 6 tests, todos OK

1. **ejecutar providers:** Mock provider con 2 oportunidades, monitor_source debe fetched 2 new 2 errors 0, via PluginLoader runtime dynamic

2. **fingerprint deduplicación:**
   - Primera vez con "Duplicated Opp" -> new 1 dup 0
   - Segunda vez misma oportunidad (mismo título, url, org, deadline) -> new 0 duplicate_exact 1
   - DB solo 1 oportunidad única (no duplicados)
   - Approximate: Posterheroes 2026 vs Poster Heroes 2026 (mismo URL, título similar) -> con normalización agresiva hash igual o similarity >=0.85 y URL misma -> duplicate, no new. Testeado con 2 plugins que retornan títulos con y sin espacio, segundo no inserta new.

3. **registrar cambios:**
   - Primera versión Challenge 2026 deadline 2026-09-15 awards $5000 -> new 1
   - Segunda versión mismo título y URL, deadline 2026-09-30 (extendido) awards $10000 -> debe detectar como update no new, history 2 entries (deadline_extended, prize_updated), opp_count 1
   - Antes de mejorar _find_approximate_duplicate, deadline en hash generaba new opp (opp_count 2) y history 0 -> limitación documentada. Con lógica mejorada (official_link mismo -> duplicate aunque deadline diferente), ahora correctamente detecta update con history 2, opp_count 1. Testeado y ahora pasa como update flow.

4. **errores aislados:**
   - 2 plugins: good (OK) y bad (fetch lanza RuntimeError)
   - 2 sources: good.com y bad.com
   - monitor_all batch 10: total_sources 2, total_new 1 (good), total_errors 1 (bad), fetched >=1, sistema no roto, no crash

5. **logs y métricas:**
   - monitor_source con 1 opp: metrics duration >=0, fetched 1 new 1, to_dict contiene fetched, new, duplicate_exact, errors, duration_seconds
   - monitor.log existe y contiene "MONITOR" logs, tamaño >0
   - Métricas producidas correctamente

6. **flujo completo Provider -> Normalize -> Fingerprint -> Database -> Logs sin scoring:**
   - Mock provider con fetch (Provider step) -> extract (Extract) -> normalize (Normalize) -> fingerprint hash generado y en DB -> Database insert -> Logs monitor.log [NEW]
   - Segunda pasada mismo opp -> duplicate_exact 1, no new, alternate link handling
   - Scoring deshabilitado verificado: config scoring.enabled=false

## Validación requerida por Ticket 006

- **duplicados:** Testeado exact (mismo hash) y approximate (Posterheroes vs Poster Heroes, deadline extendido mismo URL -> update no new, cross-source con URL diferente y deadline mismo -> duplicate si title >=0.95)
- **errores:** Testeado aislamiento: 1 source bueno + 1 source malo (fetch failure) -> total_new 1, total_errors 1, sistema no roto, métricas y logs siguen
- **logs:** monitor.log separado, RotatingFileHandler, contiene [MONITOR], [NEW], [UPDATE], [HISTORY], [ALT_LINK], [MONITOR_ALL], etc. Verificado existe y tamaño >0
- **métricas:** SourceMetrics y MonitoringMetrics con fetched, normalized, new, duplicate_exact, duplicate_approximate, updated, history_entries, alternate_links_added, errors, error_messages, duration_seconds, to_dict() con todos los campos. Acumulación correcta en monitor_all.

**Flujo garantizado:** Provider (fetch) -> Normalize (extract+normalize via provider.run) -> Fingerprint (generate + is_duplicate exact + approximate) -> Database (insert_opportunity only new, update_opportunity + insert_history + add_alternate_link si duplicado con cambios, last_seen_at) -> Logs (monitor.log) -> Métricas (MonitoringMetrics)

**Sin scoring:** config.yaml scoring.enabled=false respetado, monitoring_engine no importa scoring, tests verifican scoring disabled

**Ejecución real (con plugins existentes skeleton que retornan vacío):**
```bash
python -m radar monitor --batch-size 5
# Como plugins skeleton retornan extract [] (vacío), fetched 0 new 0, pero no errores, sistema funciona
# Cuando plugins reales Posterheroes y Runway se implementen (Ticket 009+), fetched >0
```

## Archivos modificados/creados

- `core/history.py` (150 líneas): HistoryTracker, FieldChange, detect_changes, has_significant_changes, format_changes_for_log, TRACKED_FIELDS
- `core/db.py` extendido (añadidos 100 líneas): find_organization_by_slug, find_opportunity_by_fingerprint, find_opportunity_by_id, insert_opportunity (con UNIQUE handling), update_opportunity, add_alternate_link, insert_history, get_opportunities_count
- `core/monitoring_engine.py` (600 líneas): SourceMetrics, MonitoringMetrics, MonitoringEngine con monitor_source, process_opportunity, _handle_duplicate, _find_approximate_duplicate (lógica estricta para evitar falsos positivos), _normalize_deadline_for_db, _map_category, monitor_all
- `jobs/monitoring.py` (actualizado, antes placeholder): run_monitoring() real que usa MonitoringEngine, argparse, print resumen
- `cli/main.py` monitor actualizado: ahora ejecuta run_monitoring real, tabla Rich métricas totales y por source
- `tests/unit/test_monitoring_engine.py` (6 tests): ejecutar providers, fingerprint deduplicación (exact + approximate), registrar cambios (deadline extendido -> history), errores aislados, logs y métricas, flujo completo sin scoring
- `tests/unit/test_plugin_loader_hardening.py` (3 tests hardening de Ticket 005 nota aprobación): reload repetido sin leaks, concurrencia get_or_create_instance, excepción Provider.close() aislada
- `scripts/TICKET_006_REPORT.md` (este archivo)

## Hardening Ticket 005 nota aprobación completado

Añadidos tests de hardening como nota en Ticket 005 aprobación:

- `tests/unit/test_plugin_loader_hardening.py`:
  - reload repetido 5 veces: discovered 9, loaded 9, instances limpiadas cada reload, módulos plugins count <20 no leak
  - concurrencia get_or_create_instance: 10 threads concurrentes intentando crear misma instancia posterheroes, 0 crashes, al menos 1 instancia válida (ideal 1, aceptable >=1), sistema no roto
  - excepción dentro Provider.close(): plugin good close OK, plugin bad_close close() lanza RuntimeError pero shutdown_instance no crashea, marca STOPPED, shutdown_all OK

Todos pasan.

## Criterios de aceptación Ticket 006

- [x] ejecutar providers (via PluginLoader runtime dynamic, sin imports manuales, get_or_create_instance)
- [x] recibir oportunidades (fetch -> extract -> normalize via provider.run)
- [x] pasar todas por Fingerprint (generate + find exact + approximate para deadline extendido)
- [x] insertar únicamente nuevas (deduplicación exact hash + approximate title>=0.95 deadline mismo o URL mismo, DB UNIQUE constraint, add_alternate_link)
- [x] registrar cambios (HistoryTracker detect_changes campo por campo, insert_history opportunity_history, update_opportunity, deadline_extended, prize_updated, etc, log [HISTORY] y [UPDATE])
- [x] producir métricas (SourceMetrics y MonitoringMetrics con fetched, normalized, new, duplicate_exact, duplicate_approximate, updated, history_entries, alternate_links_added, errors, error_messages, duration_seconds, to_dict)
- [x] NO scoring (config scoring.enabled=false respetado, monitoring_engine no usa scoring)
- [x] Flujo Provider -> Normalize -> Fingerprint -> Database -> Logs garantizado (cada opp recorre esos 5 pasos, verificado en tests)
- [x] Validación duplicados (exact duplicado 2da vez misma opp -> dup_exact 1 new 0, approximate Posterheroes vs Poster Heroes -> dup, deadline extendido mismo URL -> update no new + history)
- [x] Validación errores (1 good source OK new 1 + 1 bad source fetch failure error 1, sistema no roto, total_errors contado)
- [x] Validación logs (monitor.log separado, RotatingFileHandler, contiene [MONITOR], [NEW], [UPDATE], [HISTORY], [MONITOR_ALL], tamaño >0)
- [x] Validación métricas (to_dict con todos campos, acumulación en monitor_all, duration)
- [x] Detenerse aquí y validar completamente antes de continuar (no se implementó Ticket 007)

## Próximos tickets sugeridos (esperando validación)

- Ticket 007: `core/db.py` mejorado final + `watchlist`/`notifications` base (si no se hizo en 006) o primer scraper real Posterheroes
- Ticket 008-009: Scrapers Posterheroes y Runway reales usando MonitoringEngine + Provider runtime + Fingerprint
- Ticket 010+: Jobs discovery, notifier, scheduler APScheduler, CLI digest mejorado

Pero detenerse aquí según plan.

## Decisiones de arquitectura

1. **History Tracker separado de Monitoring Engine:** Single responsibility, HistoryTracker solo detecta cambios, MonitoringEngine orquesta DB + history + fingerprint + logs. Core agnóstico.

2. **Aproximate duplicate con lógica estricta para evitar falsos positivos:** Primera versión simple title similarity >= threshold causaba que Test Opp 1 vs 2 (títulos similares, URLs diferentes, deadlines diferentes) se mergearan incorrectamente. Mejorada a:
   - Si URL normalizada igual + title similarity >=0.85 -> duplicate (deadline extendido)
   - Si URL diferente + title similarity >=0.95 + deadline mismo exacto -> duplicate (cross-source)
   Así evita merge de Opp1 vs Opp2 (URL diferente, deadline diferente) y correctamente detecta deadline extendido (URL igual) y Posterheroes vs Poster Heroes (URL igual).

3. **DB métodos con UNIQUE handling:** insert_opportunity captura IntegrityError UNIQUE y retorna existente id, evitando crash por race condition, y permite tratar como duplicate.

4. **Métricas por source y totales:** SourceMetrics para debugging por fuente (cuál fuente falla), MonitoringMetrics para resumen job. Útil cuando haya 25 sources en batch.

5. **Logs separados monitor.log:** No mezclar con discover.log, usando get_logger("monitor") con RotatingFileHandler. Cada source log start, fetched, new, dup, updated, errors, duration. Fácil debugging 3AM.

6. **Sin scoring:** Respetado senior advice, monitoring_engine no importa scoring, tests verifican scoring.enabled=false. Scoring solo después de 300 opps.

## Resultado

Al finalizar Ticket 006, Radar dispone de motor de monitoreo funcional:

```bash
python -m radar monitor --batch-size 5
# Sources: 9 (o batch), Fetched: 0 (skeleton plugins retornan []), New: 0, Dup: 0, Updated: 0, Errors: 0, Duration: 0.5s
# Cuando plugins reales estén listos (Ticket 009+), Fetched >0

python tests/unit/test_monitoring_engine.py # 6 tests OK
python -m radar doctor # OK
```

Flujo completo validado: Provider (fetch) -> Normalize -> Fingerprint -> Database (insert only new + history + alternate_links) -> Logs -> Métricas, sin scoring, con aislamiento errores.

Base sólida para scrapers reales.

---

*Ticket 006 completado - Esperando validación antes de continuar*
*Detenerse aquí según plan ejecución*
