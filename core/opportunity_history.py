"""
Radar - Opportunity History System (Ticket 007)
Construir el sistema de historial.

Cada oportunidad debe conservar:
- primera aparición (first_seen_at)
- última aparición (last_seen_at)
- cambios de deadline
- cambios de URL (official_link y alternate_links)
- cambios de estado
- cambios de descripción
Nunca perder historial. Registrar cada modificación como evento.

Validación: Simular cambios y verificar historial correcto.

Arquitectura:
- first_seen_at: nunca se actualiza, se setea en INSERT
- last_seen_at: se actualiza cada vez que se ve la oportunidad (incluso sin cambios)
- last_changed_at: se actualiza cuando hay cambios significativos
- opportunity_history: cada cambio es un evento con field_name, old_value, new_value, change_type, detected_at, source_id, metadata
- Nunca perder historial: nunca DELETE de opportunities ni history, solo UPDATE status a closed. FK ON DELETE CASCADE en schema pero no usamos DELETE en código.
- Transacción atómica por oportunidad (ya implementada en monitoring_engine): BEGIN -> update opp + insert history + alternate_links -> COMMIT
- Idempotencia: history no duplica si mismo cambio ya existe reciente, alternate_links solo agrega si no existe
"""
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import json

from core.logger import get_logger
from core.db import get_db
from core.history import HistoryTracker, get_history_tracker

logger = get_logger("core")

# Campos que deben conservarse en historial según Ticket 007
HISTORY_REQUIRED_FIELDS = [
    "deadline",           # cambios de deadline
    "official_link",      # cambios de URL oficial
    "alternate_links",    # cambios de URL alternas (agregadas)
    "status",             # cambios de estado
    "description_raw",    # cambios de descripción
    "description_clean",  # cambios de descripción limpia
    "title",              # cambios de título (también importante)
    "awards_text",        # cambios de premio
    "economic_value",     # cambios de premio económico
]

@dataclass
class HistoryEvent:
    opportunity_id: int
    field_name: str
    old_value: Any
    new_value: Any
    change_type: str
    detected_at: str
    source_id: Optional[int] = None
    metadata: Dict[str, Any] = None

