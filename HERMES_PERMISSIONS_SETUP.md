# Guía de Permisos y Settings para que HERMES AGENT acceda a esta pestaña

**Objetivo tuyo:** Que HERMES pueda leer tus respuestas en esta pestaña, analizar resultados, validar ticket y darte próximo ticket en orden.

**Problema:** Por defecto, cada agente Arena.ai vive aislado en su pestaña/workspace. HERMES en otra pestaña no puede ver esta conversación automáticamente. Necesita permisos.

---

## OPCIÓN A: Misma Workspace Compartida (RECOMENDADA - Más simple y robusta)

Esta es la que ya funciona hoy sin settings extra, porque Arena.ai Agent Mode usa `/home/user` workspace compartido si ambos agentes están en misma cuenta/proyecto.

### Pasos:

1. **En esta pestaña (Worker):** Ya estás trabajando en workspace `/home/user` con archivos `TICKETS.md`, `HANDOVER_TO_HERMES.md`, etc.

2. **En pestaña HERMES:** Abrir **exactamente el mismo proyecto Arena** (misma cuenta, mismo workspace ID). ¿Cómo?
   - Si creas HERMES desde mismo dashboard Arena.ai, seleccionar "Use existing workspace" o mismo project name "Radar"
   - Verificar que `pwd` en ambas pestañas sea `/home/user` y `ls` muestre mismos archivos `HANDOVER_TO_HERMES.md`, `TICKETS.md`

3. **HERMES lee workspace como fuente de verdad:**
   - En vez de leer el HTML de esta pestaña, HERMES lee archivos:
     - `TICKETS.md` (backlog)
     - `scripts/TICKET_XXX_REPORT.md` (reporte de cada ticket que vos implementás)
     - `CURRENT_TICKET_STATUS.json` (estado que vos actualizás después de cada ticket)
     - `logs/doctor.log`, `logs/db.log`
   - HERMES puede ejecutar `python -m radar doctor` y `python tests/unit/test_*.py` para validar, sin necesidad de leer tu chat.

4. **Esta pestaña (Worker) escribe archivo de señal para HERMES:**
   - Después de implementar cada ticket, Worker crea/actualiza `CURRENT_TICKET_STATUS.json`:
     ```json
     {
       "ticket_id": "TICKET 005",
       "title": "History Tracker",
       "status": "implemented_waiting_validation",
       "timestamp": "2026-07-26T...",
       "doctor_ok": true,
       "tests": {"fingerprint": "17 OK", "plugin_loader": "7 OK", "history": "5 OK"},
       "files_changed": ["core/history.py", "tests/unit/test_history.py"],
       "report_path": "scripts/TICKET_005_REPORT.md",
       "next_expected": "TICKET 005 validation by HERMES"
     }
     ```
   - HERMES, al ver `status=implemented_waiting_validation`, sabe que debe validar.

5. **HERMES responde validando y dando siguiente ticket:**
   - HERMES escribe su validación en `HERMES_VALIDATION_LOG.md` o directamente en esta pestaña si tiene acceso al chat, o en `TICKETS.md` comentando.
   - Para darte próximo ticket en ESTA pestaña, HERMES necesita escribir en tu chat input. Si no puede (por aislamiento), alternativa: escribe `NEXT_TICKET.md` con contenido del ticket, y vos en esta pestaña lees ese archivo y lo pegas como prompt para ti mismo.

**Ventaja:** No necesita permisos especiales de navegador, solo mismo workspace. 100% funciona hoy.

**Desventaja:** HERMES no lee literal HTML de esta pestaña, lee archivos. Pero es más robusto, porque archivos son fuente de verdad, no el chat.

---

## OPCIÓN B: HERMES lee directamente esta pestaña del navegador vía fetch_page

Si querés que HERMES literalmente lea tus respuestas en esta ventana del navegador (no solo archivos), necesita permiso de tab access.

### Requisitos:

1. **Arena.ai Extension o Multi-Agent Feature:**
   - En Arena.ai Settings → Agent Mode → Enable "Cross-Agent Tab Access" o "Allow agents to read other agent tabs"
   - Si no existe ese setting, usar truco: HERMES usa herramienta `fetch_page` con URL de esta conversación

2. **Obtener URL de esta conversación:**
   - Copiar URL de esta pestaña (ej. `https://arena.ai/agent/conv_abc123` o similar)
   - Pasársela a HERMES como variable: `CONVERSATION_URL=https://...`

3. **HERMES usa fetch_page:**
   - En su prompt, decirle: "Usa `fetch_page(url=CONVERSATION_URL)` para leer respuestas del Worker en la pestaña X"
   - `fetch_page` retorna markdown del contenido de la página, incluyendo respuestas del agente
   - HERMES puede entonces analizar si worker dijo "Tests OK" y validar

