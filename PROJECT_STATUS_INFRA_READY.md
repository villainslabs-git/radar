# Radar - Estado Infraestructura Principal ✅ COMPLETA

**Fecha:** 2026-07-27
**Veredicto:** Ticket 006 y 007 Aprobados - Infraestructura principal lista, detener core y pasar a providers reales

---

## Infraestructura Validada

```
Plugin Loader         ✅ - Descubrimiento dinámico, validación manifest, aislamiento fallos, enable/disable YML, prioridades
Runtime               ✅ - Instanciación dinámica, lifecycle CREATED->INITIALIZED->RUNNING->STOPPED->FAILED, concurrencia, reload sin leaks, close exception aislada
Monitoring            ✅ - Orquestador sin lógica negocio mezclada, ejecuta providers, flujo Provider->Normalize->Fingerprint->DB->Logs, métricas por source y globales, error isolation, transacción atómica, idempotencia
History               ✅ - Subsistema propio separado, first_seen inmutable, last_seen siempre actualizado, nunca borrar solo status=closed, idempotencia, transacción atómica
Fingerprint           ✅ - API congelada v1, 12 funcs normalización independientes, solo info estable, 2 niveles exacta y aproximada RapidFuzz, 0 manual imports
Deduplicación         ✅ - Exact hash + approximate title>=0.85 URL igual o title>=0.95 deadline mismo, evita falsos positivos Test Opp 1 vs 2
Métricas              ✅ - SourceMetrics y MonitoringMetrics con fetched, new, duplicate_exact, duplicate_approximate, updated, history, alternate_links, errors, duration
Logs                  ✅ - Separados por job monitor.log, discover.log, scheduler.log, doctor.log, RotatingFileHandler, formato senior
```

**Tests:**
- test_fingerprint: 17 OK
- test_plugin_loader: 7 OK
- test_plugin_loader_hardening: 3 OK (reload sin leaks, concurrencia 10 threads, close exception)
- test_monitoring_engine: 6 OK (ejecutar providers, deduplicación, registrar cambios, errores aislados, logs y métricas, flujo completo)
- test_opportunity_history: 7 OK (primera/última aparición, deadline, URL, estado, descripción, nunca perder historial, historial completo 7 eventos ordenados)
- Doctor: OK (WARN playwright optional expected)

---

## Validación Senior Ticket 006 y 007

### Ticket 006 Aprobado - Observaciones menores implementadas

**Muy bien resuelto:**
1. Monitoring Engine es orquestador, no mezcla lógica negocio con Provider/Fingerprint/History/DB
2. History separado, responsabilidad clara Opportunity -> OpportunityHistory
3. Error isolation: falla un Provider o una Opportunity y resto continúa
4. Métricas por source y globales
5. Sin scoring (pipeline limpio)

**Hardening implementado:**
1. Transacción atómica por oportunidad: BEGIN -> update + history + alternate_links -> COMMIT, rollback si falla history (crítico)
2. Idempotencia: alternate_links solo si no existe, history verifica último mismo campo/valores skip, detect_changes asegura 2da pasada sin cambios no genera nada, monitor_all crash rerun no duplica
3. Escalabilidad duplicate approximate: documentado como optimización futura vía índice/candidatos cuando >1k, no implementar hasta volumen lo justifique

**Me gusta especialmente:** Regla URL igual + deadline distinta -> UPDATE en lugar de NEW evita falsos positivos

### Ticket 007 Aprobado - Historial como subsistema propio

**Muy bien resuelto:**
1. Historial subsistema propio separado: Opportunity -> OpportunityHistory, permite mañana construir timeline, auditoría, digest, watchlists, notificaciones sin tocar monitoring
2. first_seen inmutable, last_seen siempre actualizado, evita perder info temporal
3. Nunca borrar, solo status=closed, preserva historial, estadísticas, fingerprints, auditoría (DELETE sería error)
4. Idempotencia: transacción única, history idempotente, alternate links idempotentes (clase importante problemas cuando job falla a mitad)
5. Backlog técnico correcto: no optimizar prematuramente _find_approximate_duplicate, solo documentar

**Notas futuro anotadas (no implementar ahora):**
- Versionado: reconstruir estado completo oportunidad en cualquier fecha via snapshots
- Event sourcing parcial: eventos already tienen forma created, deadline_extended, status_changed, description_changed, podría convertirse en Event Log algún día

---

## Decisión Arquitectura: Detener Core y Pasar a Providers Reales

**Riesgo principal ya NO está en core, está en providers reales.**

No agregar:
- más managers
- más engines
- más capas
- más abstracciones

Pasar directamente a:
1. Posterheroes real
2. Runway real
3. Adobe real
4. AI Film Festival
5. It's Nice That

