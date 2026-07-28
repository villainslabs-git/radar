# RADAR DE CONVOCATORIAS - Arquitectura v3.0
### Sistema de monitoreo, organización y acompañamiento de oportunidades audiovisuales AI-based/empowered

> **Evolución del documento:** v2.0 (Manus - 7/10) -> v2.1 Feedback de revisión -> **v3.0 (Este documento - 10/10 objetivo)**
> Fecha: 2026-07-26 | Autor: Agente Continuación

---

## 0. Qué cambió respecto a v2.0 de Manus

Manus tenía razón en lo esencial: **el corazón no es la UI, es el agente**. Esta v3.0 mantiene eso y corrige lo que convertía al sistema en un "scraper con DB" para convertirlo en un **Radar real**.

| Feedback Recibido | Solución en v3.0 |
|---|---|
| **Source Discovery mezclado con Scraper** | Separación total en dos Jobs con frecuencias, objetivos y stacks distintos. `Job Discovery (semanal)` vs `Job Monitoring (cada 12h)` |
| **Falta `organizations`** | Nueva entidad raíz. Todo cuelga de una organización. Permite historial por marca (Ej: qué hizo Runway en 5 años). |
| **Deduplicación solo por URL** | Nuevo sistema de `fingerprint_hash` + similitud difusa (Organizer + Deadline bucket + Prize bucket + Title normalizado) |
| **Sin historial de cambios** | Nueva tabla `opportunity_history` con trazabilidad completa de cada campo crítico. |
| **Scoring con 7-8 métricas** | Simplificado a 3: `Relevancia x Premio x Urgencia`. Con pesos configurables en YAML. |
| **Sin notificaciones** | Nueva tabla `notifications` + motor de notificaciones con estado `visto/archivado/programado` |
| **Sin watchlist** | Nueva tabla `watchlist` que transforma el buscador en asistente (recordatorios T-30, T-7, T-3, T-1) |
| **Sin configuración** | Nuevo `config.yaml` como única fuente de verdad operativa. Cero cambios de código para ajustar comportamiento. |
| **LLM bajo demanda** | Se mantiene 100%. Se detalla patrón de invocación. |
| **UI primero** | Se invierte: Agente Headless First. La UI es el último paso. CLI summary como MVP. |

---

## 1. Principios de Diseño v3.0

1.  **Organization-Centric, no Opportunity-Centric:** Las oportunidades mueren, las organizaciones permanecen. Modelamos el mundo real.
2.  **Two Clocks:** Dos relojes independientes. No tiene sentido rastrear Google por nuevos festivales cada 12 horas.
3.  **Fingerprint, not URL:** La misma oportunidad vive en 5 lugares con 5 URLs distintas. La identidad es semántica, no sintáctica.
4.  **Everything has a history:** Si una deadline se mueve del 15/09 al 30/09, no sobreescribimos. Registramos. Es información de oro.
5.  **Assistant, not Search Engine:** El valor no es "encontré 20 convocatorias". Es "te avisé 7 días antes de la que te interesaba y detecté que extendieron el plazo".
6.  **Config over Code:** `config.yaml` > `main.py`.
7.  **Headless First:** El agente debe poder vivir 3 semanas sin que nadie abra una UI, solo escribiendo logs y generando notificaciones.

---

## 2. Visión General de Arquitectura v3.0

### Componentes Separados

```mermaid
graph TD
    subgraph Scheduler [Módulo de Orquestación v3 - Dos Relojes]
        S1[Job Discovery - Cron Semanal]
        S2[Job Monitoring - Cron Cada 12h]
        S3[Job Notifier - Cron Diario 09:00]
    end

    subgraph Discovery [Job 1: SOURCE DISCOVERY - Investigador]
        D1[Seed Sources: Revistas, Agregadores, X, LinkedIn]
        D2[Explorer: Busca nuevas Orgs y Festivales]
        D3[Validator: ¿Es fuente oficial? ¿Tiene historial?]
        D1 --> D2 --> D3
    end

    subgraph Monitoring [Job 2: SOURCE MONITORING - Vigilante]
        M1[Selector de Sources Activas por Prioridad]
        M2[Scraper: Playwright + Readability]
        M3[Extractor Normalizador]
        M1 --> M2 --> M3
    end

    subgraph Core [Core de Procesamiento]
        P1[Deduplicador por Fingerprint]
        P2[Change Tracker -> opportunity_history]
        P3[Scoring Simple: Relevancia/Premio/Urgencia]
        P4[Detector de Eventos para Notifications]
    end

    subgraph DB [(SQLite DB v3)]
        DB1[organizations]
        DB2[sources]
        DB3[opportunities + history + scores]
        DB4[watchlist + notifications]
    end

    subgraph Interfaces [Capa de Salida - Al Final]
        I1[CLI Summary: Hay 3 nuevas, 1 cambió deadline]
        I2[API Local para futura UI / Extension]
        I3[On-Demand LLM: Qwen/Ollama para Resúmenes]
    end

    S1 --> Discovery
    S2 --> Monitoring
    Discovery --> DB
    Monitoring --> Core
    Core --> DB
    S3 --> DB
    DB --> Interfaces
```

