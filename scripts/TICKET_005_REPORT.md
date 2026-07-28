# TICKET 005 - REPORT: Plugin Loader Runtime

**Estado:** COMPLETADO - Esperando validación HERMES antes de continuar (según plan)
**Fecha:** 2026-07-26
**Objetivo:** Construir verdadero cargador dinámico de plugins

## Resumen Ejecutivo

Se construyó `core/plugin_loader.py` Runtime v2 que cumple todos los requisitos de Ticket 005:

- Descubre plugins automáticamente recorriendo `plugins/` sin lista manual
- Valida manifest (required fields, slug==folder, provider_type, opportunity_types)
- Carga Provider dinámicamente vía `importlib.util.spec_from_file_location` sin `from plugins.runway import ...`
- Instancia Provider dinámicamente con `Provider(organization_slug, config)`
- Controla lifecycle: CREATED -> INITIALIZED -> RUNNING -> STOPPED -> FAILED con tracking
- Soporta enable/disable respetando `config.yaml` `plugins.<slug>.enabled`
- Soporta prioridades: orden desc por priority, schedule grouping
- Registra errores sin detener sistema: try/except alrededor de YAML parse, exec_module, __init__, con logger y traceback, instancia fallida marcada FAILED pero otros siguen

No existe ningún import manual tipo `from plugins.runway import ...` en core/jobs/cli (verificado vía AST, no grep naive que daba falsos positivos).

## Implementación

### Archivo: `core/plugin_loader.py` Runtime (830 líneas, Ticket 004 base + Ticket 005 runtime)

**Cambios respecto Ticket 004:**

1. **Nuevos Enums y Dataclasses:**
```python
class PluginStatus: VALID, INVALID_MANIFEST, MISSING_CODE, LOAD_FAILED, DISABLED, ENABLED, LOADED, INSTANTIATED, FAILED
class LifecycleState: CREATED, INITIALIZED, READY, RUNNING, STOPPED, FAILED

@dataclass
class ProviderInstance:
    slug, organization_slug, instance, state, created_at, last_used_at, error, config
    mark_running(), mark_failed(error), mark_stopped()

@dataclass
class LoadedPlugin (extendido):
    instances: List[ProviderInstance]  # runtime instances
    is_loadable -> enabled + manifest.valid + has_code + status in (LOADED, INSTANTIATED) + provider_class
    is_instantiated -> len(instances)>0 and any state != FAILED
```

2. **Métodos runtime nuevos:**

- `create_provider_instance(slug, organization_slug=None, config_override=None) -> (instance, error)`:
  - Verifica plugin existe, enabled, manifest válido, has_code, status != LOAD_FAILED, provider_class existe
  - Merge config: `dict(loaded.config) + config_override`
  - Instancia dinámica: `provider_cls(organization_slug=org_slug, config=instance_config)`
  - Tracking: crea `ProviderInstance(state=INITIALIZED)`, agrega a `loaded.instances`, cambia status a INSTANTIATED, log
  - Catch exception: crea ProviderInstance FAILED con error, retorna (None, str(e)), nunca lanza hacia core

- `get_or_create_instance(slug, org_slug)`:
  - Busca instancia existente no FAILED/STOPPED para misma org, si no existe crea nueva. Evita duplicados.

- `get_instances(slug=None) -> List[ProviderInstance]`, `get_instance(slug, org_slug) -> ProviderInstance`

- Lifecycle control:
  - `mark_running(slug, org_slug)`: state RUNNING + last_used_at
  - `mark_failed(slug, error, org_slug)`: state FAILED + error
  - `shutdown_instance(slug, org_slug)`: llama close()/shutdown() si existe (con try/except), marca STOPPED
  - `shutdown_all()`: shutdown todas no STOPPED/FAILED, retorna count, log

- `instantiate_all_enabled() -> Dict[slug, (instance, error)]`:
  - Para cada enabled plugin, get_or_create_instance
  - Retorna dict con OK y FAIL, log "5 OK, 0 failed, total 5 enabled"

- `validate_runtime() -> Dict`:
  - Validación completa Ticket 005:
    - discovery: count >=1
    - validation: invalid count
    - loading: enabled, loadable
    - runtime: instantiated, failed, isolated (instantiated>0)
    - enable_disable: disabled_ignored (openai, leonardo, filmfreeway, pika no en enabled), enabled_respected (5 enabled)
    - no_manual_imports: AST parse de core/, jobs/, cli/ buscando `from plugins.<specific>` donde specific en lista plugins conocidos, excluyendo registry y base. Retorna OK si 0 encontrados.
    - overall_ok = todas OK

3. **Reload con shutdown:**
```python
def reload(self):
    self.shutdown_all() # evita leaks
    self._scanned=False; self._discovered=[]; self._loaded=[]
    config.reload()
    return self.load_all()
```

**Sin imports manuales - Garantizado:**

