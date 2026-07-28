# TICKET 004 - REPORT: Plugin Loader Real

**Estado:** COMPLETADO
**Fecha:** 2026-07-26
**Objetivo:** Cargador que descubra plugins dinámicamente, valide manifests e integre con scheduler respetando enable por YML, evitando excepciones en core y contaminación con reglas específicas

## Resumen Ejecutivo

Se implementó `core/plugin_loader.py` como boundary real entre core y plugins. El core ahora no conoce ningún plugin específico, solo escanea `plugins/` leyendo `manifest.yaml`. El scheduler consume jobs desde el loader, respetando `enabled` y `schedule` del YAML. Fallos de un plugin no rompen core ni otros plugins.

## Implementación

### Archivo principal: `core/plugin_loader.py` (400+ líneas)

**Principios de diseño (senior):**
- Sin listas manuales en core: 100% filesystem scan
- Validación estricta de manifests
- Aislamiento de fallos: try/except alrededor de cada import/exec
- Config gobierna TODO: enable, schedule, priority desde YAML
- Core agnóstico: ninguna referencia a runway, posterheroes, etc en lógica del loader

**Dataclasses:**

```python
class PluginStatus(str, Enum):
    VALID, INVALID_MANIFEST, MISSING_CODE, LOAD_FAILED, DISABLED, ENABLED, LOADED

@dataclass
class PluginManifest:
    slug, name, provider_type, opportunity_types, version, description, raw, errors, valid, folder

@dataclass
class LoadedPlugin:
    slug, manifest, has_code, folder, enabled, schedule, priority,
    provider_class, status, error, config
    is_loadable -> enabled + valid + has_code + LOADED + class not None
    to_job_definition() -> dict para scheduler
```

**Clase `PluginLoader`:**

- `scan()` -> descubre plugins recorriendo `plugins/`, leyendo cada `manifest.yaml`, validando. Sin lista manual. Retorna `List[PluginManifest]` ordenado por slug.
  - Si no hay manifest.yaml, no es plugin (skip)
  - Si YAML parse error, crea manifest inválido para reporte doctor
  - Valida required fields, slug==folder, provider_type permitido, opportunity_types permitidos

- `_validate_manifest(manifest, folder_name)` -> (valid, errors, PluginManifest)

- `_load_plugin_class(folder)` -> (cls, error) con aislamiento:
  ```python
  try:
    spec = importlib.util.spec_from_file_location(...)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # con try/except interno
    buscar clase terminada en Provider
  except Exception as e:
    logger.error + traceback, return None, error
  ```
  Nunca lanza excepción hacia core.

- `load_all()` -> carga todos los descubiertos, respeta enable por YML, aisla fallos:
  - Lee `config.yaml` plugins.<slug>.enabled, schedule, priority
  - Si no está en config, por defecto DISABLED (seguro para producto)
  - Si manifest inválido -> status INVALID_MANIFEST
  - Si enabled sin plugin.py -> MISSING_CODE
  - Si tiene código pero exec_module falla -> LOAD_FAILED + error
  - Si enabled y todo OK -> LOADED
  - Si disabled -> DISABLED
  - Ordena por priority desc, slug
  - Log: "5 enabled, 5 loadable"

- `get_enabled_plugins()` -> solo enabled (respeta YML)
- `get_loadable_plugins()` -> solo is_loadable (puede ejecutarse)
- `get_jobs()` -> integración scheduler:
  ```python
  jobs = [
    {slug, name, schedule, priority, provider_type, opportunity_types, enabled, status, version, folder},
    ...
  ]
  Ordenado por schedule (hourly < every 12h < daily < weekly) y priority desc
  Solo enabled con manifest válido y código (o al menos no missing_code)
  ```

- `get_status_report()` -> reporte completo para doctor y CLI:
  - total_discovered, total_enabled, total_loadable, total_invalid_manifest, total_missing_code, total_load_failed, total_orphans
  - plugins, enabled, loadable, invalid, missing_code, load_failed, orphans, jobs