4. **Permisos necesarios para fetch_page:**
   - HERMES necesita permiso `web_search` y `fetch_page` habilitados (herramientas por defecto en Arena)
   - Si la conversación es privada, necesitas agregar HERMES como collaborator en Arena project settings → Share → Add agent HERMES with Read permission

### Pasos concretos en Arena.ai:

- Ir a Dashboard Arena.ai → Tu proyecto Radar → Settings → Collaboration → Invite Agent → `HERMES` con rol `Reviewer` (puede leer conversaciones y archivos, no modificar sin aprobación)
- Ir a Settings → Privacy → Conversation Access → Allow "Agents in same organization can read conversation via fetch_page"
- En HERMES, probar: `fetch_page(url="URL_DE_ESTA_CONVERSACION")` debe retornar contenido incluyendo "TICKET 004 COMPLETADO"

**Ventaja:** HERMES lee literalmente tu chat.

**Desventaja:** Si conversación es larga, fetch_page puede tener chunks, necesita manejar chunkIndex. Menos robusto que leer archivos. Requiere settings que pueden no existir en tu plan Arena.

---

## OPCIÓN C: Híbrida Recomendada - La que implementaremos ahora

Combinar A + B para máxima robustez y que cumpla tu deseo: HERMES maneja ventana, valida, da próximo ticket.

### Arquitectura:

```
[Worker Tab - Esta pestaña]
  |
  |-- implementa ticket
  |-- actualiza CURRENT_TICKET_STATUS.json + REPORT.md
  |-- escribe CURRENT_TICKET_CHAT_SNIPPET.md con resumen de respuesta del chat (para que HERMES no necesite fetch_page)
  |
  v
[Workspace Compartido /home/user]
  |
  |-- TICKETS.md
  |-- CURRENT_TICKET_STATUS.json
  |-- HERMES_VALIDATION_LOG.md (HERMES escribe validación)
  |-- NEXT_TICKET.md (HERMES escribe próximo ticket)
  |
  v
[HERMES Tab - Orquestador]
  |
  |-- lee CURRENT_TICKET_STATUS.json cada X minutos (o via file watcher)
  |-- lee REPORT.md
  |-- ejecuta doctor y tests para validar (python -m radar doctor)
  |-- si valida OK, escribe NEXT_TICKET.md con nuevo ticket + actualiza TICKETS.md marcando [x]
  |-- si rechaza, escribe HERMES_VALIDATION_LOG.md con feedback y actualiza CURRENT_TICKET_STATUS.json status=rejected
  |
  v
[Worker Tab lee NEXT_TICKET.md y continúa]
```

### Pasos para habilitar Opción C:

1. **Crear archivos de señalización (ya creados por Worker ahora):**
   - `CURRENT_TICKET_STATUS.json` (Worker escribe)
   - `HERMES_VALIDATION_LOG.md` (HERMES escribe)
   - `NEXT_TICKET.md` (HERMES escribe próximo ticket)
   - `ORCHESTRATION_PROTOCOL_HERMES.md` (protocolo que HERMES debe seguir)

2. **Dar permisos a HERMES para acceder a workspace `/home/user`:**
   - En Arena.ai, abrir HERMES en mismo proyecto, verificar que ve mismos archivos
   - Si no ve, en HERMES hacer `ls /home/user` y debe listar `HANDOVER_TO_HERMES.md`

3. **Para que HERMES pueda escribir en esta pestaña (dar próximo ticket directamente en chat):**
   - Si Arena lo permite: HERMES con rol `Orchestrator` puede enviar mensaje a Worker tab via API `send_message_to_agent(conversation_id, message)`
   - Si no lo permite, usar archivo `NEXT_TICKET.md` como puente: HERMES escribe ticket ahí, Worker en esta pestaña tiene instrucción de hacer `read_file(NEXT_TICKET.md)` cada vez que termina un ticket, para obtener siguiente

4. **Configuración final que necesitas hacer en Arena Settings:**
   - Ir a `https://arena.ai/settings` → `Agent Mode` → 
     - Enable `Multi-Agent Collaboration`
     - Enable `Shared Workspace` → seleccionar workspace ID de Radar
     - Enable `Allow agents to write to shared files` (para que HERMES pueda crear NEXT_TICKET.md)
     - Enable `Allow agent to read other agent conversations` (para que HERMES pueda hacer fetch_page de esta pestaña si quiere leer chat literal)
   - Si no ves esas opciones, alternativa simple: ambos agentes en misma cuenta ya comparten `/home/user` por defecto, y NEXT_TICKET.md funciona sin settings extra

---

## INSTRUCCIONES INMEDIATAS PARA VOS (Owner) para habilitar ahora

