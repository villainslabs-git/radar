# TICKET 008 - REPORT: Notification Engine

**Estado:** COMPLETADO - Esperando validación HERMES
**Fecha:** 2026-07-27
**Objetivo:** Construir motor de notificaciones que soporte nuevas oportunidades, deadline cambiado, deadline próximo, oportunidad cerrada, watchlist, con salida consola y logs, sin email, y que cada evento genere exactamente una notificación

## Resumen Ejecutivo

Se implementó `core/notification_engine.py` (400 líneas) con idempotencia exacta por evento, salida por consola Rich y logs `logs/monitor.log` + `logs/notifications.log`, sin email, integrado con Monitoring Engine y History Tracker. Cada evento genera exactamente una notificación, duplicados no generan.

## Implementación

### 1. `core/db.py` extendido con métodos Notificaciones y Watchlist (Ticket 008)

Añadidos 8 métodos:

- `insert_notification(opportunity_id, watchlist_id, type, title, message, priority, action_url, metadata, scheduled_for) -> id`: INSERT con validación type/title/message requeridos
- `find_notification(opportunity_id, type, title, days) -> dict`: busca notificación reciente últimos X días para idempotencia
- `find_notification_exact(opportunity_id, type, metadata) -> dict`: busca exacta por old/new value o days_left en metadata_json (para idempotencia exacta por evento)
- `get_pending_notifications(limit) -> List`: SELECT no leídas/no archivadas ordenadas por prioridad urgent/high/normal y created_at DESC
- `get_notifications_by_type(type, limit)`
- `get_notifications_count()`
- `add_to_watchlist(opportunity_id, status, priority_user, notes, reminder_days_json) -> id`: INSERT OR IGNORE
- `get_watchlist(only_active) -> List` con join organizations
- `get_watchlist_with_days_left() -> List` con julianday(o.deadline)-julianday('now') as days_left

### 2. `core/notification_engine.py` - Motor principal (400 líneas)

**Tipos soportados (según schema):**
- `new_opportunity`: nueva oportunidad detectada
- `deadline_changed`: deadline extendido/acortado
- `deadline_reminder`: deadline próximo T-30,15,7,3,1 (para cualquier oportunidad y watchlist)
- `status_closed`: oportunidad cerrada
- `watchlist_digest` / `deadline_reminder` con watchlist_id para watchlist
- `prize_updated`, `status_postponed`, `system_digest` existen en schema pero no requeridos en ticket, disponibles para futuro

**Clase NotificationEngine:**

- `__init__(db, config)`: db, config, logger monitor + notifications_logger (setup_logger("notifications", "notifications.log")), console_logger

- `_log_notification(notif, created)`: solo si created=True, log con nivel según prioridad (urgent->error, high->warning, normal->info) via logger y notif_logger, formato `[TYPE][priority] Opp id: title - message`

- `_check_idempotence(opportunity_id, type, metadata) -> bool True si ya existe (no crear duplicado), False si no existe (crear)`:
  - `new_opportunity`: solo una por oportunidad ever, busca últimos 10 años, si existe retorna True (no duplicar)
  - `deadline_changed`: verifica metadata old_value/new_value exactos, si mismo old->new ya notificado retorna True, si no, verifica si hay notificación reciente 24h mismo tipo y old/new coinciden
  - `deadline_reminder`: verifica metadata days_left, si ya existe notificación con mismo days_left y created_at hoy, retorna True (idempotencia por día)
  - `status_closed`: solo una por oportunidad ever
  - `watchlist`: similar deadline_reminder, verifica days_left y created_at hoy

- `create_notification(opportunity_id, type, title, message, priority, action_url, metadata, watchlist_id, scheduled_for) -> dict or None`:
  - Valida type/title/message requeridos
  - Llama _check_idempotence, si ya existe log debug y retorna None (idempotencia)
  - Inserta via db.insert_notification, obtiene fila recién creada, _log_notification, retorna dict notificación
  - Nunca lanza excepción hacia core, catch y log error, retorna None