### Responsabilidades Claras

**Job Discovery (El Explorador) - `discovery/`:**
*   Objetivo: Encontrar NUEVAS organizaciones y NUEVAS fuentes.
*   Frecuencia: `weekly` (Domingo 03:00 AM) según `config.yaml`.
*   Input: Lista de semillas (ItsNiceThat, Creative Boom, Runway blog, Posterheroes, VideoHackers, Reddit r/aifilm).
*   Output: Nuevos registros en `organizations` y `sources` con status `pending_validation`.
*   No toca `opportunities`.

**Job Monitoring (El Vigilante) - `monitoring/`:**
*   Objetivo: Visitar solo fuentes YA conocidas y extraer oportunidades.
*   Frecuencia: `every 12h`.
*   Input: `SELECT * FROM sources WHERE status='active' ORDER BY priority DESC, last_scraped ASC`.
*   Output: Datos crudos -> `raw_extractions` -> oportunidades normalizadas.
*   No busca en Google. Solo vigila.

---

## 3. Modelo de Datos v3.0 - Rediseño Completo

Este es el corazón de la v3.0. Pasamos de 4 tablas planas a 7 tablas relacionales + 1 de auditoría.

### Diagrama ER Conceptual

```
organizations (1) ----< (N) sources
      |
      | (1) ----< (N) opportunities
                    |
                    |---< opportunity_history (N)
                    |---< opportunity_scores (1)
                    |---   watchlist (1 or 0)
                    |---< notifications (N)
                    |---< opportunity_tags (N)
```

### 3.1 `organizations` [NUEVA TABLA RAÍZ]

La entidad que perdura en el tiempo.