- `reload()` -> hot-reload filesystem + config

**Singleton y funciones conveniencia:**
```python
get_plugin_loader() -> PluginLoader singleton
get_enabled_plugins() -> List[LoadedPlugin]
get_loadable_plugins()
get_jobs_for_scheduler() -> API para scheduler
```

### Integración Scheduler: `jobs/scheduler.py`

```python
class RadarScheduler:
  __init__(self, plugins_dir, config) -> loader = get_plugin_loader()
  get_jobs() -> loader.get_jobs() # respeta enable YML
  get_schedule_by_frequency() -> {daily: [...], weekly: [...]}
  print_schedule() -> muestra DAILY (5 jobs), WEEKLY, etc + system jobs discover, monitoring
  validate_schedules() -> detecta schedule inválido, plugin enabled pero no loadable
  get_next_run_info() -> simulación próxima ejecución
```

Scheduler no conoce lista manual de plugins. Todo viene de loader.

### Actualización Doctor v2.1: Usa Plugin Loader Real

`core/doctor.py` `check_plugins_diagnostics()` ahora usa `PluginLoader`:

- `Plugins:Discovered` -> 9 discovered from filesystem (Plugin Loader real, dynamic)
- `Plugins:Valid` -> 9 valid, 0 invalid manifests
- `Plugins:Enabled` -> 5 enabled via config.yaml (respeta enable YML)
- `Plugins:Loadable` -> 5 loadable (manifest válido + código + sin error)
- Detecta `Plugin:xxx:manifest` FAIL si invalid
- Detecta `Plugin:xxx:code` WARN si enabled sin plugin.py
- Detecta `Plugin:xxx:load` FAIL si load failed (aislado)
- Detecta orphans config
- `PluginLoader` OK - dynamic filesystem scan, manifest validation, isolation, YML enable respect
- `Scheduler:jobs` OK - 5 jobs from loader (respeta enable YML) - discover->monitor->score->notify
- `Core:agnostic` OK - boundary loader

### CLI actualizado: `cli/main.py`

Nuevos comandos:

- `python -m radar plugins` -> tabla all plugins discovered (dynamic registry)
  - columnas: Slug, Name, Enabled, Status, Schedule, Priority, Has Code, Manifest Valid, Provider, Types
  - WARN si invalid manifests, missing code, load failed

- `python -m radar plugins --enabled` -> solo enabled respetando YAML

- `python -m radar schedule` -> muestra schedule agrupado por frecuencia + system jobs + validación

`stats` y `doctor` ahora usan loader real en vez de registry viejo.

## Tests: `tests/unit/test_plugin_loader.py` - 7 tests, todos OK

1. **discovery dinamico:** 9 plugins desde filesystem, sin lista manual, cada folder existe, viene de filesystem

2. **validacion manifests:** con temp dir crea valid_plugin (OK), invalid_plugin (falta required), mismatch (slug mismatch). Debe detectar 2 inválidos. Verifica valid_plugin válido.

3. **enable por YML:** según config.yaml 5 enabled (runway, posterheroes, adobe, itsnicethat, ai-film-festival). openai, leonardo disabled. Loadable subset de enabled. Respeta config gobierna TODO.

4. **aislamiento fallos:** Crea temp plugins con 2 buenos, 1 con syntax error en plugin.py, 1 con manifest inválido. Loader debe descubrir 4 sin crashear, good cargan OK, broken -> LOAD_FAILED con error, invalid -> INVALID_MANIFEST, loadable solo 2 buenos. Un plugin roto no rompe core ni otros.

5. **integracion scheduler:** get_jobs() retorna 5 jobs solo enabled, cada con schedule, priority, provider_type, opportunity_types, enabled true, schedule en allowed list o cron, ordenados por priority desc, disabled no están.

6. **core agnostico:** source de loader no contiene `if slug == "runway"` etc. Solo genérico.