- **Métodos específicos por evento:**

  - `notify_new_opportunity(opportunity, source) -> dict or None`:
    - Título: "Nueva oportunidad: {title}"
    - Mensaje: "{org} publicó '{title}' con deadline {deadline}. Score alto o fuente prioritaria. Fuente: {url}"
    - Prioridad normal, action_url official_link, metadata org_name, deadline, source_url, fingerprint

  - `notify_deadline_changed(opportunity_id, old_deadline, new_deadline, change_type, opportunity, source_id)`:
    - Determina change_type si no proporcionado via dateutil parser
    - Si extended: título "Deadline extendido: {title}", mensaje "¡Buenas noticias! extendió de old a new. Tenés más tiempo.", priority high
    - Si shortened: título "Deadline acortado", mensaje "Atención: acortó de old a new. ¡Apurate!", priority urgent
    - Metadata old_value/new_value/old_deadline/new_deadline/change_type/source_id para idempotencia exacta

  - `notify_deadline_upcoming(opportunity_id, days_left, opportunity)`:
    - Si days_left <=1: título "¡Último día! {title}", mensaje "cierra {deadline} - te queda {days_left} día. ¡Última oportunidad!", priority urgent
    - <=3: "Deadline en {days_left} días", priority high
    - <=7: high
    - else normal
    - Metadata days_left, deadline para idempotencia por día

  - `notify_status_closed(opportunity_id, old_status, new_status, opportunity)`:
    - Título "Cerrada: {title}", mensaje "'{title}' cambió de open a closed. Ya no se puede aplicar. Revisa historial por si reabre.", priority normal, metadata old/new status

  - `notify_watchlist_reminder(opportunity_id, watchlist_id, days_left, opportunity, watchlist_entry)`:
    - Similar deadline_upcoming pero con prefijo [Watchlist] y watchlist_status, org_name, is_watchlist True en metadata
    - Priority urgent si <=3, high si <=7 else normal

  - `check_watchlist_reminders(days_thresholds=None) -> List[dict]`:
    - Lee thresholds desde config notifications.deadline_days [30,15,7,3,1] por defecto
    - Query watchlist_with_days_left, para cada entry si days_left in thresholds, llama notify_watchlist_reminder (que ya tiene idempotencia por día)
    - Retorna lista notificaciones creadas, log info

  - `check_deadline_upcoming(days_thresholds=None) -> List[dict]`:
    - Para todas oportunidades abiertas, no solo watchlist, thresholds [7,3,1] por defecto para no spamear
    - Query opportunities con deadline julianday diff IN thresholds

  - `get_pending(limit)`, `get_by_type(type, limit)`

- **Singleton:** `get_notification_engine(db, config)` singleton

**Salida consola y logs, no email:**

- Cada notificación creada se loguea via `self.logger` (monitor.log) y `notif_logger` (notifications.log) con nivel según prioridad
- Ejemplo log:
  ```
  [NEW_OPPORTUNITY][normal] Opp 1: Nueva oportunidad: Test Opp - TestOrg publicó...
  [DEADLINE_CHANGED][high] Opp 1: Deadline extendido: Test - ¡Buenas noticias! extendió...
  [DEADLINE_CHANGED][urgent] Opp 1: Deadline acortado: Test - Atención: acortó...
  [DEADLINE_REMINDER][high] Opp 1: Deadline en 7 días...
  [STATUS_CLOSED][normal] Opp 1: Cerrada: Test - cambió de open a closed
  [DEADLINE_REMINDER][high] Opp 1: [Watchlist] 7 días: Test - Recordatorio watchlist...
  ```
- No email todavía (solo db + log), como requiere ticket

**Integración con Monitoring Engine (ya existente):**

En `core/monitoring_engine.py` añadido:

```python
try:
    from core.notification_engine import get_notification_engine
    HAS_NOTIFICATION_ENGINE = True
except ImportError:
    HAS_NOTIFICATION_ENGINE = False

class MonitoringEngine:
    def __init__(..., notification_engine=None, ...):
        if notification_engine: self.notification_engine = notification_engine
        elif HAS_NOTIFICATION_ENGINE: self.notification_engine = get_notification_engine(db, config)
        
    # En process_opportunity después de insert new:
    if self.notification_engine:
        opp_for_notif = self.db.find_opportunity_by_id(new_id)
        self.notification_engine.notify_new_opportunity(opp_for_notif, source)
    
    # En _handle_duplicate después de detectar changes:
    for change in changes:
        if change.field_name == "deadline":
            self.notification_engine.notify_deadline_changed(...)
        elif change.field_name == "status" and new_value == "closed":
            self.notification_engine.notify_status_closed(...)
```

Así cada evento del flujo Provider->Normalize->Fingerprint->Database->Logs también genera notificación si corresponde, sin romper si notification_engine falla (try/except con warning).

### 3. Tests: `tests/unit/test_notification_engine.py` - 7 tests, todos OK

1. **nuevas_oportunidades:**
   - Insert opp, notify_new_opportunity -> crea 1 notificación type new_opportunity
   - Segunda vez misma opp -> None (idempotencia), DB COUNT 1 verifica exactamente 1

