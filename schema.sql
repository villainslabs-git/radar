-- schema.sql - Radar de Convocatorias v3.0
-- SQLite 3.x Compatible
-- Orden de creación respetando FKs

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- 1. ORGANIZATIONS - Entidad raíz
CREATE TABLE IF NOT EXISTS organizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    website TEXT,
    type TEXT CHECK(type IN ('company','festival','institution','platform','collective','magazine')),
    country TEXT,
    description TEXT,
    logo_url TEXT,
    total_opportunities INTEGER DEFAULT 0,
    first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen_at DATETIME,
    metadata_json TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 2. SOURCES - Pertenece a una org
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER REFERENCES organizations(id) ON DELETE SET NULL,
    url TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('official_page','festival_page','magazine','aggregator','pdf','rss','instagram','linkedin','x_twitter','newsletter')),
    discovery_method TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('active','inactive','error','quarantine','pending')),
    priority INTEGER DEFAULT 1,
    last_scraped_at DATETIME,
    last_status_code INTEGER,
    last_success_at DATETIME,
    error_count INTEGER DEFAULT 0,
    consecutive_errors INTEGER DEFAULT 0,
    config_json TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_sources_org ON sources(organization_id);
CREATE INDEX IF NOT EXISTS idx_sources_status_priority ON sources(status, priority DESC, last_scraped_at ASC);

-- 3. OPPORTUNITIES - Con fingerprint
CREATE TABLE IF NOT EXISTS opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    organization_id INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    fingerprint_hash TEXT NOT NULL,
    is_duplicate_of INTEGER REFERENCES opportunities(id),
    alternate_links_json TEXT,
    title TEXT NOT NULL,
    slug TEXT,
    organizer_name TEXT NOT NULL,
    official_link TEXT NOT NULL,
    description_raw TEXT,
    description_clean TEXT,
    executive_summary TEXT,
    open_date DATE,
    deadline DATETIME,
    deadline_confidence REAL DEFAULT 1.0,
    timezone TEXT DEFAULT 'UTC',
    awards_text TEXT,
    currency TEXT,
    economic_value REAL,
    economic_value_bucket TEXT,
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
    status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','upcoming','closed','postponed','cancelled')),
    first_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_changed_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(organization_id, fingerprint_hash)
);
CREATE INDEX IF NOT EXISTS idx_opp_fingerprint ON opportunities(fingerprint_hash);
CREATE INDEX IF NOT EXISTS idx_opp_org_deadline ON opportunities(organization_id, deadline);
CREATE INDEX IF NOT EXISTS idx_opp_status_deadline ON opportunities(status, deadline);
CREATE INDEX IF NOT EXISTS idx_opp_source ON opportunities(source_id);

-- 4. OPPORTUNITY_HISTORY - Trazabilidad
CREATE TABLE IF NOT EXISTS opportunity_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    change_type TEXT CHECK(change_type IN ('deadline_extended','deadline_shortened','prize_updated','status_changed','info_updated','created')),
    detected_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    source_id INTEGER REFERENCES sources(id),
    notified BOOLEAN DEFAULT 0,
    metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_hist_opp ON opportunity_history(opportunity_id, detected_at DESC);

-- 5. OPPORTUNITY_SCORES - 3 métricas simples
CREATE TABLE IF NOT EXISTS opportunity_scores (
    opportunity_id INTEGER PRIMARY KEY REFERENCES opportunities(id) ON DELETE CASCADE,
    relevance_score REAL NOT NULL DEFAULT 0.5 CHECK(relevance_score BETWEEN 0 AND 1),
    prize_score REAL NOT NULL DEFAULT 0.5 CHECK(prize_score BETWEEN 0 AND 1),
    urgency_score REAL NOT NULL DEFAULT 0.5 CHECK(urgency_score BETWEEN 0 AND 1),
    final_score REAL GENERATED ALWAYS AS (
        (relevance_score * 0.5 + prize_score * 0.3 + urgency_score * 0.2)
    ) STORED,
    scoring_version TEXT DEFAULT 'v3_simple',
    calculated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    explanation_json TEXT
);

