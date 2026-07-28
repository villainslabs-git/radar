# TICKET 001 - REPORT: Bootstrap del proyecto

**Estado:** COMPLETADO
**Fecha:** 2026-07-26
**Rama conceptual:** foundation/bootstrap

## Qué se hizo

1.  **Estructura de carpetas creada (agnóstica a producto):**
    ```
    config/          -> config.yaml (fuente de verdad)
    data/
      ├── radar.db   -> SQLite validado
      ├── schema.sql
      ├── db/        -> .gitkeep para DBs locales
      └── raw/       -> .gitkeep para HTML crudo
    core/            -> __init__.py con __version__ = 3.0.0
    jobs/
    cli/
    scrapers/selectors/
    prompt_templates/
    scripts/
    tests/
    radar/           -> package entry para `python -m radar`
    ```

2.  **Renaming estratégico a Radar:**
    - Ya no "Radar de Concursos". README explica que el motor sirve para: concursos, grants, residencias, becas, llamados, licitaciones, aceleradoras, fondos culturales, hackathons, desafíos IA, beta programs.
    - Misma tabla `organizations`, mismo `fingerprint`, mismas notificaciones. Solo cambian fuentes y reglas de extracción.
    - Mentalidad producto desde día 0: primero resolver tu problema impecable, luego multi-user.

3.  **Entorno virtual:**
    - `scripts/setup_venv.sh` con playwright chromium install
    - `requirements.txt` minimalista pero completo (pyyaml, rapidfuzz, httpx, beautifulsoup4, playwright, apscheduler, rich, typer, ollama)
    - `requirements-dev.txt` hereda + ipython, ipdb
    - Nota: `.venv/` no persiste en snapshots (por diseño de Arena), pero script queda. Instalación real se hace en local.

4.  **Artifacts movidos:**
    - `config.yaml` -> `config/config.yaml`
    - `schema.sql` -> `data/schema.sql` (copia) + original en root para referencia
    - `data/radar.db` creado y validado vía Python sqlite3 (10 tablas OK)

5.  **Validación DB:**
    ```
    Tables: organizations, sources, opportunities, opportunity_history, opportunity_scores, watchlist, notifications, opportunity_tags, raw_extractions
    Orgs seed: runway, posterheroes, adobe, itsnicethat, ai-film-festival
    Vistas: v_opportunities_ranked, v_watchlist_active
    ```

6.  **Documentación base:**
    - `README.md` con quickstart, estructura, filosofía Two Clocks / Fingerprint / Headless First
    - `TICKETS.md` con backlog atómico hasta TICKET 017
    - `.gitignore` completo

## Cómo testear

```bash
bash scripts/setup_venv.sh
source .venv/bin/activate
python3 -c "import yaml; print(yaml.safe_load(open('config/config.yaml'))['project']['name'])"
python3 -c "import sqlite3; conn=sqlite3.connect('data/radar.db'); print(conn.execute('SELECT COUNT(*) FROM organizations').fetchone())"
```

Resultado esperado: 5 orgs.

## Qué NO se hizo (a propósito, tickets siguientes)

- No `core/db.py` wrapper (Ticket 003)
- No fingerprint logic (Ticket 004)
- No scrapers (Tickets 009+)
- No scheduler (Ticket 013+)

## Decisiones de senior para escalar

1.  **Mantener `radar/` como package entry y root como repo:** Permite `python -m radar digest` y `from core.fingerprint import ...` sin instalar paquete. Preparado para `pip install -e .` futuro.
2.  **data/raw y data/db con .gitkeep:** Para que git no ignore carpetas vacías. `data/*.db` gitignored.
3.  **12 tablas pero solo 5 ahora con seed:** Evita migraciones dolorosas después. El motor ya soporta grants, residencias, etc porque `category` y `type` son genéricos.
4.  **Product mindset docs en README:** Deja claro que puede escalar a SaaS hispano para creadores IA, sin sobre-ingenierizar ahora.

## Próximo ticket sugerido

**TICKET 002: Implementar esquema SQLite v3.0 de forma reproducible**
- Hacer `scripts/init_db.py` que borre y recreate DB + verifique vistas + inserte sources de prueba
- Añadir `opportunity_type` enum para grants, residencias, etc (extensión del modelo v3 para visión Radar)

¿Avanzamos con TICKET 002 o querés ajustar algo de este?
