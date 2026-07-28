# TICKET 007 - REPORT: Opportunity History

**Estado:** COMPLETADO - Esperando validación antes de continuar
**Fecha:** 2026-07-27
**Objetivo:** Construir sistema de historial que conserve primera aparición, última aparición, cambios de deadline, URL, estado, descripción, nunca perder historial, registrar cada modificación como evento

## Resumen Ejecutivo

Se implementó `core/opportunity_history.py` como sistema de historial completo que nunca pierde eventos, más hardening de Ticket 006 (transacción atómica crítica) y tests que simulan cambios reales.

Cada oportunidad conserva:
- **Primera aparición:** `first_seen_at` seteado en INSERT, nunca actualizado, evento `created` en `opportunity_history`
- **Última aparición:** `last_seen_at` actualizado cada vez que se ve la oportunidad, incluso sin cambios
- **Cambios de deadline:** eventos `deadline_extended` / `deadline_shortened` con old/new
- **Cambios de URL:** `official_link` y `alternate_links` (agregadas), evento `info_updated` y lista `alternate_links_json` preservada (limite 20, idempotente)
- **Cambios de estado:** `status_changed` open->closed->open etc
- **Cambios de descripción:** `description_raw` / `description_clean` eventos `info_updated`
- **Nunca perder historial:** Nunca DELETE de opportunities, solo UPDATE status a closed, history permanece. `never_lose_history()` verifica al menos evento created. FK ON DELETE CASCADE en schema pero no usamos DELETE en código, documentado.
- **Cada modificación como evento:** Cada campo cambiado genera fila en `opportunity_history` con field_name, old_value, new_value, change_type, detected_at, source_id, metadata_json

## Implementación

### 1. `core/opportunity_history.py` - Sistema de Historial (250 líneas)

**Campos requeridos Ticket 007:**
```python
HISTORY_REQUIRED_FIELDS = [
    "deadline", "official_link", "alternate_links", "status",
    "description_raw", "description_clean", "title", "awards_text", "economic_value"
]
```

**Dataclass HistoryEvent:**
```python
@dataclass
class HistoryEvent:
    opportunity_id, field_name, old_value, new_value, change_type, detected_at, source_id, metadata
```

**Clase OpportunityHistorySystem:**

- `record_first_appearance(opportunity_id, source_id, metadata) -> id`:
  - Verifica idempotencia: SELECT si ya existe evento change_type='created' para opportunity_id, si existe retorna 0 (no duplicar)
  - INSERT evento created con field_name first_seen, old None, new now, change_type created
  - first_seen_at ya está en opportunities DEFAULT CURRENT_TIMESTAMP, no se actualiza después

- `record_last_appearance(opportunity_id)`:
  - UPDATE last_seen_at=CURRENT_TIMESTAMP, sin evento history (solo timestamp)

- `record_change(opportunity_id, field_name, old, new, change_type, source_id, metadata, conn=None) -> id`:
  - Si change_type no proporcionado, determina via _get_change_type
  - Idempotencia: query último historial mismo opportunity_id y field_name, si old/new iguales skip (evita duplicado crash rerun)
  - Si conn proporcionado, usa esa transacción (para atomicidad), sino crea nueva conexión
  - INSERT y retorna id

- `record_deadline_change()`, `record_url_change(is_alternate)`, `record_status_change()`, `record_description_change()`: wrappers con change_type específico

- `get_history(opportunity_id, field_name=None, limit=100) -> List[Dict]`: SELECT ORDER BY detected_at ASC, id ASC (orden estable incluso si mismo segundo), opcional filtro campo

- `get_first_appearance(opportunity_id) -> {first_seen_at, created_event}`: SELECT first_seen_at de opportunities + evento created de history

- `get_last_appearance(opportunity_id) -> {last_seen_at, last_changed_at}`

- `never_lose_history(opportunity_id) -> bool`: COUNT history >=1 (al menos created), verifica que history permanece aunque status closed

**Nunca perder historial:**
- Código nunca hace DELETE FROM opportunities, solo UPDATE status
- Schema tiene ON DELETE CASCADE en opportunity_history, pero no usamos DELETE, documentado en BACKLOG_TECNICO y en este archivo
- Si se hiciera DELETE por error, perdería history, por eso nunca DELETE, solo soft close

### 2. Hardening Ticket 006 implementado (observaciones aprobadas)

**Transacción atómica por oportunidad (crítica):**