-- 6. WATCHLIST - Asistente
CREATE TABLE IF NOT EXISTS watchlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id INTEGER NOT NULL UNIQUE REFERENCES opportunities(id) ON DELETE CASCADE,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'interested' CHECK(status IN ('interested','researching','applying','submitted','won','lost','dismissed')),
    priority_user INTEGER DEFAULT 2 CHECK(priority_user BETWEEN 1 AND 3),
    notes TEXT,
    reminder_enabled BOOLEAN DEFAULT 1,
    reminder_days_json TEXT DEFAULT '[30,15,7,3,1]',
    last_notified_at DATETIME,
    snoozed_until DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_watchlist_status ON watchlist(status);

-- 7. NOTIFICATIONS - Memoria del sistema
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    opportunity_id INTEGER REFERENCES opportunities(id) ON DELETE CASCADE,
    watchlist_id INTEGER REFERENCES watchlist(id) ON DELETE SET NULL,
    type TEXT NOT NULL CHECK(type IN (
        'new_opportunity',
        'deadline_changed',
        'deadline_reminder',
        'prize_updated',
        'status_closed',
        'status_postponed',
        'watchlist_digest',
        'system_digest'
    )),
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    scheduled_for DATETIME DEFAULT CURRENT_TIMESTAMP,
    sent_at DATETIME,
    is_read BOOLEAN DEFAULT 0,
    is_archived BOOLEAN DEFAULT 0,
    is_dismissed BOOLEAN DEFAULT 0,
    priority TEXT DEFAULT 'normal' CHECK(priority IN ('low','normal','high','urgent')),
    action_url TEXT,
    metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_notif_read_archived ON notifications(is_read, is_archived, scheduled_for);
CREATE INDEX IF NOT EXISTS idx_notif_opp ON notifications(opportunity_id);
CREATE INDEX IF NOT EXISTS idx_notif_type ON notifications(type, created_at DESC);

-- 8. OPPORTUNITY_TAGS
CREATE TABLE IF NOT EXISTS opportunity_tags (
    opportunity_id INTEGER NOT NULL REFERENCES opportunities(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    source TEXT DEFAULT 'rule_based',
    PRIMARY KEY (opportunity_id, tag)
);

-- 9. RAW_EXTRACTIONS - Auditoría opcional pero útil en v3.0
CREATE TABLE IF NOT EXISTS raw_extractions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    status_code INTEGER,
    content_hash TEXT,
    html_path TEXT, -- path a data/raw/...
    extracted_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_raw_source ON raw_extractions(source_id, fetched_at DESC);

-- Seed inicial de organizaciones clave
INSERT OR IGNORE INTO organizations (name, slug, website, type, country) VALUES
('Runway', 'runway', 'https://runwayml.com', 'company', 'USA'),
('Posterheroes', 'posterheroes', 'https://posterheroes.org', 'festival', 'Italy'),
('Adobe', 'adobe', 'https://adobe.com', 'company', 'USA'),
('ITS NICE THAT', 'itsnicethat', 'https://www.itsnicethat.com', 'magazine', 'UK'),
('AI Film Festival', 'ai-film-festival', 'https://aifilmfest.com', 'festival', 'USA');

-- Vista útil para digest rápido
CREATE VIEW IF NOT EXISTS v_opportunities_ranked AS
SELECT 
    o.id, o.title, org.name as org_name, o.deadline, o.status,
    s.relevance_score, s.prize_score, s.urgency_score, s.final_score,
    CASE WHEN w.id IS NOT NULL THEN 1 ELSE 0 END as in_watchlist
FROM opportunities o
JOIN organizations org ON o.organization_id = org.id
LEFT JOIN opportunity_scores s ON o.id = s.opportunity_id
LEFT JOIN watchlist w ON o.id = w.opportunity_id
WHERE o.is_duplicate_of IS NULL
ORDER BY s.final_score DESC NULLS LAST, o.deadline ASC;

-- Vista para watchlist activa
CREATE VIEW IF NOT EXISTS v_watchlist_active AS
SELECT w.*, o.title, o.deadline, o.official_link, org.name as org_name,
       CAST((julianday(o.deadline) - julianday('now')) AS INTEGER) as days_left,
       s.final_score
FROM watchlist w
JOIN opportunities o ON w.opportunity_id = o.id
JOIN organizations org ON o.organization_id = org.id
LEFT JOIN opportunity_scores s ON o.id = s.opportunity_id
WHERE o.status = 'open' AND w.status IN ('interested','researching','applying')
ORDER BY o.deadline ASC;