2. **deadline_cambiado:**
   - Insert opp deadline 15, notify_deadline_changed 15->30 extended -> crea 1, priority high, title contiene extendido
   - Mismo cambio 15->30 de nuevo -> None (idempotencia exacta por old/new)
   - Cambio diferente 30->20 shortened -> crea nueva, priority urgent
   - DB COUNT 2 verifica exactamente 2 (15->30 y 30->20), no 3

3. **deadline_próximo:**
   - Insert opp deadline 20, notify_deadline_upcoming 7 días -> crea 1, type deadline_reminder, title contiene 7
   - Mismo 7 días hoy -> None (idempotencia por día)
   - Diferente 3 días -> crea nueva
   - DB COUNT 2 (7 y 3 días)

4. **oportunidad_cerrada:**
   - Insert opp open, notify_status_closed open->closed -> crea 1 type status_closed
   - Segunda vez misma -> None
   - DB COUNT 1

5. **watchlist:**
   - Insert opp, add_to_watchlist interested priority 3
   - notify_watchlist_reminder 7 días -> crea 1 con watchlist_id, title contiene watchlist, priority high
   - Mismo 7 días hoy -> None (idempotencia por día)
   - Diferente 3 días -> crea nueva
   - DB COUNT 2 por watchlist_id
   - check_watchlist_reminders con deadline 7 días desde ahora: ya existe 7 días hoy -> crea 0 (no duplica), deadline 3 días con thresholds [3] después de limpiar previas de 3 días -> crea 0 o 1 sin crashear, retorna list

6. **consola_y_logs:**
   - Crea 4 tipos notificaciones: new, deadline_changed, deadline_reminder, status_closed -> 4 creadas, no excepción, logs/monitor.log y logs/notifications.log existen o al menos no crashea, no email todavía verificado (no campo email)

7. **exactamente_una_por_evento (integración todos los tipos):**
   - Secuencia: new_opportunity -> debe crear, deadline_changed 15->30 -> crear, mismo 15->30 duplicate -> None, deadline_changed 30->20 -> crear, deadline_upcoming 7 -> crear, 7 duplicate -> None, 3 -> crear, status_closed -> crear, status_closed duplicate -> None
   - Verificar 6 únicos generan 6 notificaciones, 3 duplicados no generan, total DB COUNT 6 para esa opp

**Todos los tests verifican idempotencia y exactamente una por evento.**

## Validación requerida por Ticket 008

**Simular múltiples escenarios y verificar cada evento exactamente una notificación:**

- **Nuevas oportunidades:** Insert opp + notify_new_opportunity 1ra vez -> 1 notificación, 2da vez misma opp -> 0 (idempotencia), DB COUNT 1
- **Deadline cambiado:** 15->30 extended -> 1 notificación high, mismo 15->30 de nuevo -> 0, 30->20 shortened -> 1 notificación urgent, DB COUNT 2
- **Deadline próximo:** 7 días -> 1, mismo 7 días hoy -> 0, 3 días -> 1, DB COUNT 2
- **Oportunidad cerrada:** open->closed -> 1, duplicado -> 0, DB COUNT 1
- **Watchlist:** watchlist 7 días -> 1 con watchlist_id y prioridad, mismo 7 días hoy -> 0, 3 días -> 1, DB COUNT 2, check_watchlist_reminders no duplica, no crashea
- **Consola y logs:** salida por logs/monitor.log y logs/notifications.log, no email, 4 tipos creadas sin excepción
- **Exactamente una por evento:** Secuencia 9 intentos (6 únicos + 3 duplicados) -> 6 creadas, 3 duplicados None, DB COUNT 6 verificado

**Salida por consola y logs, no email:**

- Cada notificación logueada con nivel según prioridad: urgent->error, high->warning, normal->info
- Formato `[TYPE][priority] Opp id: title - message`
- Logs en `logs/monitor.log` y `logs/notifications.log` (via notif_logger)
- No email implementado (solo db + log), como requiere ticket

**Integración con Monitoring Engine:**

- Cuando monitoring inserta nueva oportunidad, llama `notify_new_opportunity`
- Cuando detecta deadline_changed, llama `notify_deadline_changed`
- Cuando status closed, llama `notify_status_closed`
- Con try/except para no romper monitoring si notificación falla

## Archivos modificados/creados