- Todo resuelto dinámicamente vía `importlib.util.spec_from_file_location(f"plugins.{slug}.plugin", plugin_py)`
- Búsqueda de clase Provider por convención: clase terminada en Provider o con métodos fetch+extract+normalize
- Verificación: AST parse de todos los .py en core/, jobs/, cli/ buscando `ImportFrom` con `module.startswith("plugins.")` y submodulo en lista plugins específicos. Resultado: 0 encontrados. Antes con grep naive daba falsos positivos por comentarios que contenían "from plugins.".
- No existe `from plugins.runway import ...` en ningún archivo core/jobs/cli

### Tests: `tests/unit/test_plugin_loader_runtime.py` - 9 tests, todos OK

1. **discovery automática:** 9 plugins desde filesystem, sin lista manual, folder existe

2. **validar manifest:** 9 válidos, 0 inválidos, provider_type en allowed, slug presente

3. **cargar Provider dinámicamente (sin import manual):**
   - 5 clases cargadas vía importlib, cada con fetch, extract, normalize
   - AST check 0 manual imports tipo `from plugins.runway`

4. **instanciar Provider:**
   - `create_provider_instance("posterheroes", "posterheroes")` -> instancia OK, organization_slug == posterheroes, lifecycle INITIALIZED
   - `runway` también OK

5. **controlar lifecycle:**
   - CREATED/INITIALIZED -> `mark_running()` -> RUNNING + last_used_at -> `shutdown_instance()` -> STOPPED
   - `shutdown_all()` cuenta instancias y no crashea

6. **enable/disable respetando YML:**
   - Enabled: runway, posterheroes, adobe, itsnicethat, ai-film-festival (5)
   - Disabled ignorados: openai, leonardo, filmfreeway, pika (4) no en enabled set
   - Intentar instanciar disabled (openai) -> instance None, error contains "disabled"

7. **prioridades:**
   - `load_all()` ordena por priority desc
   - `get_jobs()` ordenado por priority desc dentro mismo schedule (daily)
   - runway=10, adobe=9 verificado

8. **registrar errores sin detener sistema (aislamiento):**
   - Temp dir con 3 plugins: good (OK), fail_init (RuntimeError en __init__), broken (SyntaxError)
   - Config habilita los 3
   - discover 3, load_all: good LOADED, broken LOAD_FAILED, fail_init LOADED (clase carga pero __init__ fallará)
   - `instantiate_all_enabled()`: good OK, fail_init FAIL con "Simulated init failure", broken FAIL
   - Good sigue funcionando (1 instancia no FAILED), sistema no detenido, shutdown_all no crashea

9. **validaciones ticket (doctor, registry, loader, habilitados, deshabilitados, ningún plugin rompe, no manual imports):**
   - Registry: 9 plugins
   - Loader: discovered 9, enabled 5, loadable 5
   - Habilitados cargan: 5 instantiated OK
   - Deshabilitados ignorados: 4 ignorados OK
   - 0 manual imports
   - Aislamiento OK

### Validación requerida por Ticket 005

```
=== DOCTOR ===
Plugins:Discovered OK 9 discovered from filesystem (Plugin Loader real, dynamic)
Plugins:Valid OK 9 valid, 0 invalid manifests
Plugins:Enabled OK 5 enabled via config.yaml (respeta enable YML)
Plugins:Loadable OK 5 loadable
RESULT: OK (with WARN expected playwright optional)

=== REGISTRY ===
Registry OK: 9 plugins
['adobe', 'ai-film-festival', 'filmfreeway', 'itsnicethat', 'leonardo', 'openai', 'pika', 'posterheroes', 'runway']

=== LOADER ===
Loader OK: discovered=9 enabled=5 loadable=5

=== RUNTIME INSTANTIATION ===
posterheroes: OK instantiated
runway: OK instantiated
adobe: OK instantiated
ai-film-festival: OK instantiated
itsnicethat: OK instantiated
Total enabled: 5, OK: 5

=== ENABLE/DISABLE ===
Enabled: {'adobe', 'runway', 'ai-film-festival', 'itsnicethat', 'posterheroes'}
openai ignored: True
leonardo ignored: True
filmfreeway ignored: True
pika ignored: True

=== NO MANUAL IMPORTS ===
Forbidden manual imports: []
No manual imports: True

=== PRIORITIES ===
posterheroes: priority=10 schedule=daily
runway: priority=10 schedule=daily
adobe: priority=9 schedule=daily
ai-film-festival: priority=8 schedule=daily
itsnicethat: priority=5 schedule=daily
Priorities sorted desc: True
```

Todos los criterios del ticket OK:

- [x] doctor OK
- [x] registry OK (9)
- [x] loader OK (9 discovered, 5 enabled, 5 loadable)
- [x] plugins habilitados cargan (5 instantiated OK, sin import manual, vía importlib)
- [x] plugins deshabilitados ignorados (4 ignorados)
- [x] ningún plugin rompe sistema completo (aislamiento probado con 1 bueno + 2 rotos, good sigue OK)