```sql
CREATE TABLE organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE, -- Ej: "Runway", "Posterheroes", "Adobe"
    slug TEXT NOT NULL UNIQUE, -- runway, posterheroes
    website TEXT,
    type TEXT CHECK(type IN ('company','festival','institution','platform','collective','magazine')), 
    country TEXT,
    description TEXT,
    logo_url TEXT,
    -- Métricas derivadas
    total_opportunities INTEGER DEFAULT 0,
    first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen_at DATETIME,
    metadata_json TEXT, -- {"socials": {"ig": "...", "x": "..."}, "notes": "..."}
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Permite consultas como:**
> "Mostrame todas las convocatorias históricas de Runway" -> `SELECT * FROM opportunities WHERE organization_id = (SELECT id FROM organizations WHERE slug='runway') ORDER BY deadline DESC`
> "¿Qué hizo Adobe durante los últimos 5 años?" -> Join + filtro de fechas

### 3.2 `sources` [REFORMULADA]

Ahora pertenece a una organización.

```sql
CREATE TABLE sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
    url TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('official_page','festival_page','magazine','aggregator','pdf','rss','instagram','linkedin','x_twitter','newsletter')),
    discovery_method TEXT, -- "manual_seed", "discovery_job_v1", "user_added"
    -- Salud de la fuente
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('active','inactive','error','quarantine','pending')),
    priority INTEGER DEFAULT 1, -- 10 = Runway oficial, 1 = blog random que a veces republica
    last_scraped_at DATETIME,
    last_status_code INTEGER,
    last_success_at DATETIME,
    error_count INTEGER DEFAULT 0,
    consecutive_errors INTEGER DEFAULT 0,
    -- Control
    config_json TEXT, -- {"selector": ".opportunity-card", "needs_playwright": true}
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_sources_org ON sources(organization_id);
CREATE INDEX idx_sources_status_priority ON sources(status, priority DESC, last_scraped_at ASC);
```

### 3.3 `opportunities` [REFORMULADA con Fingerprint]

```sql
CREATE TABLE opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    -- Identidad Semántica (NUEVO)
    fingerprint_hash TEXT NOT NULL, -- SHA256(organizer_norm + deadline_bucket + prize_bucket + title_norm_trigram)
    is_duplicate_of INTEGER REFERENCES opportunities(id), -- Si es duplicado, apunta al canonical
    alternate_links_json TEXT, -- ["url_revista1", "url_pdf", "url_ig"] - todas las URLs donde se vio la misma oportunidad
    
    -- Datos Core
    title TEXT NOT NULL,
    slug TEXT,
    organizer_name TEXT NOT NULL, -- Denormalizado para búsquedas rápidas, pero FK real es organization_id
    official_link TEXT NOT NULL,
    
    -- Contenido
    description_raw TEXT,
    description_clean TEXT,
    executive_summary TEXT, -- Generado por LLM bajo demanda
    
    -- Fechas
    open_date DATE,
    deadline DATETIME,
    deadline_confidence REAL DEFAULT 1.0, -- 0.5 si el scraper no está seguro
    timezone TEXT DEFAULT 'UTC',
    
    -- Premios
    awards_text TEXT,
    currency TEXT,
    economic_value REAL,
    economic_value_bucket TEXT, -- "0-500", "500-2k", "2k-10k", "10k+"

    -- Clasificación
    country TEXT,
    accepts_argentinians BOOLEAN,
    geo_restrictions TEXT,
    category TEXT CHECK(category IN ('AI','Video','Motion','Publicidad','Arte Digital','Cine','Foto','Música','General')),
    modality TEXT,
    fee_type TEXT,
    language TEXT,
    format_requested TEXT,
    ai_allowed BOOLEAN,
    ai_mandatory BOOLEAN,
    requirements TEXT,
    
    -- Estado
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','upcoming','closed','postponed','cancelled')),
    first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_changed_at DATETIME,
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(organization_id, fingerprint_hash) -- Evita duplicados lógicos, no solo de URL
);
CREATE INDEX idx_opp_fingerprint ON opportunities(fingerprint_hash);
CREATE INDEX idx_opp_org_deadline ON opportunities(organization_id, deadline);
CREATE INDEX idx_opp_status_deadline ON opportunities(status, deadline);
```

### 3.4 `opportunity_history` [NUEVA - Crítica]

No sobreescribimos, versionamos.

```sql
CREATE TABLE opportunity_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL, -- "deadline", "awards_text", "status", "economic_value"
    old_value TEXT,
    new_value TEXT,
    change_type TEXT CHECK(change_type IN ('deadline_extended','deadline_shortened','prize_updated','status_changed','info_updated','created')),
    detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    source_id INTEGER REFERENCES sources(id), -- Qué fuente reportó el cambio
    notified BOOLEAN DEFAULT 0, -- Si ya se generó una notificación por este cambio
    metadata_json TEXT
);
CREATE INDEX idx_hist_opp ON opportunity_history(opportunity_id, detected_at DESC);

-- Ejemplo de dato real:
-- 20/07 | deadline | 2026-09-15 | 2026-09-30 | deadline_extended
-- 01/08 | awards_text | "$5000" | "$10000 + Mentorship" | prize_updated
```

### 3.5 `opportunity_scores` [SIMPLIFICADA - 3 métricas]

De 8 métricas a 3. Pesos en config.yaml.

```sql
CREATE TABLE opportunity_scores (
    opportunity_id INTEGER PRIMARY KEY REFERENCES opportunities(id) ON DELETE CASCADE,
    
    -- Los 3 pilares
    relevance_score REAL NOT NULL DEFAULT 0.5 CHECK(relevance_score BETWEEN 0 AND 1), -- ¿Qué tanto te sirve a vos? (Argentina, AI, categoría)
    prize_score REAL NOT NULL DEFAULT 0.5 CHECK(prize_score BETWEEN 0 AND 1), -- ¿Vale la pena el premio? (económico + prestigio)
    urgency_score REAL NOT NULL DEFAULT 0.5 CHECK(urgency_score BETWEEN 0 AND 1), -- ¿Cuánto tiempo queda? 1 = vence mañana, 0 = vence en 6 meses
    
    -- Score final calculado
    final_score REAL GENERATED ALWAYS AS (
        (relevance_score * 0.5 + prize_score * 0.3 + urgency_score * 0.2)
    ) STORED,
    
    -- Trazabilidad
    scoring_version TEXT DEFAULT 'v3_simple',
    calculated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    explanation_json TEXT -- {"relevance": "category match + accepts_arg", "prize": "10k+", "urgency": "15 days left"}
);