class OpportunityHistorySystem:
    """
    Sistema de historial que nunca pierde eventos
    """
    
    def __init__(self, db=None, tracker=None):
        self.db = db or get_db()
        self.tracker = tracker or get_history_tracker()
        self.logger = logger
    
    def record_first_appearance(self, opportunity_id: int, source_id: int = None, metadata: Dict[str, Any] = None) -> int:
        """
        Registra primera aparición como evento created
        first_seen_at ya está seteado por DB DEFAULT CURRENT_TIMESTAMP en INSERT, no se actualiza
        """
        try:
            with self.db.connect() as conn:
                # Verificar si ya tiene evento created (idempotencia)
                cur = conn.execute("""
                    SELECT id FROM opportunity_history 
                    WHERE opportunity_id=? AND change_type='created' 
                    LIMIT 1
                """, (opportunity_id,))
                if cur.fetchone():
                    self.logger.debug(f"First appearance already recorded for opp {opportunity_id}, skipping")
                    return 0
                
                cur = conn.execute("""
                    INSERT INTO opportunity_history (opportunity_id, field_name, old_value, new_value, change_type, source_id, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    opportunity_id,
                    "first_seen",
                    None,
                    datetime.now().isoformat(),
                    "created",
                    source_id,
                    json.dumps(metadata) if metadata else None
                ))
                self.logger.info(f"[HISTORY] First appearance recorded for opp {opportunity_id}")
                return cur.lastrowid
        except Exception as e:
            self.logger.error(f"Failed to record first appearance for opp {opportunity_id}: {e}")
            return 0
    
    def record_last_appearance(self, opportunity_id: int):
        """
        Actualiza last_seen_at a ahora, sin crear evento history (solo timestamp)
        last_seen_at se actualiza cada vez que se ve la oportunidad
        """
        try:
            with self.db.connect() as conn:
                conn.execute("UPDATE opportunities SET last_seen_at=CURRENT_TIMESTAMP WHERE id=?", (opportunity_id,))
        except Exception as e:
            self.logger.warning(f"Failed to record last appearance for opp {opportunity_id}: {e}")
    
    def record_change(self, opportunity_id: int, field_name: str, old_value: Any, new_value: Any, change_type: str = None, source_id: int = None, metadata: Dict[str, Any] = None, conn=None) -> int:
        """
        Registra cambio como evento. Si conn proporcionado, usa esa transacción (para atomicidad)
        Si no, crea nueva conexión
        Idempotente: no duplica si mismo cambio ya existe reciente
        """
        # Determinar change_type si no proporcionado
        if not change_type:
            from core.history import _get_change_type
            change_type = _get_change_type(field_name, old_value, new_value)
        
        # Idempotencia: verificar último evento mismo campo/valores
        try:
            if conn:
                cur = conn.execute("""
                    SELECT old_value, new_value FROM opportunity_history 
                    WHERE opportunity_id=? AND field_name=? 
                    ORDER BY detected_at DESC LIMIT 1
                """, (opportunity_id, field_name))
            else:
                with self.db.connect() as c:
                    cur = c.execute("""
                        SELECT old_value, new_value FROM opportunity_history 
                        WHERE opportunity_id=? AND field_name=? 
                        ORDER BY detected_at DESC LIMIT 1
                    """, (opportunity_id, field_name))
                    last = cur.fetchone()
                    if last and str(last["old_value"]) == str(old_value) and str(last["new_value"]) == str(new_value):
                        self.logger.debug(f"[HISTORY] Skipping duplicate history for opp {opportunity_id} field {field_name}")
                        return 0
                    # Insertar en nueva conexión si no hay conn proporcionado
                    with self.db.connect() as c2:
                        cur2 = c2.execute("""
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
                        return cur2.lastrowid
            
            # Si conn proporcionado, usarlo (para transacción atómica)
            if conn:
                # Verificar duplicado dentro de misma transacción
                cur = conn.execute("""
                    SELECT old_value, new_value FROM opportunity_history 
                    WHERE opportunity_id=? AND field_name=? 
                    ORDER BY detected_at DESC LIMIT 1
                """, (opportunity_id, field_name))
                last = cur.fetchone()
                if last and str(last["old_value"]) == str(old_value) and str(last["new_value"]) == str(new_value):
                    return 0
                
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
                return cur.lastrowid
        
        except Exception as e:
            self.logger.error(f"Failed to record change for opp {opportunity_id} field {field_name}: {e}")
            return 0
    
    def record_deadline_change(self, opportunity_id: int, old_deadline: Any, new_deadline: Any, source_id: int = None, metadata: Dict[str, Any] = None) -> int:
        """Registra cambio de deadline como evento específico"""
        from core.history import _get_change_type
        change_type = _get_change_type("deadline", old_deadline, new_deadline)
        return self.record_change(opportunity_id, "deadline", old_deadline, new_deadline, change_type, source_id, metadata)
    
    def record_url_change(self, opportunity_id: int, old_url: str, new_url: str, source_id: int = None, metadata: Dict[str, Any] = None, is_alternate: bool = False) -> int:
        """Registra cambio de URL (official o alternate)"""
        field_name = "alternate_links" if is_alternate else "official_link"
        change_type = "info_updated"
        if is_alternate:
            # Para alternate, old es lista existente, new es nueva URL agregada
            return self.record_change(opportunity_id, field_name, old_url, new_url, change_type, source_id, metadata)
        else:
            return self.record_change(opportunity_id, field_name, old_url, new_url, change_type, source_id, metadata)
    
    def record_status_change(self, opportunity_id: int, old_status: str, new_status: str, source_id: int = None, metadata: Dict[str, Any] = None) -> int:
        """Registra cambio de estado"""
        return self.record_change(opportunity_id, "status", old_status, new_status, "status_changed", source_id, metadata)
    
    def record_description_change(self, opportunity_id: int, old_desc: str, new_desc: str, source_id: int = None, metadata: Dict[str, Any] = None, field: str = "description_raw") -> int:
        """Registra cambio de descripción"""
        return self.record_change(opportunity_id, field, old_desc, new_desc, "info_updated", source_id, metadata)
    
    def get_history(self, opportunity_id: int, field_name: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Obtiene historial de una oportunidad, opcionalmente filtrado por campo, ordenado por fecha"""
        try:
            with self.db.connect() as conn:
                if field_name:
                    cur = conn.execute("""
                        SELECT * FROM opportunity_history 
                        WHERE opportunity_id=? AND field_name=? 
                        ORDER BY detected_at ASC, id ASC LIMIT ?
                    """, (opportunity_id, field_name, limit))
                else:
                    cur = conn.execute("""
                        SELECT * FROM opportunity_history 
                        WHERE opportunity_id=? 
                        ORDER BY detected_at ASC, id ASC LIMIT ?
                    """, (opportunity_id, limit))
                return [dict(r) for r in cur.fetchall()]
        except Exception as e:
            self.logger.error(f"Failed to get history for opp {opportunity_id}: {e}")
            return []
    
    def get_first_appearance(self, opportunity_id: int) -> Optional[Dict[str, Any]]:
        """Obtiene primera aparición"""
        try:
            with self.db.connect() as conn:
                cur = conn.execute("SELECT first_seen_at FROM opportunities WHERE id=?", (opportunity_id,))
                row = cur.fetchone()
                if row:
                    # Buscar evento created
                    cur2 = conn.execute("""
                        SELECT * FROM opportunity_history 
                        WHERE opportunity_id=? AND change_type='created' 
                        ORDER BY detected_at ASC LIMIT 1
                    """, (opportunity_id,))
                    created_event = cur2.fetchone()
                    return {
                        "first_seen_at": row["first_seen_at"],
                        "created_event": dict(created_event) if created_event else None
                    }
        except Exception as e:
            self.logger.error(f"Failed to get first appearance for opp {opportunity_id}: {e}")
        return None
    
    def get_last_appearance(self, opportunity_id: int) -> Optional[Dict[str, Any]]:
        """Obtiene última aparición"""
        try:
            with self.db.connect() as conn:
                cur = conn.execute("SELECT last_seen_at, last_changed_at FROM opportunities WHERE id=?", (opportunity_id,))
                row = cur.fetchone()
                if row:
                    return {
                        "last_seen_at": row["last_seen_at"],
                        "last_changed_at": row["last_changed_at"]
                    }
        except Exception as e:
            self.logger.error(f"Failed to get last appearance for opp {opportunity_id}: {e}")
        return None
    
    def never_lose_history(self, opportunity_id: int) -> bool:
        """
        Verifica que nunca se pierda historial: incluso si oportunidad se marca closed, history debe permanecer
        Retorna True si history existe y no se perdió
        """
        try:
            with self.db.connect() as conn:
                cur = conn.execute("SELECT COUNT(*) as c FROM opportunity_history WHERE opportunity_id=?", (opportunity_id,))
                count = cur.fetchone()["c"]
                return count >= 1  # Al menos evento created
        except Exception:
            return False

# Singleton
_history_system_instance = None

def get_opportunity_history_system(db=None) -> OpportunityHistorySystem:
    global _history_system_instance
    if _history_system_instance is None:
        _history_system_instance = OpportunityHistorySystem(db=db)
    return _history_system_instance
