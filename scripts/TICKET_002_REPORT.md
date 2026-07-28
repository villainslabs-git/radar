# TICKET 002 - REPORT: Núcleo Reproducible del Sistema

**Estado:** COMPLETADO
**Fecha:** 2026-07-26
**Definición senior:** "Construir el núcleo reproducible del sistema + radar doctor"

## Qué se hizo (redefinición del ticket por code review senior)

### 1. Cambio de "Radar de Concursos" a "Radar - Opportunity Intelligence Engine"

**Antes:** Motor solo para concursos
**Ahora:** Motor genérico agnóstico que monitorea:
- concursos, grants, residencias, becas, fellowships
- aceleradoras, hackathons, beta programs, challenges
- calls for artists, licitaciones creativas, festivales

Demostrado en:
- `config.yaml` -> `opportunity_types: [contest, grant, residency, fellowship, accelerator, hackathon, beta, festival, call_for_artists, creative_tender, challenge]`
- `plugins/*/manifest.yaml` -> cada plugin declara sus `opportunity_types`
- `core/provider.py` -> `NormalizedOpportunity.opportunity_type` campo genérico

**Consecuencia producto:** Si funciona para vos, mismo motor sirve para SaaS hispano para creadores IA. No atado a dominio concursos.

### 2. Carpeta `plugins/` (punto 1 review)

```
plugins/
├── base.py              # Re-export Provider para plugins
├── registry.py          # Descubre plugins y respeta config.yaml
├── runway/              # contest, grant, beta, festival - playwright
│   ├── manifest.yaml
│   └── plugin.py (RunwayProvider)
├── posterheroes/        # contest, festival - beautifulsoup
├── adobe/               # residency, grant, beta
├── leonardo/            # contest, beta
├── openai/              # grant, residency, beta, accelerator - api futuro
├── itsnicethat/         # aggregator
├── filmfreeway/         # aggregator - playwright
├── ai-film-festival/    # festival, contest
└── pika/                # contest, beta
```

Cada plugin es independiente, con su lógica distinta. No todo en `scrapers/`. Escalable.

### 3. Config gobierna TODO (punto 2 review)

Antes: config.yaml gobernaba scan
Ahora: config.yaml gobierna TODO:

```yaml
plugins:
  runway:
    enabled: true
    schedule: daily
    priority: 10
  openai:
    enabled: false
  # ... 9 plugins

logging:
  level: INFO
  files: {monitor: monitor.log, discover: discover.log, ...}

scoring:
  enabled: false # Senior advice

opportunity_types: [contest, grant, residency...]
```

Para activar/desactivar conector: cambias `enabled: true/false` en yaml, no tocas código.

Validado por `core/config.py` con `is_plugin_enabled()`, `get_plugin_schedule()`, `validate()`.

### 4. Jobs independientes (punto 3 review)

Arquitectura diseñada (no implementada aún, solo estructura + logging):

```
discover (semanal) -> busca nuevas orgs/sources desde seeds
  ↓
monitor (cada 12h) -> visita solo fuentes conocidas, usa Provider.fetch()
  ↓
score (deshabilitado hasta 300 opps) -> calculará relevance/prize/urgency cuando haya data real
  ↓
notify (diario 09:00) -> watchlist T-30,7,3,1 + deadline_changed
```

Cada job loguea a archivo separado: `logs/discover.log`, `logs/monitor.log`, etc. Facilita debugging 3AM.

### 5. Logs desde día 0 (punto 4 review)

```
core/logger.py
  - setup_logger(name, log_file, level)
  - RotatingFileHandler 5MB x 3
  - Formato: timestamp | level | job | message (senior)
  - Factory: get_logger("monitor"), get_logger("discover"), etc

logs/
  monitor.log, discover.log, scheduler.log, doctor.log, db.log, core.log, provider.log
  .gitkeep para persistir carpeta vacía
```

Cero `print()`. Todo `logger.info/warning/error`.

### 6. Provider Interface (punto 5 review) - Desde día 0

```python
# core/provider.py
class Provider(ABC):
  provider_type: str  # playwright, beautifulsoup, rss, api, json, github, mcp...
  fetch(url) -> FetchResult
  extract(fetch_result) -> List[RawOpportunity]
  normalize(raw) -> NormalizedOpportunity
  validate(normalized) -> bool
  run(url) -> List[NormalizedOpportunity] # pipeline completo

# Futuros providers listos sin romper nada:
# RSSProvider, APIProvider, MCPProvider, etc
```