-- Cálculo urgency_score sugerido:
-- urgency = 1 - (days_left / 90) clamped 0-1. Si days_left <0 => 1 (urgentísimo, cierra hoy)
-- O curva exponencial para últimos 7 días.
```

### 3.6 `watchlist` [NUEVA - Convierte Buscador en Asistente]

```sql
CREATE TABLE watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id INTEGER NOT NULL UNIQUE REFERENCES opportunities(id) ON DELETE CASCADE,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    -- Estado del usuario
    status TEXT NOT NULL DEFAULT 'interested' CHECK(status IN ('interested','researching','applying','submitted','won','lost','dismissed')),
    priority_user INTEGER DEFAULT 2 CHECK(priority_user BETWEEN 1 AND 3), -- 3 = top priority
    notes TEXT, -- "Necesito pedir carta de recomendación"
    
    -- Lógica de recordatorio - puede ser override de config.yaml
    reminder_enabled BOOLEAN DEFAULT 1,
    reminder_days_json TEXT DEFAULT '[30,15,7,3,1]', -- Días antes del deadline
    
    last_notified_at DATETIME,
    snoozed_until DATETIME,
    
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

**Flujo Watchlist:** User marca "Me interesa" -> Genera notificaciones programadas automáticamente a T-30,15,7,3,1 y también si hay `opportunity_history` para esa oportunidad.

### 3.7 `notifications` [NUEVA - Memoria del Sistema]

El sistema sabe qué ya te mostró.

```sql
CREATE TABLE notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id INTEGER REFERENCES opportunities(id) ON DELETE CASCADE,
    watchlist_id INTEGER REFERENCES watchlist(id) ON DELETE SET NULL,
    
    type TEXT NOT NULL CHECK(type IN (
        'new_opportunity',          -- Nueva oportunidad relevante (score alto)
        'deadline_changed',         -- Cambio en deadline (crítico)
        'deadline_reminder',        -- T-30,15,7,3,1 para watchlist
        'prize_updated',
        'status_closed',
        'status_postponed',
        'watchlist_digest',         -- Resumen diario de tu watchlist
        'system_digest'             -- "Hay 3 nuevas, 1 cambió deadline, 2 cerraron"
    )),
    
    title TEXT NOT NULL, -- "Runway AI Film Festival extendió deadline"
    message TEXT NOT NULL, -- "Nueva fecha: 30/09 (antes 15/09). Te quedan 15 días."
    
    -- Ciclo de vida
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    scheduled_for DATETIME DEFAULT CURRENT_TIMESTAMP, -- Para recordatorios futuros
    sent_at DATETIME, -- Cuando se mostró/envió
    is_read BOOLEAN DEFAULT 0,
    is_archived BOOLEAN DEFAULT 0,
    is_dismissed BOOLEAN DEFAULT 0,
    
    priority TEXT DEFAULT 'normal' CHECK(priority IN ('low','normal','high','urgent')),
    action_url TEXT, -- Deep link a la oportunidad
    metadata_json TEXT -- {"old_deadline": "...", "new_deadline": "..."}
);
CREATE INDEX idx_notif_read_archived ON notifications(is_read, is_archived, scheduled_for);
CREATE INDEX idx_notif_opp ON notifications(opportunity_id);
```

### 3.8 `opportunity_tags` (Se mantiene de v2.0)

```sql
CREATE TABLE opportunity_tags (
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    source TEXT DEFAULT 'rule_based', -- rule_based, llm, manual
    PRIMARY KEY (opportunity_id, tag)
);
```

---

## 4. Lógica de Deduplicación por Fingerprint [NUEVO]

### Por qué URL no sirve:

- La misma convocatoria aparece en: revista (itsnicethat.com/runway), página oficial (runwayml.com/festival-2026), PDF de bases, post de Instagram, LinkedIn.
- 5 URLs, 1 oportunidad real.

### Algoritmo Fingerprint v3

