# Protocolo de Orquestación - HERMES como Supervisor, Este Agente como Worker

**Objetivo:** HERMES maneja esta ventana de agente paso a paso, validando cada ticket antes de continuar.

**Rol HERMES:** Tech Lead / QA - No codea, orquesta, valida, da siguiente ticket
**Rol Worker (este agente):** Implementa solo el ticket que HERMES da, entrega prueba

---

## Flujo de Orquestación por Ticket

```
HERMES: Lee TICKETS.md + HANDOVER_TO_HERMES.md + último reporte
  ↓
HERMES: Genera Ticket 00X con criterios de aceptación claros
  ↓
HERMES: Pega ticket en ESTA ventana (este chat) - Formato:
  "TICKET 005 - Título
   Objetivo: ...
   Criterios aceptación: ...
   No hacer: ..."
  ↓
Worker: Implementa SOLO ese ticket, sin agregar extras
  ↓
Worker: Actualiza archivos, crea scripts/TICKET_XXX_REPORT.md, corre validaciones:
  python -m radar doctor
  python tests/unit/test_*.py
  python -m radar plugins
  ↓
Worker: Responde en ESTE chat con resumen + archivos modificados + validación
  ↓
HERMES: LEE respuesta de worker en esta pestaña (necesita permisos para acceder a tab)
  + LEE archivos del workspace (fuente de verdad): TICKETS.md, REPORT, radar doctor output
  + VALIDA contra criterios aceptación del ticket
  ↓
HERMES: Si APRUEBA → marca [x] en TICKETS.md, archiva reporte, da TICKET 00X+1
        Si RECHAZA → da feedback específico: "Falla X, corregir Y, no tocar Z"
  ↓
Worker: Solo continúa cuando HERMES aprueba
```

---

## Qué debe validar HERMES por cada ticket (checklist)

Para cada ticket, HERMES debe verificar antes de aprobar:

**1. Scope respetado:**
- [ ] Worker implementó solo lo pedido en ticket, no agregó scoring ni frontend ni extras
- [ ] No rompió tickets anteriores (fingerprint, plugin_loader siguen OK)

**2. Core agnóstico:**
- [ ] Ninguna regla específica de org (runway, posterheroes) en core/
- [ ] Toda lógica org en plugins/<slug>/

**3. Config gobierna TODO:**
- [ ] Nuevo parámetro en config/config.yaml, no hardcodeado
- [ ] Enable por YML respetado

**4. Tests y Doctor:**
- [ ] `python -m radar doctor` → RESULT: OK (WARN playwright optional permitido)
- [ ] `python tests/unit/test_fingerprint.py` → 17 OK (si ticket toca fingerprint)
- [ ] `python tests/unit/test_plugin_loader.py` → 7 OK (si toca loader)
- [ ] Nuevo test del ticket pasa (ej. test_history.py)
- [ ] `python -m radar plugins` → 9 discovered, 5 enabled, 5 loadable (o más si nuevo plugin)

**5. Logs no prints:**
- [ ] Usa `get_logger("monitor")` etc, no print() en core/jobs

**6. Documentación:**
- [ ] Actualizó TICKETS.md marcando [x]
- [ ] Creó scripts/TICKET_XXX_REPORT.md con qué hizo, validación, decisiones
- [ ] API estable si aplica (ej. fingerprint generate/compare/is_duplicate no cambia firma)

**7. Arquitectura ordenada:**
- [ ] Loader como boundary, no lista manual plugins en core
- [ ] Jobs independientes si aplica

Si algún check falla → RECHAZAR con feedback preciso, no dar siguiente ticket.

---

## Archivos que HERMES debe monitorear como fuente de verdad

**Primario (workspace compartido):**
- `TICKETS.md` - Backlog y estado [x] / [ ]
- `scripts/TICKET_XXX_REPORT.md` - Reporte de cada ticket implementado
- `HANDOVER_TO_HERMES.md` - Contexto completo 29KB
- `config/config.yaml` - Fuente verdad plugins enabled/schedule
- `data/radar.db` - DB (via python -m radar stats)
- `logs/*.log` - Logs por job