Antes:
```python
# Conexiones separadas, commits separados
db.add_alternate_link() # conn1 commit
db.update_opportunity() # conn2 commit
db.insert_history() # conn3 commit -> si falla, oportunidad actualizada sin historial inconsistencia
```

Ahora en `core/monitoring_engine.py` `_handle_duplicate()`:
```python
with self.db.connect() as conn:  # BEGIN
    # 1. Alternate link idempotente dentro de misma transacción
    cur = conn.execute("SELECT alternate_links_json...")
    if new_url not in existing_links: conn.execute("UPDATE ...")
    
    # 2. Update oportunidad
    conn.execute("UPDATE opportunities SET ... WHERE id=?")
    
    # 3. Insert history con idempotencia check dentro misma transacción
    for change in changes:
        cur = conn.execute("SELECT old_value, new_value FROM opportunity_history WHERE opportunity_id=? AND field_name=? ORDER BY detected_at DESC LIMIT 1")
        if last old==new: skip
        conn.execute("INSERT INTO opportunity_history ...")
    
    # COMMIT automático al salir sin excepción, ROLLBACK automático si excepción
```

- Si falla history después de update, rollback deja DB consistente (oportunidad no actualizada sin historial)
- Si falla alternate_link, rollback

**Idempotencia:**

- alternate_links: solo agrega si no existe y no es official_link
- history: verifica último historial mismo campo/valores, skip si ya existe
- updates: solo si detect_changes encuentra cambios, 2da pasada sin cambios no genera update ni history

**Escalabilidad duplicate approximate:**

- Documentada en código y BACKLOG_TECNICO.md como optimización futura cuando volumen >1k por org
- Actual O(n) OK para 300 objetivo inicial
- Futuro: FTS5, índice deadline bucket, embeddings vector search

### 3. Integración con Monitoring Engine

- `process_opportunity` ya generaba fingerprint y buscaba duplicado exacto + approximate (deadline extendido mismo URL -> update no new)
- Ahora `_handle_duplicate` usa transacción atómica y OpportunityHistorySystem para registrar cambios
- Al insertar nueva oportunidad, también `record_first_appearance` (evento created) - añadido en monitoring_engine

Actualización en monitoring_engine para first appearance:

```python
# Después de insert_opportunity new_id
history_system.record_first_appearance(new_id, source_id, {"fingerprint": fp.hash})
```

### 4. Tests: `tests/unit/test_opportunity_history.py` - 7 tests, todos OK

1. **primera_y_ultima_aparicion:**
   - Insert opp, record_first_appearance -> evento created, first_seen_at no None, created_event change_type created
   - record_last_appearance -> last_seen_at actualizado, first_seen_at nunca cambia
   - Idempotencia: segunda vez first appearance retorna 0, no duplica evento created

2. **cambios_deadline:**
   - Insert opp deadline 2026-09-15, first appearance
   - Simular cambio 15->30 -> detect_changes deadline_extended, record_deadline_change, history 1 entry field deadline old 15 new 30 change_type extended
   - Simular 30->20 -> deadline_shortened, history 2 entries, ambos tipos existen

3. **cambios_url:**
   - Insert opp old-url, record_first_appearance
   - Cambio official_link old->new -> history 1 entry field official_link
   - Agregar alternate link aggregator.com/url-test via db.add_alternate_link -> verifica alternate_links_json contiene URL
   - Registrar alternate_links evento -> history 1 entry field alternate_links

4. **cambios_estado:**
   - Insert status open, first appearance
   - Cambio open->closed -> history status_changed old open new closed
   - Cambio closed->open (reapertura) -> history 2 entries

5. **cambios_descripcion:**
   - Insert description_raw Old, first appearance
   - Cambio Old->New with more details -> detect_changes description_raw, record_description_change, history 1 entry old/new

6. **nunca_perder_historial:**
   - Insert opp, 4 eventos (created + deadline + status + url)
   - Marcar opp status closed via UPDATE (no DELETE)
   - History permanece mismo count antes/después, never_lose_history True
   - Documenta por qué nunca DELETE (FK CASCADE perdería history)

7. **historial_completo_simulado:**
   - Secuencia realista:
     1. Insert opp deadline 15/09 awards $5000 description Initial
     2. Deadline extendido 15->30/09 + update DB
     3. Premio actualizado $5000->$10000 + update DB
     4. URL agregada alternate aggregator.com/full + add_alternate_link
     5. Descripción actualizada Initial->Updated with new requirements
     6. Estado cerrado open->closed
   - Verificar historial completo ordenado: >=7 eventos, detected_at ASC, id ASC estable, tipos created, deadline_extended, prize_updated, etc, first_seen preserved, first_seen_at nunca cambia aunque last_changed_at sí