```python
def normalize_title(title: str) -> str:
    title = title.lower().strip()
    title = re.sub(r'\b(2026|2027|2028|2025|edición|edition|convocatoria|festival)\b', '', title)
    title = unidecode(title) # quitar acentos
    title = re.sub(r'[^a-z0-9]', '', title)
    return title[:50] # primeros 50 chars significativos

def bucket_deadline(deadline: datetime) -> str:
    # Agrupar por quincena, no por día exacto, por si hay cambios menores
    if not deadline: return "no_deadline"
    return f"{deadline.year}-{deadline.month:02d}-{(deadline.day//15)}" # Ej: 2026-09-1 (primera quincena sep)

def bucket_prize(value: float, text: str) -> str:
    if not value and "exposure" in text.lower(): return "exposure"
    if value is None: return "unknown"
    if value < 500: return "0-500"
    if value < 2000: return "500-2k"
    if value < 10000: return "2k-10k"
    return "10k+"

def generate_fingerprint(org_id: int, title: str, deadline: datetime, prize_value: float, prize_text: str) -> str:
    parts = [
        str(org_id), # Más robusto que organizer string
        normalize_title(title),
        bucket_deadline(deadline),
        bucket_prize(prize_value, prize_text)
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16] # 16 chars es suficiente

# Umbral de fusión:
# Si fingerprint exacto => merge automático, agregar alternate_link
# Si org_id igual + title similarity > 0.85 (Levenshtein/trigram) + deadline en +/- 15 días => cola de revisión "possible_duplicate"
```

**Flujo en Monitoring Job:**
1. Scrapea oportunidad candidata -> genera fingerprint.
2. `SELECT * FROM opportunities WHERE organization_id=? AND fingerprint_hash=?` -> Si existe, no crea nueva, agrega URL a `alternate_links_json`, actualiza `last_seen_at`.
3. Si no existe exacto, busca candidatos con mismo `organization_id` y `deadline` +/- 15 días y calcula similitud de título (usando `rapidfuzz`). Si > 85% -> marca como `possible_duplicate` y no notifica hasta revisión manual o confirmación de 2 fuentes distintas.
4. Si no hay candidatos -> oportunidad nueva, genera notificación `new_opportunity` si `final_score > threshold`.

---

## 5. Flujos de Ejecución Separados v3.0

### Job 1: Discovery - `python -m jobs.discovery`

Frecuencia: Semanal, Domingo 03:00 UTC-3.

```
[Seed Loader] Lee config.yaml -> discovery.seeds (20 URLs de revistas/agregadores)
   |
[Explorer] Para cada seed: Playwright -> extrae todos los links externos que contienen keywords (festival, convocatoria, open call, grant, AI film)
   |
[Org Resolver] Para cada link nuevo: ¿El dominio ya existe en organizations? 
   Si no: Crea organization con LLM (extrae nombre, tipo). Luego crea source con status=pending
   Si sí: Crea source asociado a org existente si url no existe.
   |
[Health Check] Para cada source pending: intenta fetch /about, /opportunities. Si 200 y contiene fecha futura -> promote a active con priority=1. Si no -> quarantine.
   |
[Report] Genera notificación tipo system_digest: "Discovery semanal: 5 nuevas orgs, 12 nuevas sources (3 activadas)"
```

### Job 2: Monitoring - `python -m jobs.monitoring`

Frecuencia: Cada 12h.

```
[Selector] SELECT * FROM sources WHERE status='active' ORDER BY priority DESC, last_scraped_at ASC LIMIT config.scan.batch_size
   |
[Scraper Cluster] Para cada source: Playwright (si needs_playwright) o httpx+BeautifulSoup
   -> raw_extraction guardado en tabla temporal raw_extractions para auditoría
   |
[Extractor] LLM ligero? No. Reglas + selectors del source.config_json -> extrae (title, deadline, prize, etc) -> normaliza fechas con dateparser
   |
[Deduplicador] fingerprint -> check duplicado (ver sección 4)
   |
[Change Tracker] Si oportunidad ya existía: compara campo por campo
   Si deadline != old_deadline: INSERT INTO opportunity_history + UPDATE opportunities + CREATE notification tipo deadline_changed (priority=urgent si está en watchlist)
   |
[Scoring] Calcula relevance/prize/urgency -> INSERT INTO opportunity_scores
   |
[Event Detector] Si nueva oportunidad con final_score > config.notifications.min_score_for_new -> CREATE notification new_opportunity
   |
[Update Source] SET last_scraped_at=NOW(), last_success_at=NOW(), consecutive_errors=0
```

### Job 3: Notifier / Watchlist - `python -m jobs.notifier`

Frecuencia: Diario 09:00 y cada hora para urgentes.

