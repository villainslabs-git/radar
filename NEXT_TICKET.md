# NEXT_TICKET - TICKET 011 - Scraper Runway Real - Validación cross-source

**Estado actual:** Núcleo cerrado formalmente + Primer provider real Posterheroes validado ✅

**Infraestructura completa:**
- Plugin Loader ✅ Runtime ✅ Monitoring ✅ History ✅ Notification ✅ Fingerprint ✅ Deduplicación ✅ Database ✅ Scheduler ✅ Logs ✅ Métricas ✅ Idempotencia ✅
- 69 tests OK (17 fingerprint + 7 loader + 3 hardening + 9 runtime + 6 monitoring + 7 history + 7 notification + 6 scheduler + 7 posterheroes fixture)
- Doctor OK
- Primer provider real Posterheroes 15 - Still Human extraído real 1 opp, deduplicación OK, persistencia OK, logs OK, notificaciones OK, sin excepciones core

**Fase anterior:** Tickets 001-010 aprobados, núcleo arquitectónicamente completo, arquitectura validada con caso real sin excepciones en core

**Nueva fase:** Fase 2 – Providers Reales - Prueba de arquitectura superada, ahora ampliar cobertura y calidad

## TICKET 011 - Scraper Runway Real (playwright) - Validación cross-source

**Objetivo:** Segundo scraper real usando pipeline ya validado, validando deduplicación cross-source misma oportunidad en runway oficial + itsnicethat aggregator -> 1 registro alternate_links + notificación

**Debe:**
- plugins/runway/plugin.py real playwright (requiere JS): fetch https://runwayml.com/ai-film-festival y https://runwayml.com/blog con playwright (ya en requirements), extract BeautifulSoup con selectors reales, normalize dateparser, flujo Provider->Normalize->Fingerprint->Database->Logs ya validado, registrar cambios history, producir métricas y notificaciones, manejar JS rendering, fechas inconsistentes, URLs variables, datos incompletos
- Validar deduplicación cross-source: misma oportunidad aparece en runway oficial y en itsnicethat aggregator que linkea a runway -> debe ser 1 registro en DB con alternate_links_json = ["https://runwayml.com/ai-film-festival", "https://www.itsnicethat.com/news/..."] y fingerprint igual, no 2 registros
- Usar candidate_urls() + fetch_first_success() genérico de Provider base (implementado en Ticket 010 fix 2) para definir lista [ai-film-festival, blog, gen-4, etc] sin tocar base
- economic_value siempre float (fix 1 Ticket 010) para evitar updates falsos
- Tests con fixture HTML: tests/plugins/runway/runway_2026.html con asserts title, deadline, awards, description (como se hizo con posterheroes fixture)
- No scoring, no más managers/engines/capas, no tocar fingerprint/history/loader/monitoring core (usarlos como infraestructura estable), no hardcodear reglas otras orgs

**Validación:**
- [ ] Doctor OK
- [ ] Tests existentes 69 OK no regresión + 1 nuevo provider real posterheroes ya validado
- [ ] python -m radar monitor --batch-size 2 (runway + itsnicethat) con fuentes reales: fetched >=1 (runway), new >=1 insertado DB si no existe, si misma oportunidad en ambas sources -> DB count 1 con alternate_links 2, notif new_opportunity 1, logs monitor.log
- [ ] Segunda ejecución mismas 2 sources: fetched >0, new 0, duplicate_exact o duplicate_approximate >=1 (cross-source), no duplicados DB, alternate_links no duplicado, history no duplicado
- [ ] Simular cambio deadline en HTML mock runway: cambiar deadline y ejecutar monitor de nuevo: debe detectar updated 1, history deadline_extended, notif deadline_changed
- [ ] No manual imports: 0 from plugins.runway import en core/
- [ ] Flujo exacto sin excepciones en core: Plugin->Provider->Normalize->Fingerprint->History->Database->Notification sin if slug == "runway" en core/

**Entregables:**
- plugins/runway/plugin.py real playwright con fetch_first_success y candidate_urls
- data/raw/runway_sample.html HTML ejemplo para test offline (opcional)
- tests/plugins/runway/test_runway_extract.py con fixture HTML y asserts title, deadline, awards, description + economic_value float + candidate_urls genérico
- scripts/TICKET_011_REPORT.md con mismo nivel detalle
- TICKETS.md [x] Ticket 011

**Notas:**
- Usar playwright ya en requirements, instalar chromium via playwright install chromium
- Manejar caso sin deadline, sin premio, sin descripción (robustez)
- Usar logger monitor para logs
- Respetar enable por YML: config.yaml plugins.runway.enabled=true ya está

**Próximos:**
- Ticket 012: Scraper Adobe Real + AI Film Festival + It's Nice That
- Ticket 013: Integration Test con 5 plugins reales, 50-100 oportunidades reales deduplicadas, con history, notificaciones, métricas, logs
- Cuando volumen suficiente (300 opps), activar scoring y funcionalidades basadas en datos

**Instrucción:** Implementar solo Ticket 011, detenerse aquí y validar completamente antes de continuar, como en tickets anteriores. Si Runway funciona sin excepciones en core y valida deduplicación cross-source, arquitectura queda doblemente validada.