Porque scrapers reales validarán si arquitectura responde bien frente a HTML real, cambios estructura, fechas inconsistentes, URLs variables, datos incompletos.

**Flujo validado que usarán scrapers reales:**
```
Provider (fetch httpx/playwright -> extract BeautifulSoup -> normalize dateparser)
  ↓
Fingerprint (hash + is_duplicate exact + approximate con lógica estricta URL igual + title>=0.85 o URL diferente + title>=0.95 + deadline mismo)
  ↓
Database (insert only new UNIQUE handling, update + history + alternate_links en transacción atómica idempotente, first_seen inmutable, last_seen siempre)
  ↓
Logs (monitor.log separado) -> Métricas (SourceMetrics, MonitoringMetrics)
```

Sin scoring (hasta 300 opps reales).

---

## Próximos Tickets Recomendados - Fase Providers Reales

**Ticket 008: Scraper Posterheroes Real**
- plugins/posterheroes/plugin.py real: fetch httpx, extract BeautifulSoup con selectors (ej. .event-card, .deadline, .prize), normalize dateparser para deadline, awards_text, category
- Debe recorrer flujo validado Provider->Normalize->Fingerprint->Database->Logs
- Validar con URL real https://posterheroes.org/competition/ o HTML guardado en data/raw/
- Métricas: fetched >0, new insertado, history created, logs monitor.log
- No scoring

**Ticket 009: Scraper Runway Real (playwright)**
- plugins/runway/plugin.py real con playwright (requiere JS), fetch blog y festival pages
- Validar deduplicación cross-source: misma oportunidad en runway oficial + itsnicethat aggregator -> 1 registro con alternate_links
- Manejar fechas inconsistentes, URLs variables

**Ticket 010: Scraper Adobe Real**
- plugins/adobe/plugin.py: Creative Residency, Grants, Beta programs

**Ticket 011: Scraper AI Film Festival + It's Nice That aggregator**

**Ticket 012: Integration Test con datos reales**
- Ejecutar python -m radar monitor --batch-size 5 con plugins reales
- Verificar 50-100 oportunidades reales, deduplicadas, con history, métricas

---

## Archivos Clave Infraestructura Lista

- `core/plugin_loader.py` (830 líneas, Runtime v2, discovery dinámico, validación manifest, aislamiento fallos, enable/disable YML, prioridades, lifecycle, transacción atómica)
- `core/monitoring_engine.py` (600 líneas, SourceMetrics, MonitoringMetrics, monitor_source, process_opportunity, _handle_duplicate atómico + idempotente, _find_approximate_duplicate estricto, monitor_all)
- `core/opportunity_history.py` (250 líneas, sistema historial nunca pierde, first/last appearance, deadline, URL, estado, descripción, nunca DELETE, eventos)
- `core/history.py` (150 líneas, HistoryTracker detect_changes)
- `core/fingerprint.py` (800 líneas, API congelada v1, 12 funcs normalización)
- `core/db.py` (extendido, find, insert, update, alternate_links, history, idempotencia)
- `jobs/monitoring.py` (run_monitoring real)
- `cli/main.py` (monitor real con tabla Rich)
- `tests/unit/test_*.py` (17+7+3+6+7 = 40 tests OK)
- `BACKLOG_TECNICO.md` (transacción atómica ✅, idempotencia ✅, escalabilidad 📝 documentada)
- `config/config.yaml` (scoring.enabled=false respetado)

---

## Comandos para Fase Providers Reales

```bash
# Validar infra lista
python -m radar doctor # RESULT OK
python tests/unit/test_fingerprint.py # 17 OK
python tests/unit/test_plugin_loader.py # 7 OK
python tests/unit/test_plugin_loader_hardening.py # 3 OK
python tests/unit/test_monitoring_engine.py # 6 OK
python tests/unit/test_opportunity_history.py # 7 OK

# Ejecutar monitoreo con plugins actuales (skeleton retornan vacío)
python -m radar monitor --batch-size 5
# Cuando Posterheroes real esté listo, fetched >0

# Ver plugins
python -m radar plugins --enabled # 5 enabled
python -m radar schedule # DAILY 5 jobs

# Ver digest headless
python -m radar digest # Total oportunidades: 0 (fase recolección)
```

---

## Notas Futuro (no implementar ahora)

- **Versionado:** reconstruir estado completo oportunidad en cualquier fecha via snapshots
- **Event sourcing parcial:** eventos already tienen forma created, deadline_extended, status_changed, podría convertirse en Event Log

---

*Infraestructura principal completa - 40 tests OK - Doctor OK - Listo para providers reales*
*Decisión: detener core, pasar a Posterheroes, Runway, Adobe, AI Film Festival, It's Nice That*