```
[Watchlist Scanner] SELECT w.*, o.deadline FROM watchlist w JOIN opportunities o ON w.opportunity_id=o.id WHERE w.reminder_enabled=1 AND o.status='open'
   Para cada item: calcula días restantes. Si days_left IN reminder_days_json y last_notified_at < 24h: CREATE notification deadline_reminder scheduled_for=NOW()
   |
[Urgent Scanner] SELECT * FROM notifications WHERE type='deadline_changed' AND is_read=0 AND priority='urgent' AND scheduled_for <= NOW()
   |
[Digest Builder] Si es 09:00: Construye system_digest con conteos de últimas 24h:
   "Hay 3 convocatorias nuevas (1 con score 0.92), 1 modificó su deadline (Posterheroes), 2 cerraron."
   |
[Delivery] En v3 sin UI: escribe a logs, y a notifications.sent_at=NOW(). Futura UI/Ext leerá de ahí.
```

---

## 6. Sistema de Puntuación Simplificado v3.0

### Filosofía: Menos métricas, más accionable.

**Fórmula Final:** `final_score = (relevance * w_r) + (prize * w_p) + (urgency * w_u)`

Pesos por defecto en `config.yaml`: `relevance: 0.5, prize: 0.3, urgency: 0.2`

#### 6.1 `relevance_score` (0-1) - ¿Esto es para mí?

```python
def calc_relevance(opp, config):
    score = 0.0
    if opp.category in config.categories: score += 0.3
    if opp.accepts_argentinians or opp.country in config.countries: score += 0.3
    if opp.language in config.languages: score += 0.1
    if opp.ai_allowed or opp.ai_mandatory: score += 0.2
    # Bonus si organizer en favoritos (Ej: Runway siempre alta)
    if opp.organization_id in config.favorite_orgs: score += 0.2
    return min(score, 1.0)
```

#### 6.2 `prize_score` (0-1) - ¿Vale el esfuerzo?

```python
def calc_prize(opp):
    if opp.economic_value:
        if opp.economic_value >= 10000: return 1.0
        if opp.economic_value >= 2000: return 0.8
        if opp.economic_value >= 500: return 0.5
        return 0.2
    # Si no hay plata pero hay prestigio: mapear keywords
    text = (opp.awards_text or "").lower()
    if "cannes" in text or "oscar qualifying" in text: return 0.9
    if "exhibition" in text or "screening" in text: return 0.6
    return 0.3
```

#### 6.3 `urgency_score` (0-1) - ¿Tengo que apurarme?

No es lineal. Curva exponencial últimos 7 días.

```python
def calc_urgency(deadline):
    if not deadline: return 0.5
    days_left = (deadline - now()).days
    if days_left < 0: return 0.0 # Ya cerró, pero lo mantenemos para historial
    if days_left <= 1: return 1.0
    if days_left <= 3: return 0.9
    if days_left <= 7: return 0.75
    if days_left <= 15: return 0.5
    if days_left <= 30: return 0.3
    return 0.1
```

---

## 7. Archivo de Configuración `config.yaml` [NUEVO]

Única fuente de verdad operativa. Cero código para cambiar comportamiento.

```yaml
# config.yaml - Radar de Convocatorias v3.0
project:
  name: "Radar Audiovisual AI"
  timezone: "America/Argentina/Buenos_Aires"
  db_path: "data/radar_v3.db"
  log_level: "INFO"

scan:
  monitoring:
    enabled: true
    cron: "every 12h" # o "0 */12 * * *"
    batch_size: 25    # cuántas sources por corrida
    timeout_seconds: 45
    use_playwright_for: ["official_page", "festival_page"] # qué tipos requieren browser
  discovery:
    enabled: true
    cron: "0 3 * * 0" # Domingo 3AM
    max_new_sources_per_run: 30
    seeds:
      - https://www.itsnicethat.com/news
      - https://www.creativeboom.com/inspiration/
      - https://runwayml.com/blog
      - https://posterheroes.org
      - https://www.videomaker.com/
      - https://www.reddit.com/r/aifilm/new/
      # ... 15 más

notifications:
  min_score_for_new: 0.65 # Solo notifica nuevas si final_score > 0.65
  deadline_days: [30, 15, 7, 3, 1] # Default para watchlist
  digest_time: "09:00"
  channels: ["db", "log"] # futuro: ["db", "email", "telegram", "chrome_ext"]

countries:
  - Argentina
  - LATAM
  - Global
  - No restriction

languages:
  - Español
  - Inglés
  - Portugués

categories:
  - AI
  - Video
  - Motion
  - Publicidad
  - Cine
  - Arte Digital

scoring:
  weights:
    relevance: 0.5
    prize: 0.3
    urgency: 0.2
  favorite_orgs: ["runway", "adobe", "posterheroes"] # slugs

organizations:
  # Configuración para extraer orgs automáticamente
  min_opportunities_to_be_org: 1

deduplication:
  fingerprint_version: "v3"
  title_similarity_threshold: 0.85 # para possible_duplicate
  deadline_delta_days: 15

watchlist:
  auto_add_if_score_above: 0.9 # Si una oportunidad saca 0.9, entra sola a watchlist con status interested

llm:
  provider: "ollama" # o "lmstudio", "openai"
  model: "qwen2.5:7b"
  on_demand_only: true
  tasks:
    - summarize_bases
    - check_rights_cession
    - check_argentina_eligibility
```

