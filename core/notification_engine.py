"""
Radar - Notification Engine (Ticket 008)

Construir el motor de notificaciones.

Debe soportar:
- nuevas oportunidades
- deadline cambiado
- deadline próximo
- oportunidad cerrada
- watchlist

Inicialmente solamente salida por consola y logs.

Validación: Simular múltiples escenarios, verificar que cada evento genere exactamente una notificación.

Arquitectura:
- Cada evento genera exactamente una notificación (idempotencia)
- Salida por consola (rich) y logs (logs/notifications.log o monitor.log)
- No email todavía (solo db + log)
- Integración con Monitoring Engine y History Tracker: cuando se detecta nuevo, deadline cambiado, status cerrado, etc, se llama a notification_engine
- Watchlist: deadline próximo T-30,15,7,3,1 genera reminder

Tipos de notificaciones (según schema):
- new_opportunity
- deadline_changed
- deadline_reminder
- prize_updated (no requerido en ticket pero útil)
- status_closed
- status_postponed
- watchlist_digest
- system_digest
"""

from typing import Dict, List, Any, Optional
from datetime import datetime, date
import json
from pathlib import Path

from core.logger import get_logger
from core.config import get_config
from core.db import get_db

logger = get_logger("monitor")  # Usa monitor log para notificaciones, o crear notifications logger
notifications_logger = get_logger("core")  # Para logs separados si existe logs/notifications.log mapeado como core.log, usamos monitor por ahora

# Intentar obtener logger específico para notifications si existe file mapping
try:
    from core.logger import setup_logger
    notif_logger = setup_logger("notifications", "notifications.log", "INFO")
except Exception:
    notif_logger = logger