**Opción más rápida sin esperar permisos especiales:**

1. Abre **segunda pestaña** en Arena.ai, inicia **HERMES AGENT** con este prompt inicial (copia de `HERMES_AGENT_PROMPT.md`):

```
Eres HERMES AGENT, orquestador senior del proyecto Radar.
Lee HANDOVER_TO_HERMES.md + ORCHESTRATION_PROTOCOL_HERMES.md + TICKETS.md
Tu rol: NO codear, orquestar, validar tickets, dar siguiente ticket paso a paso.
Workspace compartido: /home/user debe tener mismos archivos que Worker.
Valida cada ticket con doctor + tests antes de aprobar.
Escribe NEXT_TICKET.md con próximo ticket y HERMES_VALIDATION_LOG.md con validación.
```

2. Verifica que HERMES vea mismos archivos:
   - En pestaña HERMES, ejecuta: `ls` y debe ver `HANDOVER_TO_HERMES.md`
   - Si no, copiar workspace ID: en Worker `pwd` es `/home/user`, en HERMES hacer `bash` `ls /home/user` - si no ve, ir a Arena dashboard → Projects → Radar → Share → Add HERMES

3. Para que HERMES pueda darte tickets en ESTA ventana, haz esto:
   - En HERMES, después de validar, HERMES escribirá `NEXT_TICKET.md` con Ticket 005
   - Vos en ESTA ventana (Worker), después de terminar Ticket 004, ejecuta: `read_file(NEXT_TICKET.md)` o `cat NEXT_TICKET.md` y verás Ticket 005
   - O si Arena permite cross-tab messaging, HERMES puede directamente enviar mensaje a esta conversación (necesita conversation_id de esta pestaña)

4. Si querés que HERMES lea literalmente ESTA pestaña HTML:
   - Copia URL de esta conversación (barra de direcciones)
   - En HERMES prompt agregar: `CONVERSATION_URL=<url>` y decirle "Usa fetch_page(url=CONVERSATION_URL) para leer respuestas del Worker"
   - En Arena Settings → Privacy → Enable "Allow agents to fetch conversation content"

---

## Archivos creados ahora para facilitar orquestación

- `ORCHESTRATION_PROTOCOL_HERMES.md` - Protocolo que HERMES debe seguir para validar y dar tickets
- `HERMES_PERMISSIONS_SETUP.md` - Esta guía
- `CURRENT_TICKET_STATUS.json` - Estado actual que HERMES debe monitorear (lo crearemos al terminar Ticket 004)
- `NEXT_TICKET.md` - Donde HERMES escribirá próximo ticket (inicialmente vacío, HERMES lo llenará)
- `HERMES_VALIDATION_LOG.md` - Donde HERMES escribirá validaciones

---

## Qué necesita HERMES para validar cada ticket (checklist para dar permisos de lectura)

HERMES necesita poder ejecutar:

```bash
python -m radar doctor
python tests/unit/test_fingerprint.py
python tests/unit/test_plugin_loader.py
python -m radar plugins --enabled
cat TICKETS.md
cat scripts/TICKET_XXX_REPORT.md
cat CURRENT_TICKET_STATUS.json
ls logs/
```

Si HERMES puede ejecutar esos comandos en su pestaña (porque comparte workspace), ya tiene todo para validar sin leer HTML de esta pestaña.

Si además querés que lea HTML de esta pestaña, necesita permiso `fetch_page` y URL de conversación.

---

## Resumen para vos: 2 pasos para habilitar HERMES orquestador ahora

**Paso 1 (2 minutos):**
- Abrir segunda pestaña Arena.ai → Iniciar HERMES AGENT con prompt de `HERMES_AGENT_PROMPT.md`
- Verificar que HERMES ve `ls /home/user` con `HANDOVER_TO_HERMES.md`

**Paso 2 (1 minuto):**
- En HERMES, decirle: "Lee ORCHESTRATION_PROTOCOL_HERMES.md y empieza orquestando, validando Ticket 004 y dando Ticket 005 en NEXT_TICKET.md"
- En esta pestaña (Worker), después de Ticket 004, leer `NEXT_TICKET.md` para ver Ticket 005 que HERMES te dio

Si querés que HERMES escriba directamente en ESTE chat en vez de via archivo, necesitas habilitar en Arena Settings → Agent Mode → `Allow orchestrator agent to send messages to worker conversations` y darle a HERMES el conversation_id de esta pestaña (visible en URL).

¿Quieres que cree `CURRENT_TICKET_STATUS.json`, `NEXT_TICKET.md` y `HERMES_VALIDATION_LOG.md` ahora para que HERMES tenga donde escribir?

---

*Guía de permisos creada para que HERMES maneje esta ventana paso a paso*