---

## 8. Módulo de IA Bajo Demanda v3.0 - Se mantiene perfecto

No consume recursos en los jobs. Solo cuando el usuario hace click en "Analizar".

**API Interna:**

```python
# core/llm_service.py
class OnDemandLLM:
    def __init__(self, config): self.client = OllamaClient(config.llm.model)

    def summarize(self, opportunity_id: int) -> str:
        opp = db.get_opportunity(opportunity_id)
        prompt = f"Resumime en 5 bullets las bases de esta convocatoria:\n{opp.description_clean}\nEn español, foco en requisitos y cesión de derechos."
        return self.client.generate(prompt)

    def check_rights_cession(self, opportunity_id) -> dict:
        # Retorna {"has_cession": bool, "is_abusive": bool, "clause": str, "explanation": str}

    def can_argentinian_apply(self, opportunity_id) -> dict:
        # Retorna {"eligible": bool, "confidence": 0.9, "reason": str}
```

**Patrón de uso:** La futura UI / CLI llama a `llm_service.summarize(id)` -> Esto inserta un registro en `notifications` tipo `llm_task_completed` cuando termina.

---

## 9. Interfaz: Headless First [NUEVO - Al Final]

### Fase Headless (v3.0 - Ahora):

El agente vive sin UI.

**CLI Summary (el único output de los jobs):**

```bash
$ python -m jobs.monitoring && python -m jobs.notifier --show-digest

[2026-07-26 09:00] === RADAR DIGEST 24H ===
Hay 3 convocatorias nuevas:
  [0.92] Runway AI Film Festival 2026 - $25k - 45 días
  [0.71] Posterheroes 2026 - Exhibition + $2k - 60 días
  [0.68] Adobe Creative Residency - Grants - 22 días

1 modificó su deadline (URGENTE - en tu watchlist):
  ! Posterheroes 2025/2026 -> extendido de 15/09 a 30/09

2 cerraron:
  - AI Video Awards (cierre 25/07)
  - Motion Motion Festival

Tu watchlist (4 activas):
  - Runway (T-45), Posterheroes (T-65, deadline extendido!), Adobe (T-22)
  Próximos recordatorios: Adobe en 7 días.

Run `python -m cli list --score-min 0.6` para ver detalle.
```

**Tablas como UI:** En esta fase, `sqlite3 data/radar_v3.db "SELECT title, deadline, final_score FROM opportunities JOIN opportunity_scores USING(opportunity_id) ORDER BY final_score DESC LIMIT 10"` ES la UI.

### Fase Futura (v3.5):
*   FastAPI local `api/main.py` que expone `/opportunities`, `/watchlist`, `/notifications`
*   Extensión Chrome que lee de esa API local
*   Dashboard web local simple con filters por score, org, deadline

Pero no ahora. Ahora el foco es que el Radar sea autónomo y útil sin abrir nada.

---

## 10. Roadmap v3.0 Actualizado

### Fase 1: Diseño Técnico (Completada + esta v3.0)

- [x] Arquitectura v2.0 Manus
- [x] Feedback y requisitos 10 puntos
- [x] **Arquitectura v3.0 con modelo rediseñado (este doc)**
- [ ] `schema.sql` final + `config.yaml` base
- [ ] Crear estructura de carpetas: `/jobs`, `/core`, `/data`, `/config`

### Fase 2: Fundación y Job Monitoring (Core del Radar)

- [ ] Tarea 2.1: Setup Python + SQLite + Playwright + httpx + rapidfuzz + pyyaml
- [ ] Tarea 2.2: Implementar `organizations` + CRUD + seed de 10 orgs iniciales (Runway, Posterheroes, Adobe, etc)
- [ ] Tarea 2.3: Migrar `sources` a nuevo esquema con `organization_id`
- [ ] Tarea 2.4: Implementar Job Monitoring aislado: selector -> scraper -> extractor (sin dedup por ahora)
- [ ] Tarea 2.5: Implementar `opportunity_history` tracker (detecta cambios campo por campo)