## Validación requerida por Ticket 007

**Simular cambios y verificar historial correcto:**

- **Primera aparición:** first_seen_at seteado en INSERT, evento created en history, idempotencia no duplica, nunca cambia aunque last_seen_at sí
- **Última aparición:** last_seen_at actualizado cada vez que se ve oportunidad, incluso sin cambios, via record_last_appearance o en _handle_duplicate
- **Cambios deadline:** deadline_extended 15->30 y deadline_shortened 30->20 registrados con old/new y change_type correcto, historial por campo deadline
- **Cambios URL:** official_link old->new y alternate_links agregada, historial con field official_link y alternate_links, alternate_links_json preserva lista
- **Cambios estado:** open->closed y closed->open registrados como status_changed
- **Cambios descripción:** description_raw Old->New registrado
- **Nunca perder historial:** history permanece aunque status closed, never_lose_history True, nunca DELETE solo UPDATE status, documentado FK CASCADE riesgo
- **Cada modificación como evento:** cada campo cambiado genera fila opportunity_history con field_name, old_value, new_value, change_type, detected_at, source_id, metadata_json
- **Historial ordenado y completo simulado:** 7 eventos en orden cronológico, first_seen preserved, change_types correctos

**Transacción atómica (hardening Ticket 006):**

- _handle_duplicate ahora BEGIN -> update + history + alternate_links -> COMMIT en una sola conexión
- Si falla history, rollback deja oportunidad no actualizada sin historial inconsistente
- Testeado en test_monitoring_engine con crash simulado y rerun no duplica history ni alternate_links

**Idempotencia:**

- alternate_links solo si no existe
- history verifica último mismo campo/valores skip duplicado
- detect_changes asegura 2da pasada sin cambios no genera update/history

**Escalabilidad duplicate approximate:**

- Documentado en BACKLOG_TECNICO.md como optimización futura cuando >1k por org
- Actual O(n) con 300 objetivo inicial OK, no implementar hasta volumen lo justifique

## Archivos modificados/creados

- `core/opportunity_history.py` (250 líneas): OpportunityHistorySystem con record_first_appearance (idempotente), record_last_appearance, record_change (idempotente con conn opcional para transacción atómica), record_deadline_change, record_url_change, record_status_change, record_description_change, get_history ORDER BY detected_at ASC, id ASC, get_first_appearance, get_last_appearance, never_lose_history
- `core/monitoring_engine.py` (hardening): _handle_duplicate ahora transacción atómica con single connection, idempotencia alternate_links y history, _find_approximate_duplicate lógica estricta (URL igual + title>=0.85 -> duplicate deadline extendido; URL diferente + title>=0.95 + deadline mismo -> duplicate cross-source; evita falsos positivos Test Opp 1 vs 2)
- `core/history.py` (ya existía): HistoryTracker usado por opportunity_history system
- `core/db.py` (ya extendido en Ticket 006): insert_opportunity, update_opportunity, add_alternate_link, insert_history, find_organization_by_slug, etc
- `tests/unit/test_opportunity_history.py` (7 tests): primera/última aparición, deadline, URL, estado, descripción, nunca perder historial, historial completo simulado
- `tests/unit/test_plugin_loader_hardening.py` (3 tests hardening Ticket 005 nota): reload sin leaks, concurrencia, close exception
- `BACKLOG_TECNICO.md` (documenta 3 observaciones hardening Ticket 006: transacción atómica ✅, idempotencia ✅, escalabilidad 📝)
- `scripts/TICKET_007_REPORT.md` (este archivo)
- `CURRENT_TICKET_STATUS.json` actualizado a TICKET 007

## Criterios de aceptación Ticket 007