### CLI y Doctor actualizados

- `python -m radar doctor` ahora muestra runtime: PluginLoader OK, Scheduler:jobs OK 5 jobs from loader
- `python -m radar plugins` -> 9 discovered dynamic, 5 enabled, 5 loadable, status LOADED/INSTANTIATED
- `python -m radar plugins --enabled` -> 5 respetando YML
- `python -m radar schedule` -> DAILY 5 jobs priority orden + SYSTEM JOBS discover/monitoring

## Criterios de aceptación Ticket 005

- [x] descubrir plugins automáticamente (scan recorre plugins/ sin lista manual)
- [x] validar manifest (required fields, slug==folder, provider_type, opportunity_types)
- [x] cargar Provider dinámicamente (importlib, sin from plugins.runway)
- [x] instanciar Provider (create_provider_instance con org_slug, config, lifecycle tracking)
- [x] controlar lifecycle (CREATED->INITIALIZED->RUNNING->STOPPED->FAILED, mark_running, shutdown_instance, shutdown_all)
- [x] soportar enable/disable (config.yaml plugins.<slug>.enabled, por defecto DISABLED seguro)
- [x] soportar prioridades (orden desc por priority, schedule grouping)
- [x] registrar errores sin detener sistema (try/except en yaml parse, exec_module, __init__, instancia FAILED pero otros siguen, log traceback)
- [x] ningún import manual tipo from plugins.runway import ... (AST check 0 encontrados)
- [x] Validación doctor OK, registry OK, loader OK, habilitados cargan, deshabilitados ignorados, ningún plugin rompe sistema
- [x] Detenerse aquí para validar antes de siguiente (no se implementó Ticket 006)

## Archivos modificados/creados

- `core/plugin_loader.py` (830 líneas, Runtime v2): Added ProviderInstance, LifecycleState, INSTANTIATED/FAILED status, create_provider_instance, get_or_create_instance, get_instances, get_instance, mark_running, mark_failed, shutdown_instance, shutdown_all, instantiate_all_enabled, validate_runtime, reload con shutdown
- `tests/unit/test_plugin_loader_runtime.py` (9 tests): discovery automática, validar manifest, cargar dinámicamente sin manual imports, instanciar, lifecycle, enable/disable, prioridades, registrar errores sin detener, validaciones ticket
- `scripts/TICKET_005_REPORT.md` (este archivo)
- `CURRENT_TICKET_STATUS.json` actualizado a TICKET 005 implemented_waiting_validation

## Próximos pasos (esperando validación HERMES)

**Detenerse aquí según plan.** No comenzar Ticket 006 hasta validación HERMES.

Cuando HERMES valide OK, siguiente sugerido (según backlog):

- Ticket 006: `core/history.py` Change Tracker + `watchlist`/`notifications` base sin scoring
- O Ticket 006: Scraper Posterheroes real usando Provider runtime + Fingerprint

Pero esperar validación HERMES.

## Decisiones de arquitectura

1. **Runtime como extensión de Loader, no nuevo archivo:** Evita duplicación. Loader ya tenía discovery/validation/loading, agregar instantiation y lifecycle mantiene boundary único core<->plugins.

2. **ProviderInstance con lifecycle tracking:** Permite a scheduler saber si instancia está RUNNING, FAILED, STOPPED, last_used_at para health checks futuros. Preparado para multi-org por plugin (un plugin puede servir múltiples orgs).

3. **Instanciación con organization_slug param:** Cada Provider espera (organization_slug, config) según core/provider.py. Org slug por defecto = plugin slug (runway plugin sirve org runway), pero permite override para plugins genéricos (ej. aggregator itsnicethat podría instanciar para múltiples orgs).

4. **Aislamiento total:** Cada fase (yaml parse, exec_module, class load, __init__) con try/except + logger.error + traceback, retorna error sin throw. Sistema sigue aunque 2 de 3 plugins fallen.

5. **No manual imports verificado vía AST:** Grep naive daba falsos positivos por comentarios que contenían "from plugins.". AST parse de ImportFrom nodes es preciso y evita falsos positivos.

## Resultado

Al finalizar Ticket 005, Radar dispone de verdadero cargador runtime:

- `python -m radar plugins --enabled` -> 5 plugins
- `loader.instantiate_all_enabled()` -> 5 instancias OK, cada con lifecycle INITIALIZED
- `loader.get_instance("runway", "runway").instance.fetch(url)` -> listo para usar en monitoring job
- Si `plugins/broken` tiene syntax error, loader marca LOAD_FAILED pero `runway` sigue funcionando
- Config `plugins.openai.enabled=false` -> ignorado, no instancia, no job

Base sólida para Ticket 006 (history tracker) y Ticket 007+ (scrapers reales).

---

*Ticket 005 completado - Esperando validación HERMES antes de continuar*
*Detenerse aquí según plan ejecución*
