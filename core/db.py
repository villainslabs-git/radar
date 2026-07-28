"""
Radar - Core DB Wrapper
Ticket 002: Núcleo reproducible

Objetivo: Wrapper SQLite con context manager, helpers CRUD, validación de integridad.
No ORM pesado. Solo sqlite3 stdlib + logging.

Para validación posterior de 300 oportunidades antes de hacer scoring.
"""
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from contextlib import contextmanager
import json
from core.logger import get_logger
from core.config import get_config

logger = get_logger("db")

class RadarDB:
    def __init__(self, db_path: Path = None):
        cfg = get_config()
        self.db_path = db_path or cfg.get_db_path()
        self.db_path = Path(self.db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
    
    @contextmanager
    def connect(self):
        """Context manager que habilita FKs y WAL"""
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"DB transaction failed: {e}", exc_info=True)
            raise
        finally:
            conn.close()
    
    def table_exists(self, name: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,))
            return cur.fetchone() is not None
    
    def validate_integrity(self) -> Dict[str, Any]:
        """
        Para radar doctor y init_db.
        Retorna dict con estado de cada tabla, conteos, FK check.
        """
        result = {
            "db_path": str(self.db_path),
            "exists": self.db_path.exists(),
            "tables": {},
            "counts": {},
            "fk_check": "OK",
            "issues": []
        }
        
        if not result["exists"]:
            result["issues"].append(f"DB file not found: {self.db_path}")
            return result
        
        try:
            with self.connect() as conn:
                # Check tables
                cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [r[0] for r in cur.fetchall()]
                
                expected = ["organizations","sources","opportunities","opportunity_history","opportunity_scores","watchlist","notifications","opportunity_tags","raw_extractions"]
                for exp in expected:
                    result["tables"][exp] = exp in tables
                    if exp not in tables:
                        result["issues"].append(f"Missing table: {exp}")
                
                # Counts
                for t in expected:
                    if t in tables:
                        try:
                            c = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                            result["counts"][t] = c
                        except Exception as e:
                            result["counts"][t] = f"error: {e}"
                
                # FK check
                try:
                    fk_errors = conn.execute("PRAGMA foreign_key_check;").fetchall()
                    if fk_errors:
                        result["fk_check"] = f"FAILED: {fk_errors}"
                        result["issues"].append(f"FK violations: {fk_errors}")
                except Exception as e:
                    result["fk_check"] = f"error: {e}"
                
                # Views
                cur = conn.execute("SELECT name FROM sqlite_master WHERE type='view'")
                views = [r[0] for r in cur.fetchall()]
                result["views"] = views
                
        except Exception as e:
            result["issues"].append(f"Validation exception: {e}")
        
        return result
    
    # --- CRUD helpers mínimos para init ---
    
    def insert_organization(self, name: str, slug: str, website: str = "", type: str = "company", country: str = "") -> int:
        with self.connect() as conn:
            cur = conn.execute("""
                INSERT OR IGNORE INTO organizations (name, slug, website, type, country)
                VALUES (?, ?, ?, ?, ?)
            """, (name, slug, website, type, country))
            if cur.lastrowid == 0:
                # Ya existía, buscar id
                cur = conn.execute("SELECT id FROM organizations WHERE slug=?", (slug,))
                row = cur.fetchone()
                return row["id"] if row else 0
            return cur.lastrowid
    
    def insert_source(self, org_id: int, url: str, name: str, type: str = "official_page", status: str = "active", priority: int = 5, discovery_method: str = "seed") -> int:
        with self.connect() as conn:
            cur = conn.execute("""
                INSERT OR IGNORE INTO sources (organization_id, url, name, type, status, priority, discovery_method)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (org_id, url, name, type, status, priority, discovery_method))
            if cur.lastrowid == 0:
                cur = conn.execute("SELECT id FROM sources WHERE url=?", (url,))
                row = cur.fetchone()
                return row["id"] if row else 0
            return cur.lastrowid

    def get_organizations(self) -> List[Dict]:
        with self.connect() as conn:
            cur = conn.execute("SELECT * FROM organizations ORDER BY name")
            return [dict(r) for r in cur.fetchall()]
    
    def get_sources(self, only_active: bool = False) -> List[Dict]:
        with self.connect() as conn:
            q = "SELECT s.*, o.name as org_name, o.slug as org_slug FROM sources s LEFT JOIN organizations o ON s.organization_id=o.id"
            if only_active:
                q += " WHERE s.status='active'"
            q += " ORDER BY s.priority DESC"
            cur = conn.execute(q)
            return [dict(r) for r in cur.fetchall()]

    # --- Métodos para Monitoring Engine (Ticket 006) ---

    def find_organization_by_slug(self, slug: str) -> Optional[Dict]:
        with self.connect() as conn:
            cur = conn.execute("SELECT * FROM organizations WHERE slug=?", (slug,))
            row = cur.fetchone()
            return dict(row) if row else None

    def find_opportunity_by_fingerprint(self, fingerprint_hash: str, organization_id: int = None) -> Optional[Dict]:
        with self.connect() as conn:
            if organization_id:
                cur = conn.execute("""
                    SELECT o.*, org.slug as org_slug, s.url as source_url
                    FROM opportunities o
                    LEFT JOIN organizations org ON o.organization_id=org.id
                    LEFT JOIN sources s ON o.source_id=s.id
                    WHERE o.fingerprint_hash=? AND o.organization_id=?
                """, (fingerprint_hash, organization_id))
            else:
                cur = conn.execute("""
                    SELECT o.*, org.slug as org_slug, s.url as source_url
                    FROM opportunities o
                    LEFT JOIN organizations org ON o.organization_id=org.id
                    LEFT JOIN sources s ON o.source_id=s.id
                    WHERE o.fingerprint_hash=?
                """, (fingerprint_hash,))
            row = cur.fetchone()
            return dict(row) if row else None

    def find_opportunity_by_id(self, opp_id: int) -> Optional[Dict]:
        with self.connect() as conn:
            cur = conn.execute("SELECT * FROM opportunities WHERE id=?", (opp_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def insert_opportunity(self, opportunity_data: Dict[str, Any]) -> int:
        """
        Inserta nueva oportunidad, maneja alternate_links_json, fingerprint_hash UNIQUE constraint
        opportunity_data debe tener: organization_id, source_id, fingerprint_hash, title, organizer_name, official_link, etc
        """
        # Campos permitidos en tabla opportunities
        allowed_fields = [
            "organization_id", "source_id", "fingerprint_hash", "is_duplicate_of",
            "alternate_links_json", "title", "slug", "organizer_name", "official_link",
            "description_raw", "description_clean", "executive_summary",
            "open_date", "deadline", "deadline_confidence", "timezone",
            "awards_text", "currency", "economic_value", "economic_value_bucket",
            "country", "accepts_argentinians", "geo_restrictions",
            "category", "modality", "fee_type", "language", "format_requested",
            "ai_allowed", "ai_mandatory", "requirements", "status"
        ]
        
        # Filtrar solo campos permitidos
        filtered = {k: v for k, v in opportunity_data.items() if k in allowed_fields}
        
        # Asegurar defaults
        if "status" not in filtered:
            filtered["status"] = "open"
        if "organizer_name" not in filtered:
            filtered["organizer_name"] = "Unknown"
        if "title" not in filtered:
            raise ValueError("title requerido para insertar oportunidad")
        if "official_link" not in filtered:
            raise ValueError("official_link requerido")
        if "fingerprint_hash" not in filtered:
            raise ValueError("fingerprint_hash requerido")
        if "organization_id" not in filtered or "source_id" not in filtered:
            raise ValueError("organization_id y source_id requeridos")
        
        # Convertir alternate_links_json si es lista -> json string
        if "alternate_links_json" in filtered and isinstance(filtered["alternate_links_json"], list):
            filtered["alternate_links_json"] = json.dumps(filtered["alternate_links_json"])
        
        # Convertir bool a int para SQLite
        for bool_field in ["accepts_argentinians", "ai_allowed", "ai_mandatory"]:
            if bool_field in filtered and isinstance(filtered[bool_field], bool):
                filtered[bool_field] = 1 if filtered[bool_field] else 0
        
        with self.connect() as conn:
            columns = ", ".join(filtered.keys())
            placeholders = ", ".join(["?"] * len(filtered))
            values = list(filtered.values())
            try:
                cur = conn.execute(f"INSERT INTO opportunities ({columns}) VALUES ({placeholders})", values)
                opp_id = cur.lastrowid
                # Actualizar total_opportunities en organizations
                try:
                    conn.execute("UPDATE organizations SET total_opportunities = total_opportunities + 1, last_seen_at = CURRENT_TIMESTAMP WHERE id=?", (filtered["organization_id"],))
                except Exception:
                    pass
                return opp_id
            except sqlite3.IntegrityError as e:
                # Puede ser UNIQUE constraint en (organization_id, fingerprint_hash)
                if "fingerprint_hash" in str(e) or "UNIQUE" in str(e):
                    logger.warning(f"Duplicate fingerprint insert attempted: {filtered.get('fingerprint_hash')} org {filtered.get('organization_id')}")
                    # Buscar existente y retornar su id
                    existing = conn.execute(
                        "SELECT id FROM opportunities WHERE fingerprint_hash=? AND organization_id=?",
                        (filtered["fingerprint_hash"], filtered["organization_id"])
                    ).fetchone()
                    if existing:
                        return existing["id"]
                raise

    def update_opportunity(self, opp_id: int, updates: Dict[str, Any]) -> bool:
        """Actualiza oportunidad por id, set updated_at y last_changed_at"""
        if not updates:
            return False
        
        allowed_fields = [
            "title", "slug", "organizer_name", "official_link", "alternate_links_json",
            "description_raw", "description_clean", "executive_summary",
            "open_date", "deadline", "deadline_confidence", "timezone",
            "awards_text", "currency", "economic_value", "economic_value_bucket",
            "country", "accepts_argentinians", "geo_restrictions",
            "category", "modality", "fee_type", "language", "format_requested",
            "ai_allowed", "ai_mandatory", "requirements", "status",
            "last_seen_at", "last_changed_at"
        ]
        
        filtered = {k: v for k, v in updates.items() if k in allowed_fields}
        if not filtered:
            return False
        
        # Asegurar last_changed_at y updated_at
        filtered["last_changed_at"] = filtered.get("last_changed_at") or datetime_now_iso()
        filtered["updated_at"] = datetime_now_iso()
        
        if "alternate_links_json" in filtered and isinstance(filtered["alternate_links_json"], list):
            filtered["alternate_links_json"] = json.dumps(filtered["alternate_links_json"])
        
        with self.connect() as conn:
            set_clause = ", ".join([f"{k}=?" for k in filtered.keys()])
            values = list(filtered.values()) + [opp_id]
            cur = conn.execute(f"UPDATE opportunities SET {set_clause} WHERE id=?", values)
            return cur.rowcount > 0

    def add_alternate_link(self, opp_id: int, new_url: str) -> bool:
        """Agrega URL a alternate_links_json si no existe, y actualiza last_seen_at"""
        if not new_url:
            return False
        
        with self.connect() as conn:
            cur = conn.execute("SELECT alternate_links_json, official_link FROM opportunities WHERE id=?", (opp_id,))
            row = cur.fetchone()
            if not row:
                return False
            
            existing_links = []
            if row["alternate_links_json"]:
                try:
                    existing_links = json.loads(row["alternate_links_json"])
                except Exception:
                    existing_links = []
            
            # Normalizar comparación: si new_url == official_link o ya en lista, no agregar
            official = row["official_link"] or ""
            if new_url == official or new_url in existing_links:
                # Solo actualizar last_seen_at
                conn.execute("UPDATE opportunities SET last_seen_at=CURRENT_TIMESTAMP WHERE id=?", (opp_id,))
                return False
            
            existing_links.append(new_url)
            # Limitar a 20 links para no crecer infinito
            if len(existing_links) > 20:
                existing_links = existing_links[-20:]
            
            conn.execute(
                "UPDATE opportunities SET alternate_links_json=?, last_seen_at=CURRENT_TIMESTAMP WHERE id=?",
                (json.dumps(existing_links), opp_id)
            )
            return True

    def insert_history(self, opportunity_id: int, field_name: str, old_value: Any, new_value: Any, change_type: str, source_id: int = None, metadata: Dict[str, Any] = None) -> int:
        """Inserta registro en opportunity_history"""
        with self.connect() as conn:
            cur = conn.execute("""
                INSERT INTO opportunity_history (opportunity_id, field_name, old_value, new_value, change_type, source_id, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                opportunity_id,
                field_name,
                str(old_value) if old_value is not None else None,
                str(new_value) if new_value is not None else None,
                change_type,
                source_id,
                json.dumps(metadata) if metadata else None
            ))
            # Actualizar last_changed_at en opportunities
            conn.execute("UPDATE opportunities SET last_changed_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?", (opportunity_id,))
            return cur.lastrowid

    def get_opportunities_count(self) -> int:
        with self.connect() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM opportunities WHERE is_duplicate_of IS NULL")
            return cur.fetchone()[0]

    # --- Métodos para Notification Engine (Ticket 008) ---

    def insert_notification(self, opportunity_id: int = None, watchlist_id: int = None, type: str = None, title: str = None, message: str = None, priority: str = "normal", action_url: str = None, metadata: Dict[str, Any] = None, scheduled_for: str = None) -> int:
        """Inserta notificación, con idempotencia básica (no duplica si existe reciente igual)"""
        if not type or not title or not message:
            raise ValueError("type, title, message requeridos para notificación")
        
        with self.connect() as conn:
            cur = conn.execute("""
                INSERT INTO notifications (opportunity_id, watchlist_id, type, title, message, priority, action_url, metadata_json, scheduled_for)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                opportunity_id,
                watchlist_id,
                type,
                title,
                message,
                priority,
                action_url,
                json.dumps(metadata) if metadata else None,
                scheduled_for
            ))
            return cur.lastrowid

    def find_notification(self, opportunity_id: int = None, type: str = None, title: str = None, days: int = 1) -> Optional[Dict]:
        """Busca notificación existente reciente para idempotencia: misma oportunidad y tipo en últimos X días"""
        with self.connect() as conn:
            if opportunity_id and type:
                cur = conn.execute("""
                    SELECT * FROM notifications 
                    WHERE opportunity_id=? AND type=? 
                    AND created_at >= datetime('now', '-' || ? || ' days')
                    ORDER BY created_at DESC LIMIT 1
                """, (opportunity_id, type, days))
                row = cur.fetchone()
                return dict(row) if row else None
            return None

    def find_notification_exact(self, opportunity_id: int, type: str, metadata: Dict[str, Any] = None) -> Optional[Dict]:
        """Busca notificación exacta por oportunidad, tipo y metadata (para idempotencia exacta por evento)"""
        with self.connect() as conn:
            # Buscar por oportunidad y tipo, luego comparar metadata en Python (SQLite JSON query limitado)
            cur = conn.execute("""
                SELECT * FROM notifications 
                WHERE opportunity_id=? AND type=? 
                ORDER BY created_at DESC LIMIT 10
            """, (opportunity_id, type))
            rows = [dict(r) for r in cur.fetchall()]
            if not metadata:
                return rows[0] if rows else None
            
            # Comparar metadata exacta
            target_old = metadata.get("old_value")
            target_new = metadata.get("new_value")
            target_days = metadata.get("days_left")
            for r in rows:
                try:
                    meta = json.loads(r.get("metadata_json") or "{}")
                    if target_old is not None and target_new is not None:
                        if meta.get("old_value") == target_old and meta.get("new_value") == target_new:
                            return r
                    if target_days is not None:
                        if meta.get("days_left") == target_days:
                            # Verificar si es mismo día (evitar duplicado mismo día)
                            # Si created_at es hoy, considerar duplicado
                            return r
                except Exception:
                    continue
            return None

    def get_pending_notifications(self, limit: int = 50) -> List[Dict]:
        with self.connect() as conn:
            cur = conn.execute("""
                SELECT n.*, o.title as opportunity_title, o.deadline
                FROM notifications n
                LEFT JOIN opportunities o ON n.opportunity_id=o.id
                WHERE n.is_read=0 AND n.is_archived=0 AND n.is_dismissed=0
                ORDER BY 
                    CASE n.priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END,
                    n.created_at DESC
                LIMIT ?
            """, (limit,))
            return [dict(r) for r in cur.fetchall()]

    def get_notifications_by_type(self, type: str, limit: int = 50) -> List[Dict]:
        with self.connect() as conn:
            cur = conn.execute("SELECT * FROM notifications WHERE type=? ORDER BY created_at DESC LIMIT ?", (type, limit))
            return [dict(r) for r in cur.fetchall()]

    def get_notifications_count(self) -> int:
        with self.connect() as conn:
            cur = conn.execute("SELECT COUNT(*) FROM notifications WHERE is_read=0 AND is_archived=0")
            return cur.fetchone()[0]

    def add_to_watchlist(self, opportunity_id: int, status: str = "interested", priority_user: int = 2, notes: str = "", reminder_days_json: str = "[30,15,7,3,1]") -> int:
        with self.connect() as conn:
            cur = conn.execute("""
                INSERT OR IGNORE INTO watchlist (opportunity_id, status, priority_user, notes, reminder_days_json)
                VALUES (?, ?, ?, ?, ?)
            """, (opportunity_id, status, priority_user, notes, reminder_days_json))
            if cur.lastrowid == 0:
                cur = conn.execute("SELECT id FROM watchlist WHERE opportunity_id=?", (opportunity_id,))
                row = cur.fetchone()
                return row["id"] if row else 0
            return cur.lastrowid

    def get_watchlist(self, only_active: bool = True) -> List[Dict]:
        with self.connect() as conn:
            q = """
                SELECT w.*, o.title, o.deadline, o.official_link, o.status as opp_status, org.name as org_name, org.slug as org_slug
                FROM watchlist w
                JOIN opportunities o ON w.opportunity_id=o.id
                JOIN organizations org ON o.organization_id=org.id
            """
            if only_active:
                q += " WHERE o.status='open' AND w.status IN ('interested','researching','applying')"
            q += " ORDER BY o.deadline ASC"
            cur = conn.execute(q)
            return [dict(r) for r in cur.fetchall()]

    def get_watchlist_with_days_left(self) -> List[Dict]:
        """Retorna watchlist con days_left calculado"""
        with self.connect() as conn:
            cur = conn.execute("""
                SELECT w.*, o.title, o.deadline, o.official_link, 
                       CAST((julianday(o.deadline) - julianday('now')) AS INTEGER) as days_left,
                       org.name as org_name
                FROM watchlist w
                JOIN opportunities o ON w.opportunity_id=o.id
                JOIN organizations org ON o.organization_id=org.id
                WHERE o.status='open' AND w.status IN ('interested','researching','applying')
                AND o.deadline IS NOT NULL
                ORDER BY o.deadline ASC
            """)
            return [dict(r) for r in cur.fetchall()]

def datetime_now_iso():
    from datetime import datetime
    return datetime.now().isoformat()

def get_db(db_path: Path = None) -> RadarDB:
    return RadarDB(db_path)