### Fase 3: Inteligencia del Radar (Fingerprint + Scoring + Watchlist)

- [ ] Tarea 3.1: Implementar `fingerprint_hash` + algoritmo de deduplicación (merge de alternate_links)
- [ ] Tarea 3.2: Sistema de Scoring simple (3 métricas) + pesos desde config
- [ ] Tarea 3.3: Implementar `watchlist` + lógica de inserción manual y auto (score > 0.9)
- [ ] Tarea 3.4: Implementar `notifications` engine + tipos de eventos (new, deadline_changed, reminder)

### Fase 4: Job Discovery Separado

- [ ] Tarea 4.1: Implementar Job Discovery semanal: seed loader -> explorer -> org resolver
- [ ] Tarea 4.2: Health check de nuevas fuentes (promote quarantine -> active)
- [ ] Tarea 4.3: Probar Discovery vs Monitoring en paralelo durante 2 semanas, medir no overlapping

### Fase 5: Headless Ops + LLM bajo demanda

- [ ] Tarea 5.1: `config.yaml` loader + validación + hot-reload simple
- [ ] Tarea 5.2: CLI `python -m cli digest` y `python -m cli watchlist` (unico UI inicial)
- [ ] Tarea 5.3: Scheduler real con `APScheduler` que corre los 3 jobs con sus crons de config.yaml
- [ ] Tarea 5.4: On-Demand LLM con Ollama + Qwen 7B para `summarize_bases` y `check_rights`

### Fase 6: Futuro (v3.5+)

- [ ] API FastAPI local
- [ ] Extensión Chrome v1 (solo lectura de notifications + watchlist)
- [ ] Dashboard web local

---

## 11. Estructura de Carpetas Propuesta v3.0

```
radar/
├── config/
│   └── config.yaml          # <--- Fuente de verdad
├── data/
│   ├── radar_v3.db
│   └── raw_extractions/     # logs de html crudo para debug
├── core/
│   ├── db.py                # conexión + migraciones
│   ├── models.py            # dataclasses
│   ├── fingerprint.py       # lógica deduplicación (Sec 4)
│   ├── scoring.py           # 3 métricas
│   ├── history.py           # change tracker
│   ├── notifications.py     # generador de eventos
│   └── llm_service.py       # on-demand
├── jobs/
│   ├── discovery.py         # Job semanal (separado)
│   ├── monitoring.py        # Job 12h (separado)
│   └── notifier.py          # Job diario watchlist/digest
├── cli/
│   ├── __main__.py          # python -m cli digest
│   └── commands.py
├── scrapers/
│   ├── base.py
│   ├── playwright_scraper.py
│   └── selectors/           # yaml por source si se necesita
└── architecture_description_v3.md
```

---

## 12. Conclusión v3.0

Esta v3.0 ya no es un scraper. Es un **Radar de Convocatorias y Oportunidades de desarrollo audiovisual AI based/empowered** que:

1.  **Entiende el mundo:** Sabe que Runway tiene múltiples programas a lo largo de años (gracias a `organizations`).
2.  **No duplica:** Entiende que 5 URLs pueden ser 1 oportunidad (gracias a `fingerprint`).
3.  **Recuerda:** Sabe que una deadline se movió y te avisa si la tenías en seguimiento (gracias a `history` + `watchlist` + `notifications`).
4.  **Trabaja solo:** Dos relojes independientes, uno semanal para descubrir y otro cada 12h para vigilar. No desperdicia recursos.
5.  **Se configura sin tocar código:** Cambias `config.yaml` y cambia comportamiento.
6.  **Es asistente, no buscador:** La `watchlist` con recordatorios T-30,7,3,1 es la feature que convierte info en acción.
7.  **Vive headless:** Puede correr semanas generando solo un digest por CLI: "Hay 3 nuevas, 1 modificó deadline, 2 cerraron". Ya con eso el núcleo funciona.

**Próximo paso inmediato recomendado:** Generar `schema.sql` con todos los `CREATE TABLE` de la Sección 3 y `config.yaml` base, y luego implementar `jobs/monitoring.py` con `organizations` precargadas (Runway, Posterheroes, Adobe, etc).

Este documento está listo para pasar a código.
