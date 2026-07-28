"""
Radar - History Tracker (Change Tracker)
Ticket 006: Registrar cambios campo por campo

Objetivo: Detectar cambios en oportunidades y escribir en opportunity_history
Toda oportunidad debe recorrer: Provider -> Normalize -> Fingerprint -> Database -> Logs
Este módulo es el que registra cambios en Database y produce Logs

Debe:
- comparar old vs new
- detectar campo por campo
- generar change_type (deadline_extended, deadline_shortened, prize_updated, status_changed, info_updated, etc)
- insertar en opportunity_history
- no romper si no hay cambios
"""
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, date
import json

from core.logger import get_logger

logger = get_logger("core")

# Campos críticos a trackear
TRACKED_FIELDS = [
    "title",
    "deadline",
    "awards_text",
    "economic_value",
    "currency",
    "status",
    "official_link",
    "description_raw",
    "description_clean",
    "organizer_name",
    "country",
    "category",
    "opportunity_type"
]

def _parse_deadline(value: Any) -> Optional[date]:
    """Parsea deadline a date para comparación, retorna None si no parseable"""
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            # Intentar ISO
            from dateutil import parser
            dt = parser.parse(value, fuzzy=True)
            return dt.date()
        except Exception:
            try:
                # Intentar solo YYYY-MM-DD
                return date.fromisoformat(value.split("T")[0].split(" ")[0])
            except Exception:
                return None
    return None

def _get_change_type(field: str, old: Any, new: Any) -> str:
    """Determina change_type basado en field y valores"""
    if field == "deadline":
        old_date = _parse_deadline(old)
        new_date = _parse_deadline(new)
        if old_date and new_date:
            if new_date > old_date:
                return "deadline_extended"
            elif new_date < old_date:
                return "deadline_shortened"
            else:
                return "info_updated"
        return "info_updated"
    
    if field in ("awards_text", "economic_value", "currency"):
        return "prize_updated"
    
    if field == "status":
        return "status_changed"
    
    return "info_updated"

@dataclass
class FieldChange:
    field_name: str
    old_value: Any
    new_value: Any
    change_type: str

    def to_dict(self):
        return {
            "field_name": self.field_name,
            "old_value": str(self.old_value) if self.old_value is not None else None,
            "new_value": str(self.new_value) if self.new_value is not None else None,
            "change_type": self.change_type
        }

class HistoryTracker:
    """
    Tracker que compara oportunidades old vs new y registra cambios
    Core agnóstico, sin reglas org específicas
    """
    
    def __init__(self, tracked_fields: List[str] = None):
        self.tracked_fields = tracked_fields or TRACKED_FIELDS
    
    def detect_changes(self, old: Dict[str, Any], new: Dict[str, Any]) -> List[FieldChange]:
        """
        Compara old vs new dict y retorna lista de FieldChange
        Solo compara tracked_fields
        Fix 1 (Ticket 010 observación): normalizar economic_value para evitar updates falsos 2500.0 -> 2500
        """
        changes = []
        for field in self.tracked_fields:
            old_val = old.get(field)
            new_val = new.get(field)
            
            # Normalizar None vs "" como iguales si ambos vacíos
            old_norm = "" if old_val is None else str(old_val).strip()
            new_norm = "" if new_val is None else str(new_val).strip()
            
            # Si ambos vacíos, no hay cambio
            if not old_norm and not new_norm:
                continue
            
            # Caso especial: economic_value - comparar numéricamente para evitar 2500.0 vs 2500 falsos
            if field == "economic_value":
                try:
                    # Ambos vacíos ya manejados arriba
                    if old_val is None or new_val is None:
                        # Si uno es None y otro no, es cambio real
                        if (old_val is None) != (new_val is None):
                            pass  # Continuar a detectar cambio
                        else:
                            continue  # Ambos None -> no cambio
                    else:
                        old_float = float(old_val)
                        new_float = float(new_val)
                        # Comparar con tolerancia pequeña para floats
                        if abs(old_float - new_float) < 0.01:
                            continue  # Mismo valor numérico, no cambio aunque representación string diferente
                except (ValueError, TypeError):
                    # Si no se pueden parsear como float, caer a comparación string normal
                    pass
            
            # Si son iguales (case-sensitive? Para deadline comparar dates, para otros string exact)
            if field == "deadline":
                old_date = _parse_deadline(old_val)
                new_date = _parse_deadline(new_val)
                if old_date == new_date:
                    continue
                # Si uno None y otro no, es cambio
                if old_date is None and new_date is None:
                    continue
            else:
                # Para campos no numéricos, comparar string normalizado
                # Para economic_value ya manejado arriba con float, si llegó aquí es porque son diferentes numéricamente o no parseables
                if field != "economic_value" and old_norm == new_norm:
                    continue
            
            change_type = _get_change_type(field, old_val, new_val)
            changes.append(FieldChange(
                field_name=field,
                old_value=old_val,
                new_value=new_val,
                change_type=change_type
            ))
        
        return changes
    
    def has_significant_changes(self, changes: List[FieldChange]) -> bool:
        """¿Hay cambios significativos que ameritan notificación?"""
        significant_types = {"deadline_extended", "deadline_shortened", "prize_updated", "status_changed"}
        return any(c.change_type in significant_types for c in changes)
    
    def format_changes_for_log(self, changes: List[FieldChange]) -> str:
        """Formatea cambios para log legible"""
        if not changes:
            return "No changes"
        parts = []
        for c in changes:
            parts.append(f"{c.field_name}: {str(c.old_value)[:30]} -> {str(c.new_value)[:30]} ({c.change_type})")
        return "; ".join(parts)

# Singleton conveniencia
_tracker_instance = None

def get_history_tracker() -> HistoryTracker:
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = HistoryTracker()
    return _tracker_instance

def detect_changes(old: Dict[str, Any], new: Dict[str, Any]) -> List[FieldChange]:
    """Helper que usa singleton"""
    return get_history_tracker().detect_changes(old, new)