7. **reload:** hot-reload funciona, mismo count.

Salida:
```
✓ discovery dinamico: 9 plugins desde filesystem, sin lista manual en core
✓ validacion manifests: detecta inválidos, slug mismatch, required fields
✓ enable por YML: 5 enabled respetando config.yaml, loadable=5
✓ aislamiento fallos: 1 plugin roto no rompió core, 2 buenos siguen loadable
✓ integracion scheduler: 5 jobs con schedule y priority respetando enable YML
✓ core agnostico: loader sin reglas específicas
✓ reload: hot-reload funciona
```

## Validación Doctor + CLI

```bash
$ python -m radar doctor
Plugins:Discovered OK 9 discovered from filesystem (Plugin Loader real, dynamic)
Plugins:Valid OK 9 valid, 0 invalid manifests
Plugins:Enabled OK 5 enabled via config.yaml (respeta enable YML)
Plugins:Loadable OK 5 loadable
Plugin:posterheroes OK enabled, sched=daily, provider=beautifulsoup...
Plugin:runway OK enabled, sched=daily, provider=playwright...
Core:agnostic OK Core has no hardcoded org rules - org logic in plugins/ only (Loader como boundary)
PluginLoader OK Plugin Loader real v1 - dynamic filesystem scan, manifest validation, isolation, YML enable respect
Scheduler:jobs OK 5 jobs from loader (respeta enable YML)
RESULT: OK (with WARN expected)

$ python -m radar plugins
All Plugins Discovered (dynamic registry desde filesystem)
posterheroes ✓ loaded daily 10 ✓ ✓ beautifulsoup contest,festival
runway ✓ loaded daily 10 ✓ ✓ playwright contest,grant,beta,festival
adobe ✓ loaded daily 9 ✓ ✓ beautifulsoup residency,grant,beta,fellowship
...

$ python -m radar schedule
=== RADAR SCHEDULE (respeta enable por YML) ===
DAILY (5 jobs):
  - posterheroes........ priority=10 provider=beautifulsoup types=['contest', 'festival']
  - runway.............. priority=10 provider=playwright types=['contest', 'grant', 'beta', 'festival']
  - adobe............... priority=9 provider=beautifulsoup types=['residency', 'grant', 'beta', 'fellowship']
  ...
SYSTEM JOBS:
  - discover: schedule=0 3 * * 0 enabled=True
  - monitoring: schedule=0 */12 * * * enabled=True
```

## Criterios de aceptación Ticket 004

- [x] Registro dinámico de verdad recorriendo carpeta plugins y leyendo cada manifest sin atar core (loader.scan() 100% filesystem)
- [x] Valida manifests y detecta rotos (invalid_manifests, slug mismatch, provider_type, opportunity_types)
- [x] Detecta plugins habilitados sin implementación (MISSING_CODE) y errores carga (LOAD_FAILED) sin romper core
- [x] Integra con scheduler respetando enable por YML (get_jobs() solo enabled, schedule por plugin, priority orden)
- [x] Evita excepciones en core (try/except alrededor de yaml parse, exec_module, import, con logger y traceback, retorna error en vez de throw)
- [x] Mantiene arquitectura ordenada y fácil de mantener (loader como boundary entre core y plugins, core agnóstico, plugins/ contiene toda lógica específica)
- [x] Core agnóstico sin reglas específicas de organizaciones (verificado grep, doctor Core:agnostic OK)
- [x] Tickets pequeños y verificables (tests unitarios + doctor + CLI)

## Próximos tickets sugeridos

- Ticket 005: `core/history.py` - Change Tracker + `watchlist`/`notifications` integrados con loader
- Ticket 006: Primer scraper real Posterheroes usando Provider + FingerprintEngine + Loader (plugin posterheroes ya tiene skeleton, ahora implementar fetch/extract real)
- Ticket 007: Scraper Runway (playwright) validando deduplicación cross-source con fingerprint

¿Siguiente?