class NotificationEngine:
    """
    Motor de notificaciones con idempotencia: cada evento genera exactamente una notificación
    """
    
    def __init__(self, db=None, config=None):
        self.config = config or get_config()
        self.db = db or get_db()
        self.logger = notif_logger
        self.console_logger = logger
    
    def _log_notification(self, notif: Dict[str, Any], created: bool):
        """Log por consola y archivo, solo si se creó nueva notificación"""
        if not created:
            return
        
        title = notif.get("title", "")
        message = notif.get("message", "")
        ntype = notif.get("type", "")
        priority = notif.get("priority", "normal")
        opp_id = notif.get("opportunity_id")
        
        # Log con nivel según prioridad
        log_msg = f"[{ntype.upper()}][{priority}] Opp {opp_id}: {title} - {message}"
        
        if priority == "urgent":
            self.logger.error(log_msg)
        elif priority == "high":
            self.logger.warning(log_msg)
        else:
            self.logger.info(log_msg)
        
        # También log en notif_logger si es diferente
        if notif_logger != self.logger:
            notif_logger.info(log_msg)
    
    def _check_idempotence(self, opportunity_id: int, type: str, metadata: Dict[str, Any] = None) -> bool:
        """
        Verifica si notificación ya existe para mismo evento (idempotencia)
        Retorna True si ya existe (no crear duplicado), False si no existe (crear)
        """
        if not opportunity_id or not type:
            return False
        
        try:
            # Para new_opportunity: solo una por oportunidad ever
            if type == "new_opportunity":
                existing = self.db.find_notification(opportunity_id=opportunity_id, type=type, days=3650)  # 10 años
                return existing is not None
            
            # Para deadline_changed: verificar si mismo old->new ya notificado
            if type == "deadline_changed":
                if metadata:
                    existing = self.db.find_notification_exact(opportunity_id, type, metadata)
                    return existing is not None
                # Si no hay metadata, verificar si ya hay notificación reciente (últimas 24h) para mismo opp y tipo
                existing = self.db.find_notification(opportunity_id=opportunity_id, type=type, days=1)
                if existing:
                    # Si old/new en metadata coinciden, es duplicado
                    if metadata:
                        try:
                            meta_existing = json.loads(existing.get("metadata_json") or "{}")
                            if meta_existing.get("old_value") == metadata.get("old_value") and meta_existing.get("new_value") == metadata.get("new_value"):
                                return True
                        except Exception:
                            pass
                    else:
                        return True
            
            # Para deadline_reminder: verificar si ya se notificó hoy mismo para mismos days_left
            if type == "deadline_reminder":
                if metadata and "days_left" in metadata:
                    existing = self.db.find_notification_exact(opportunity_id, type, metadata)
                    if existing:
                        # Verificar si created_at es hoy
                        try:
                            created = existing.get("created_at", "")
                            # Si created hoy, no duplicar
                            today = datetime.now().date().isoformat()
                            if today in created:
                                return True
                        except Exception:
                            return True
            
            # Para status_closed: solo una por oportunidad
            if type == "status_closed":
                existing = self.db.find_notification(opportunity_id=opportunity_id, type=type, days=3650)
                return existing is not None
            
            # Para watchlist: verificar si ya hay reminder hoy para mismos days_left
            if type == "watchlist_digest" or type == "deadline_reminder":
                # Similar a deadline_reminder
                if metadata and "days_left" in metadata:
                    existing = self.db.find_notification_exact(opportunity_id, type, metadata)
                    if existing:
                        # Verificar si es hoy
                        try:
                            created = existing.get("created_at", "")
                            today = datetime.now().date().isoformat()
                            if today in created:
                                return True
                        except Exception:
                            pass
            
            return False
        
        except Exception as e:
            self.logger.warning(f"Idempotence check failed for opp {opportunity_id} type {type}: {e}, allowing creation")
            return False
    
    def create_notification(self, opportunity_id: int = None, type: str = None, title: str = None, message: str = None, priority: str = "normal", action_url: str = None, metadata: Dict[str, Any] = None, watchlist_id: int = None, scheduled_for: str = None) -> Optional[Dict[str, Any]]:
        """
        Crea notificación con idempotencia: cada evento genera exactamente una notificación
        Retorna dict notificación si creada, None si ya existía (idempotente)
        """
        if not type or not title or not message:
            self.logger.error(f"Cannot create notification: type, title, message required, got type={type} title={title}")
            return None
        
        # Idempotencia: verificar si ya existe
        if self._check_idempotence(opportunity_id, type, metadata):
            self.logger.debug(f"[NOTIF] Idempotence: notification already exists for opp {opportunity_id} type {type} metadata={metadata}, skipping")
            return None
        
        try:
            notif_id = self.db.insert_notification(
                opportunity_id=opportunity_id,
                watchlist_id=watchlist_id,
                type=type,
                title=title,
                message=message,
                priority=priority,
                action_url=action_url,
                metadata=metadata,
                scheduled_for=scheduled_for
            )
            
            # Obtener notificación recién creada para log
            with self.db.connect() as conn:
                cur = conn.execute("SELECT * FROM notifications WHERE id=?", (notif_id,))
                row = cur.fetchone()
                notif = dict(row) if row else {"id": notif_id, "opportunity_id": opportunity_id, "type": type, "title": title, "message": message, "priority": priority}
            
            self._log_notification(notif, created=True)
            
            return notif
        
        except Exception as e:
            self.logger.error(f"Failed to create notification opp {opportunity_id} type {type}: {e}", exc_info=True)
            return None
    
    # --- Métodos específicos por tipo de evento ---
    
    def notify_new_opportunity(self, opportunity: Dict[str, Any], source: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """Nueva oportunidad detectada"""
        opp_id = opportunity.get("id")
        title = opportunity.get("title", "Nueva oportunidad")
        org_name = opportunity.get("org_name") or opportunity.get("organizer_name") or "Organización"
        deadline = opportunity.get("deadline", "sin fecha")
        
        notif_title = f"Nueva oportunidad: {title}"
        notif_message = f"{org_name} publicó '{title}' con deadline {deadline}. Score alto o en fuente prioritaria."
        if source:
            notif_message += f" Fuente: {source.get('url', '')}"
        
        return self.create_notification(
            opportunity_id=opp_id,
            type="new_opportunity",
            title=notif_title,
            message=notif_message,
            priority="normal",
            action_url=opportunity.get("official_link"),
            metadata={
                "org_name": org_name,
                "deadline": str(deadline),
                "source_url": source.get("url") if source else None,
                "fingerprint": opportunity.get("fingerprint_hash")
            }
        )
    
    def notify_deadline_changed(self, opportunity_id: int, old_deadline: str, new_deadline: str, change_type: str = None, opportunity: Dict[str, Any] = None, source_id: int = None) -> Optional[Dict[str, Any]]:
        """Deadline cambiado (extendido o acortado)"""
        if not old_deadline or not new_deadline:
            return None
        
        # Determinar si extendido o acortado si no proporcionado
        if not change_type:
            try:
                from dateutil import parser
                old_dt = parser.parse(str(old_deadline), fuzzy=True)
                new_dt = parser.parse(str(new_deadline), fuzzy=True)
                change_type = "deadline_extended" if new_dt > old_dt else "deadline_shortened"
            except Exception:
                change_type = "deadline_extended" if str(new_deadline) > str(old_deadline) else "deadline_shortened"
        
        opp_title = opportunity.get("title", f"Opp {opportunity_id}") if opportunity else f"Opp {opportunity_id}"
        
        if change_type == "deadline_extended":
            notif_title = f"Deadline extendido: {opp_title}"
            notif_message = f"¡Buenas noticias! '{opp_title}' extendió deadline de {old_deadline} a {new_deadline}. Tenés más tiempo."
            priority = "high"
        else:
            notif_title = f"Deadline acortado: {opp_title}"
            notif_message = f"Atención: '{opp_title}' acortó deadline de {old_deadline} a {new_deadline}. ¡Apurate!"
            priority = "urgent"
        
        return self.create_notification(
            opportunity_id=opportunity_id,
            type="deadline_changed",
            title=notif_title,
            message=notif_message,
            priority=priority,
            action_url=opportunity.get("official_link") if opportunity else None,
            metadata={
                "old_value": str(old_deadline),
                "new_value": str(new_deadline),
                "old_deadline": str(old_deadline),
                "new_deadline": str(new_deadline),
                "change_type": change_type,
                "source_id": source_id
            }
        )
    
    def notify_deadline_upcoming(self, opportunity_id: int, days_left: int, opportunity: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """Deadline próximo (para cualquier oportunidad, no solo watchlist)"""
        if days_left is None or days_left < 0:
            return None
        
        opp_title = opportunity.get("title", f"Opp {opportunity_id}") if opportunity else f"Opp {opportunity_id}"
        deadline = opportunity.get("deadline", "") if opportunity else ""
        
        if days_left <= 1:
            notif_title = f"¡Último día! {opp_title}"
            notif_message = f"'{opp_title}' cierra {deadline} - te queda {days_left} día. ¡Última oportunidad!"
            priority = "urgent"
        elif days_left <= 3:
            notif_title = f"Deadline en {days_left} días: {opp_title}"
            notif_message = f"'{opp_title}' cierra en {days_left} días ({deadline}). Apurate a presentar."
            priority = "high"
        elif days_left <= 7:
            notif_title = f"Deadline en {days_left} días: {opp_title}"
            notif_message = f"'{opp_title}' cierra en {days_left} días ({deadline})."
            priority = "high"
        else:
            notif_title = f"Deadline en {days_left} días: {opp_title}"
            notif_message = f"'{opp_title}' cierra en {days_left} días ({deadline}). Queda tiempo pero no lo dejes."
            priority = "normal"
        
        return self.create_notification(
            opportunity_id=opportunity_id,
            type="deadline_reminder",
            title=notif_title,
            message=notif_message,
            priority=priority,
            action_url=opportunity.get("official_link") if opportunity else None,
            metadata={
                "days_left": days_left,
                "deadline": str(deadline)
            }
        )
    
    def notify_status_closed(self, opportunity_id: int, old_status: str = None, new_status: str = None, opportunity: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """Oportunidad cerrada"""
        opp_title = opportunity.get("title", f"Opp {opportunity_id}") if opportunity else f"Opp {opportunity_id}"
        
        notif_title = f"Cerrada: {opp_title}"
        notif_message = f"'{opp_title}' cambió de {old_status or 'open'} a {new_status or 'closed'}. Ya no se puede aplicar."
        if new_status == "closed":
            notif_message += " Revisa historial por si reabre."
        
        return self.create_notification(
            opportunity_id=opportunity_id,
            type="status_closed",
            title=notif_title,
            message=notif_message,
            priority="normal",
            action_url=opportunity.get("official_link") if opportunity else None,
            metadata={
                "old_value": old_status,
                "new_value": new_status,
                "old_status": old_status,
                "new_status": new_status
            }
        )
    
    def notify_watchlist_reminder(self, opportunity_id: int, watchlist_id: int, days_left: int, opportunity: Dict[str, Any] = None, watchlist_entry: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """Watchlist: deadline próximo para oportunidad en watchlist (recordatorio personalizado)"""
        if days_left is None or days_left < 0:
            return None
        
        opp_title = opportunity.get("title", f"Opp {opportunity_id}") if opportunity else f"Opp {opportunity_id}"
        org_name = opportunity.get("org_name") or opportunity.get("organizer_name") or ""
        
        if days_left <= 1:
            notif_title = f"[Watchlist] ¡Último día! {opp_title}"
            notif_message = f"Tu watchlist '{opp_title}' ({org_name}) cierra en {days_left} día. ¡Última oportunidad para {watchlist_entry.get('status','interested')}!"
            priority = "urgent"
        elif days_left <= 3:
            notif_title = f"[Watchlist] {days_left} días: {opp_title}"
            notif_message = f"Tu watchlist '{opp_title}' cierra en {days_left} días. Estado: {watchlist_entry.get('status','interested') if watchlist_entry else 'interested'}"
            priority = "urgent"
        else:
            notif_title = f"[Watchlist] {days_left} días: {opp_title}"
            notif_message = f"Recordatorio watchlist: '{opp_title}' cierra en {days_left} días. Org: {org_name}"
            priority = "high" if days_left <= 7 else "normal"
        
        return self.create_notification(
            opportunity_id=opportunity_id,
            watchlist_id=watchlist_id,
            type="deadline_reminder",  # Usamos mismo tipo pero con watchlist_id para distinguir
            title=notif_title,
            message=notif_message,
            priority=priority,
            action_url=opportunity.get("official_link") if opportunity else None,
            metadata={
                "days_left": days_left,
                "watchlist_status": watchlist_entry.get("status") if watchlist_entry else "interested",
                "org_name": org_name,
                "is_watchlist": True
            }
        )
    
    def check_watchlist_reminders(self, days_thresholds: List[int] = None) -> List[Dict[str, Any]]:
        """
        Revisa watchlist y genera recordatorios para deadlines próximos
        days_thresholds: [30,15,7,3,1] por defecto desde config
        Retorna lista de notificaciones creadas
        """
        if days_thresholds is None:
            try:
                days_thresholds = self.config.get("notifications.deadline_days", [30,15,7,3,1])
            except Exception:
                days_thresholds = [30,15,7,3,1]
        
        created = []
        try:
            watchlist = self.db.get_watchlist_with_days_left()
            for entry in watchlist:
                days_left = entry.get("days_left")
                if days_left is None:
                    continue
                
                # Si days_left está en thresholds, generar recordatorio
                if days_left in days_thresholds:
                    # Verificar si ya se notificó hoy para este days_left (idempotencia)
                    notif = self.notify_watchlist_reminder(
                        opportunity_id=entry["opportunity_id"],
                        watchlist_id=entry["id"],
                        days_left=days_left,
                        opportunity=entry,
                        watchlist_entry=entry
                    )
                    if notif:
                        created.append(notif)
        
        except Exception as e:
            self.logger.error(f"Failed to check watchlist reminders: {e}", exc_info=True)
        
        self.logger.info(f"[NOTIF] Watchlist reminders check: {len(created)} new notifications for thresholds {days_thresholds}")
        return created
    
    def check_deadline_upcoming(self, days_thresholds: List[int] = None) -> List[Dict[str, Any]]:
        """
        Revisa todas las oportunidades abiertas y genera deadline_reminder para próximas
        No solo watchlist, sino todas
        """
        if days_thresholds is None:
            days_thresholds = [7,3,1]  # Para todas, solo últimos días para no spamear
        
        created = []
        try:
            with self.db.connect() as conn:
                cur = conn.execute("""
                    SELECT o.*, org.name as org_name,
                           CAST((julianday(o.deadline) - julianday('now')) AS INTEGER) as days_left
                    FROM opportunities o
                    JOIN organizations org ON o.organization_id=org.id
                    WHERE o.status='open' AND o.deadline IS NOT NULL
                    AND CAST((julianday(o.deadline) - julianday('now')) AS INTEGER) IN ({})
                    ORDER BY o.deadline ASC
                """.format(",".join(["?"]*len(days_thresholds))), days_thresholds)
                
                opps = [dict(r) for r in cur.fetchall()]
                for opp in opps:
                    days_left = opp.get("days_left")
                    if days_left is None:
                        continue
                    
                    notif = self.notify_deadline_upcoming(
                        opportunity_id=opp["id"],
                        days_left=days_left,
                        opportunity=opp
                    )
                    if notif:
                        created.append(notif)
        
        except Exception as e:
            self.logger.error(f"Failed to check deadline upcoming: {e}", exc_info=True)
        
        return created
    
    def get_pending(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Obtiene notificaciones pendientes (no leídas, no archivadas)"""
        try:
            return self.db.get_pending_notifications(limit=limit)
        except Exception as e:
            self.logger.error(f"Failed to get pending notifications: {e}")
            return []
    
    def get_by_type(self, type: str, limit: int = 50) -> List[Dict[str, Any]]:
        try:
            return self.db.get_notifications_by_type(type, limit=limit)
        except Exception as e:
            self.logger.error(f"Failed to get notifications by type {type}: {e}")
            return []

# Singleton
_engine_instance = None

def get_notification_engine(db=None, config=None) -> NotificationEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = NotificationEngine(db=db, config=config)
    return _engine_instance