**Secundario (esta pestaña del navegador):**
- Respuestas del worker en este chat (resumen + validación)
- Último doctor output pegado por worker

**Recomendación:** HERMES lea SIEMPRE workspace files como fuente de verdad principal, y use esta pestaña como log de conversación del worker. No confiar solo en texto del chat, validar con `radar doctor` y tests leyendo archivos.

---

## Formato de Ticket que HERMES debe dar (para que worker no se desvíe)

```
TICKET 00X - Título Corto

Objetivo: 1 párrafo claro qué debe lograr este ticket, sin ambigüedad

Contexto: De qué tickets anteriores depende, qué archivos relevantes leer

Tareas específicas:
- [ ] Tarea 1 concreta (ej. crear core/history.py con función track_changes)
- [ ] Tarea 2 (ej. validar que detecta deadline_extended)
- [ ] etc, máximo 5-6 tareas

Criterios de aceptación:
- [ ] Criterio 1 verificable (ej. python tests/unit/test_history.py pasa 5 tests)
- [ ] Criterio 2 (ej. radar doctor sigue OK)
- [ ] etc

No hacer en este ticket:
- Lista explícita de lo que NO debe tocar (ej. no implementar scoring, no tocar scrapers)

Entregables esperados:
- Archivos modificados/creados
- Reporte en scripts/TICKET_XXX_REPORT.md
- Comandos validación

```

HERMES debe ser muy específico, como senior dando ticket a junior.

---

## Cómo HERMES debe dar siguiente ticket solo si aprueba

**Si APRUEBA:**
```
TICKET 00X APROBADO ✅

Validación:
- Doctor: OK
- Tests: 7 OK
- Criterios: todos OK
- Core agnóstico: OK

Siguiente: TICKET 00Y - Título
Objetivo: ...
```

**Si RECHAZA:**
```
TICKET 00X RECHAZADO ❌

Fallos encontrados:
- [ ] Doctor FAIL: Table:opportunities missing fingerprint_hash -> schema no aplicado, correr init_db.py
- [ ] Test falla: test_history.py test_deadline_extended expected notification but got None
- [ ] Core contaminación: core/history.py contiene if org == "runway" -> mover a plugins/runway/

Acción: Corregir solo esos puntos, no agregar nuevo código, re-ejecutar validaciones y responder con corrección
No daré TICKET 00Y hasta que este sea aprobado
```

---

## Comunicación entre HERMES y Worker via esta pestaña

Worker solo responde en este chat. HERMES debe leer esta pestaña.

Opciones técnicas para permisos (ver HERMES_PERMISSIONS_SETUP.md):
- Opción A: Misma workspace Arena.ai compartida (HERMES y Worker ven mismos archivos /home/user)
- Opción B: HERMES usa fetch_page para leer URL de esta conversación
- Opción C: Extensión Arena que permite agent-to-agent tab access

Recomendado: Opción A + archivo CURRENT_TICKET_STATUS.json que worker actualiza y HERMES lee

Worker creará después de cada ticket:
- `CURRENT_TICKET_STATUS.json` con {ticket_id, status: implemented/waiting_validation, doctor_ok, tests_ok, files_changed}

HERMES lee ese JSON como señal.

---

## Orden sugerido de tickets restantes (para HERMES orquestar)

Basado en TICKETS.md y senior advice (scoring NO hasta 300 opps):

- TICKET 005: `core/history.py` - Change Tracker (detecta deadline_extended, prize_updated, status_changed) + `opportunity_history` tabla
- TICKET 006: `core/db.py` mejorado + `watchlist` + `notifications` base sin scoring
- TICKET 007: Primer scraper real Posterheroes usando Provider + FingerprintEngine + Loader
- TICKET 008: Scraper Runway (playwright) validando deduplicación cross-source
- TICKET 009: `jobs/monitoring.py` El Vigilante con selector priority y loader.get_loadable_plugins()
- etc hasta 017

Pero HERMES decide orden final validando cada uno.

---

*Protocolo creado para que HERMES orqueste esta ventana paso a paso, validando cada ticket antes de continuar*