Desacopla sistema de scraping. Job Monitoring solo llama `provider.run(url)`.

### 7. Scoring NO implementado (tu sugerencia clave)

```
scoring:
  enabled: false
  note: "No implementar hasta juntar 300 oportunidades y ver cuáles se presentan"
```

Razón senior: no sabes qué es "buena oportunidad" hasta tener data real. Evitar heurística prematura basada en intuición.

En `radar doctor`: `Scoring OK disabled until 300 opps collected (senior advice)`

### 8. Núcleo reproducible real

**`scripts/init_db.py`:**
- Borra DB si existe (con backup timestamp)
- Ejecuta `data/schema.sql`
- Carga 9 orgs desde `data/seed/organizations.yaml`
- Carga 9 sources desde `data/seed/sources.yaml`
- Valida integridad FK, tablas, conteos
- Logs a `logs/db.log`

**`core/db.py`:**
- Wrapper SQLite con context manager, WAL, foreign_keys ON
- `validate_integrity()` -> dict con tables, counts, fk_check, issues
- Helpers `insert_organization`, `insert_source`, `get_organizations`, `get_sources`

**`core/doctor.py`:**
- Checks: Python 3.10+, deps (yaml, httpx, bs4, rapidfuzz, dateutil, playwright), SQLite, DB file, Tables, FK, Config validation, Plugins, Logs dir, Scheduler
- Salida tipo:

```
Python.............OK        ✓ 3.13.14
Dep:yaml...........OK        ✓ installed
SQLite.............OK        ✓ 3.46.1
Database...........OK        ✓ data/radar.db exists (128 KB)
Table:organizationsOK        ✓ 9 rows
Organizations......OK        ✓ 9
Sources............OK        ✓ 9
Config.............OK        ✓ config/config.yaml
Plugins:Found......OK        ✓ 9 found
Plugins:Enabled....OK        ✓ 5 enabled
Plugin:runway......OK        ✓ enabled, schedule=daily, types=[contest,grant,beta,festival]
Scoring............OK        ✓ disabled until 300 opps collected
Logs:Dir...........OK        ✓ logs exists
Scheduler..........OK        ✓ APScheduler available
RESULT: All systems OK
```

**`cli/main.py` (Typer + Rich):**
```
python -m radar doctor   -> diagnóstico integral
python -m radar init-db  -> recreation reproducible
python -m radar stats    -> tablas + plugins enabled + counts
python -m radar digest   -> Headless MVP "Hay 3 nuevas..."
python -m radar monitor  -> placeholder hasta Ticket 013
python -m radar discover -> placeholder hasta Ticket 014
```

## Validación

```bash
$ python scripts/init_db.py
[INIT_DB] OK
  DB: data/radar.db
  Organizations: 9
  Sources: 9
  Tables: 10 tables
  FK check: OK

$ python -m radar doctor
RESULT: All systems OK

$ python -m radar stats
Plugins Found 9, Enabled 5, Scoring DISABLED
```

## Qué NO se hizo (a propósito)

- No scoring.py (esperar 300 opps)
- No scrapers reales (Tickets 010+)
- No jobs monitor/discover/notify reales (Tickets 013+)
- No fingerprint.py (Ticket 004) - aunque provider ya está listo para usarlo

## Decisión de arquitectura para escalar a producto

1.  **Opportunity Intelligence Engine**: El cambio de nombre no es marketing. Cambia cómo modelas datos. `opportunity_type` genérico permite que mañana una empresa pague por "solo becas de AI" filtrando por type.
2.  **Plugins como boundary**: Si en 6 meses abrís a otros usuarios, cada usuario puede tener `plugins.custom_org` con su propio manifest sin tocar core.
3.  **Doctor como onboarding**: Cuando otra persona instale Radar, `radar doctor` le dice exactamente qué falta (Playwright, DB, etc). Ahorra horas de soporte.
4.  **Logs separados por job**: Cuando tengas 20 plugins corriendo, si falla solo `monitor.log` sabes que no es `discover`.

## Próximo ticket sugerido (según backlog original)

**TICKET 003: `core/db.py` mejorado + tests**
O **TICKET 004: `core/fingerprint.py`** (ya tenemos provider, podemos hacer deduplicación antes de scrapers para que cuando lleguen 300 opps no haya duplicados)

Vos decís como senior cuál sigue.