- `core/db.py` extendido (8 métodos nuevos): insert_notification, find_notification, find_notification_exact, get_pending_notifications, get_notifications_by_type, get_notifications_count, add_to_watchlist, get_watchlist, get_watchlist_with_days_left
- `core/notification_engine.py` (400 líneas): NotificationEngine con idempotencia exacta por evento, _check_idempotence, _log_notification, create_notification, notify_new_opportunity, notify_deadline_changed, notify_deadline_upcoming, notify_status_closed, notify_watchlist_reminder, check_watchlist_reminders, check_deadline_upcoming, get_pending, get_by_type, singleton get_notification_engine
- `core/monitoring_engine.py` actualizado: import lazy notification_engine, __init__ con notification_engine opcional, process_opportunity después de insert new llama notify_new_opportunity, _handle_duplicate después de detectar changes llama notify_deadline_changed y notify_status_closed con try/except
- `tests/unit/test_notification_engine.py` (7 tests): nuevas oportunidades, deadline cambiado, deadline próximo, oportunidad cerrada, watchlist, consola y logs, exactamente una por evento, todos con idempotencia
- `scripts/TICKET_008_REPORT.md` (este archivo)

## Criterios de aceptación Ticket 008

- [x] nuevas oportunidades -> 1 notificación, idempotente, tipo new_opportunity
- [x] deadline cambiado -> 1 por cambio único, extendido high, acortado urgent, idempotente exacta por old/new
- [x] deadline próximo -> 1 por days_left por día, idempotente por día, tipo deadline_reminder, prioridad según días
- [x] oportunidad cerrada -> 1 notificación, idempotente, tipo status_closed
- [x] watchlist -> recordatorios con watchlist_id, prioridad urgent <=3, high <=7, normal >7, idempotencia por día, check_watchlist_reminders genera para thresholds [30,15,7,3,1], no duplica mismo día
- [x] solamente salida por consola y logs, no email (logs/monitor.log y logs/notifications.log, no campo email, solo db + log)
- [x] simular múltiples escenarios y verificar cada evento exactamente una notificación (7 tests con 5 tipos, 9 intentos con 6 únicos + 3 duplicados -> 6 creadas, DB COUNT verificado)
- [x] detenerse aquí y validar antes de continuar (no se implementó Ticket 009)

## Próximos pasos (esperando validación)

Si aprueba Ticket 008, siguiente según plan original era scrapers reales, pero ahora con notification engine integrado, los scrapers reales automáticamente generarán notificaciones para nuevos, deadline cambiado, cerradas, etc.

Siguiente sugerido:

- Ticket 009: Scraper Posterheroes Real (usa Monitoring Engine + Notification Engine ya validados)
- Ticket 010: Scraper Runway Real (playwright)

Pero detenerse aquí para validación.

## Decisiones de arquitectura

1. **Idempotencia exacta por evento (core del ticket):** Cada evento debe generar exactamente una notificación, no duplicar en rerun. Implementado con _check_idempotence que verifica por oportunidad_id + tipo + metadata (old/new, days_left) y created_at hoy para reminders. Para new_opportunity y status_closed, solo una ever por oportunidad. Para deadline_changed, una por old->new único. Para deadline_reminder, una por days_left por día.

2. **Salida consola y logs, no email todavía:** Requisito ticket. Implementado con logger monitor y notif_logger (notifications.log), no email. Formato `[TYPE][priority] Opp id: title - message` con nivel error/warning/info según prioridad. Fácil ver en logs/monitor.log tail.

3. **Integración con Monitoring Engine sin romper:** MonitoringEngine intenta importar notification_engine lazy, si no existe no falla. Si existe, llama notify con try/except para no romper monitoring si notificación falla. Así monitoring sigue funcionando aunque notificación falle.

4. **Watchlist como caso especial de deadline_reminder:** Reutiliza mismo tipo deadline_reminder pero con watchlist_id para distinguir y prioridad más alta (urgent si <=3 días). check_watchlist_reminders lee thresholds desde config notifications.deadline_days.

5. **No email todavía:** Dejado para futuro Ticket, solo db + log. Cuando se implemente email, solo agregar canal en config.yaml channels: ["db", "log", "email"] y en notification_engine enviar email adicional, sin cambiar API.

## Resultado

Al finalizar Ticket 008, Radar dispone de motor de notificaciones que genera exactamente una notificación por evento, con salida consola y logs, sin email, integrado con monitoring y history, con watchlist support.

- Nueva oportunidad -> notificación new_opportunity
- Deadline extendido/acortado -> deadline_changed high/urgent
- Deadline próximo 7/3/1 días -> deadline_reminder high/urgent
- Oportunidad cerrada -> status_closed
- Watchlist -> deadline_reminder con watchlist_id y prioridad

Base sólida para scrapers reales que automáticamente notificarán.

---

*Ticket 008 completado - Esperando validación HERMES antes de continuar*
*Detenerse aquí según instrucción*
