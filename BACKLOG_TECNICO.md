# Backlog Técnico - Hardening y Optimizaciones Futuras

**Origen:** Observaciones Ticket 006 aprobado con observaciones menores y Ticket 005 hardening

---

## 1. Transacción Atómica por Oportunidad (CRÍTICA - Implementada en Ticket 006 hardening)

**Problema original (Ticket 006):**
Flujo anterior:
```
Fingerprint
↓
insert opportunity
↓
insert history
↓
alternate links
```
Cada paso abría conexión separada con commit independiente. Si fallaba history después de update, quedaba oportunidad actualizada sin historial correspondiente -> inconsistencia.

**Solución implementada (Ticket 006 hardening):**
En `core/monitoring_engine.py` `_handle_duplicate()` ahora usa **transacción atómica única**:

```python
with self.db.connect() as conn:
    # 1. Alternate link idempotente
    # 2. Update oportunidad
    # 3. Insert history con idempotencia check
    # Commit automático al salir del context manager, rollback automático si excepción
```

- BEGIN implícito al entrar a `connect()`
- Todas operaciones en misma conexión: SELECT alternate_links_json, UPDATE alternate_links_json, UPDATE opportunity, INSERT history
- COMMIT automático al salir sin excepción
- ROLLBACK automático si excepción

**Idempotencia también implementada:**
- alternate_links: solo agrega si no existe y no es official_link
- history: verifica último historial para mismo opportunity_id y field_name, si old/new iguales skip (evita duplicado en crash rerun)
- updates: solo si detect_changes encuentra cambios, 2da pasada sin cambios no genera update ni history

**Validación:**
- Tests `test_monitoring_engine.py` con crash simulado y rerun no duplican history ni alternate_links
- Tests `test_opportunity_history.py` idempotencia primera aparición no duplica evento created

**Estado:** ✅ Implementado en Ticket 006 hardening, tests OK

---

## 2. Idempotencia de monitor_all() (Implementada)

**Problema:**
```
monitor_all()
↓
crash (ej. power failure, OOM)
↓
monitor_all()
```
Podría generar:
- history duplicado (mismo cambio registrado 2 veces)
- alternate_links duplicados (misma URL agregada 2 veces)
- updates repetidos

**Solución implementada:**

- **alternate_links:** `add_alternate_link` verifica si URL ya existe en lista o es official_link, solo agrega si no existe. Idempotente.
- **history:** Antes de insertar, query último historial para mismo opportunity_id y field_name, si old_value y new_value iguales, skip. Evita duplicado en crash rerun.
- **updates:** `detect_changes` compara old vs new, si no hay cambios (segunda pasada con mismos datos), no hay update ni history. Idempotente.

**Tests:**
- `test_registrar_cambios` verifica que 2da vez sin cambios no genera history nuevo
- `test_primera_y_ultima_aparicion` verifica idempotencia evento created
- `test_monitoring_engine` con 2 fuentes, una falla, rerun no duplica

**Estado:** ✅ Implementado, tests OK

**Pendiente menor:** Añadir timestamp check (si último historial <1 hora y mismos valores, skip) ya está con lógica básica de valores iguales, suficiente para v1.

---

## 3. Escalabilidad de duplicate approximate (Documentada, optimización futura)

**Problema actual:**
`_find_approximate_duplicate()` en `monitoring_engine.py`:
```python
cur = conn.execute("SELECT * FROM opportunities WHERE organization_id=? AND is_duplicate_of IS NULL")
candidates = [dict(r) for r in cur.fetchall()]
for candidate in candidates:
    cand_fp = fingerprint_engine.generate(...)
    title_sim = fingerprint_engine._title_similarity(...)
    if title_sim >= threshold: return candidate
```

- Consulta todas oportunidades de org (ej. 30k, 100k, 500k)
- Para cada una genera fingerprint y calcula RapidFuzz ratio
- O(n) por oportunidad nueva, O(n²) para batch

**Con 300 oportunidades:** OK, <100ms

**Con 30k-500k:** Cuello de botella, puede tardar segundos por oportunidad, batch de 25 sources con 10 opps cada uno = 250 opps * 30k comparaciones = 7.5M comparaciones -> lento

**Solución futura (no implementar ahora, documentar):**

Optimizar approximate duplicate mediante índice/candidatos cuando volumen lo justifique (observación Ticket 006):

- **Fase 1 (cuando >1k opps por org):** Filtrar candidatos por deadline bucket (mismo mes/año) o por primera letra título, reduce de 30k a ~500 candidatos
- **Fase 2 (cuando >10k):** Índice trigram o full-text search SQLite FTS5 para título, buscar candidatos con LIKE o FTS antes de RapidFuzz
- **Fase 3 (cuando >100k):** Embeddings + vector search (Qdrant, Chroma) para similitud semántica, híbrido con fingerprint exact
- **Fase 4 (cuando >500k):** Pre-filtrado por organization_id + deadline ±15 días + category, luego RapidFuzz solo en candidatos

**No merece adelantarse ahora:** Con 300 opps objetivo inicial, O(n) es suficiente. Dejar documentado.

**Documentado en código:**
```python
def _find_approximate_duplicate(...):
    """
    ...
    Escalabilidad (observación 3): consulta todas oportunidades de org y compara una por una.
    Con 300 ok, con 30k-500k será cuello de botella. Documentado como optimización futura vía índice/candidatos.
    """
```

**Estado:** 📝 Documentado como optimización futura, no implementar hasta que volumen lo justifique. Para Ticket 007 con <100 opps, actual O(n) OK.

---

## 4. Hardening adicional Ticket 005 (Implementado)

**Nota aprobación Ticket 005:**
- reload repetido sin leaks de módulos
- concurrencia en get_or_create_instance
- excepción dentro de Provider.close()

**Implementado en `tests/unit/test_plugin_loader_hardening.py`:**
- 5 reloads seguidos, discovered 9, loaded 9, instances limpiadas, módulos plugins <20 no leak
- 10 threads concurrentes get_or_create_instance misma org, 0 crashes, al menos 1 instancia válida
- Provider con close() que lanza RuntimeError, shutdown_instance no crashea, marca STOPPED, shutdown_all OK

**Estado:** ✅ Implementado, 3 tests OK

---

## Resumen Backlog Técnico

| Item | Prioridad | Estado | Ticket |
|------|-----------|--------|--------|
| Transacción atómica por oportunidad | CRÍTICA | ✅ Implementado | 006 hardening |
| Idempotencia monitor_all crash rerun | Alta | ✅ Implementado | 006 hardening |
| Escalabilidad duplicate approximate | Media | 📝 Documentado, optimizar cuando >1k opps | Futuro |
| Reload sin leaks | Media | ✅ Implementado | 005 hardening |
| Concurrencia get_or_create_instance | Media | ✅ Implementado | 005 hardening |
| Excepción Provider.close() aislada | Alta | ✅ Implementado | 005 hardening |

**Próximos hardening sugeridos para futuro (no bloqueantes):**
- Transacción atómica también para insert new opportunity + first appearance history (actualmente insert + first appearance son 2 transacciones separadas, podría unificarse)
- Índice en opportunities(organization_id, fingerprint_hash) ya existe UNIQUE, pero agregar índice en (organization_id, deadline) para accelerate approximate duplicate filtering
- Métricas persistidas en DB para dashboard histórico, no solo logs