- [x] primera aparición conservada (first_seen_at nunca cambia, DEFAULT CURRENT_TIMESTAMP en INSERT, no en UPDATE allowed fields, evento created)
- [x] última aparición conservada (last_seen_at actualizado cada vez que se ve oportunidad, incluso sin cambios, en _handle_duplicate y record_last_appearance)
- [x] cambios de deadline registrados (deadline_extended / shortened con old/new, change_type)
- [x] cambios de URL registrados (official_link y alternate_links, alternate_links_json preserva lista, evento history)
- [x] cambios de estado registrados (status_changed open->closed->open)
- [x] cambios de descripción registrados (description_raw, description_clean)
- [x] nunca perder historial (history permanece aunque status closed, nunca DELETE solo UPDATE status, never_lose_history True, FK CASCADE documentado riesgo)
- [x] cada modificación como evento con field, old, new, change_type, detected_at, source_id, metadata
- [x] historial ordenado cronológicamente y completo simulado (7 eventos, detected_at ASC id ASC, first_seen preserved)
- [x] transacción atómica por oportunidad (hardening crítico Ticket 006): BEGIN -> update + history + alternate -> COMMIT, rollback si falla
- [x] idempotencia: alternate_links solo si no existe, history verifica último mismo valores skip, detect_changes asegura 2da pasada sin cambios no genera update
- [x] escalabilidad duplicate approximate documentada como optimización futura cuando volumen >1k
- [x] detenerte aquí y validar completamente antes de continuar (no se implementó Ticket 008)

## Próximos pasos (esperando validación)

Ticket 006 aprobado con observaciones menores, hardening transacción atómica implementado y validado.

Ticket 007 completado con historial que nunca pierde eventos.

A partir de aquí, mayor valor vendrá de incorporar providers/scrapers reales (Posterheroes, Runway) más que seguir ampliando infraestructura core, como sugeriste.

Siguiente sugerido:

- Ticket 008: Scraper Posterheroes real usando Monitoring Engine + Provider runtime + Fingerprint + History
- Ticket 009: Scraper Runway (playwright) validando deduplicación cross-source

Pero detenerse aquí para validación de Ticket 007.

## Decisiones de arquitectura

1. **OpportunityHistorySystem separado de HistoryTracker:** HistoryTracker solo detecta cambios (field, old, new, change_type), OpportunityHistorySystem gestiona persistencia, first/last appearance, idempotencia, transacción. Single responsibility.

2. **first_seen_at nunca cambia:** No está en allowed_fields de update_opportunity, solo se setea en INSERT DEFAULT. Documentado y testeado que permanece igual aunque last_seen_at y last_changed_at cambien.

3. **last_seen_at actualizado siempre:** Incluso si no hay cambios, en _handle_duplicate se actualiza last_seen_at, y record_last_appearance lo hace explícitamente. Permite saber última vez que se vio oportunidad aunque no haya cambiado.

4. **Nunca DELETE, solo UPDATE status:** Para nunca perder historial, nunca hacemos DELETE FROM opportunities. Solo UPDATE status a closed. Si se hiciera DELETE, FK ON DELETE CASCADE borraría history. Documentado en BACKLOG_TECNICO y en código. Si en futuro se necesita hard delete, cambiar FK a SET NULL o soft delete.

5. **Transacción atómica crítica:** Observación 1 Ticket 006. Implementada con single connection en _handle_duplicate. Si falla history después de update, rollback. Evita inconsistencia oportunidad actualizada sin historial.

6. **Idempotencia para crash rerun:** Observación 2 Ticket 006. Implementada con checks: alternate_links solo si no existe, history verifica último mismo campo/valores skip, detect_changes asegura 2da pasada sin cambios no genera nada. Testeado con monitor_all crash simulado y rerun.

7. **Escalabilidad documentada no implementada:** Observación 3 Ticket 006. Actual _find_approximate_duplicate consulta todas oportunidades de org y compara una por una O(n). Con 300 ok, con 30k-500k será cuello de botella. Documentado en código y BACKLOG_TECNICO como optimización futura con FTS5, deadline bucket, embeddings. No implementar hasta volumen lo justifique (premature optimization).

## Resultado

Al finalizar Ticket 007, Radar dispone de sistema de historial que nunca pierde eventos:

- Primera aparición: first_seen_at + evento created
- Última aparición: last_seen_at actualizado cada vez
- Cambios deadline, URL, estado, descripción: cada uno evento en opportunity_history con old/new/change_type/detected_at
- Nunca perder: history permanece aunque status closed, nunca DELETE
- Transacción atómica: update + history + alternate en una transacción
- Idempotente: crash rerun no duplica
- Escalabilidad documentada

Base sólida para scrapers reales.

---

*Ticket 007 completado - Esperando validación antes de continuar*
*Detenerse aquí según plan ejecución - ARENA*
