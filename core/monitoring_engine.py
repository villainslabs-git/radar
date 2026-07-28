"""
Radar - Monitoring Engine (Ticket 006)
Construir el motor de monitoreo

Debe:
- ejecutar providers (via PluginLoader runtime)
- recibir oportunidades (via Provider fetch/extract/normalize)
- pasar todas por Fingerprint
- insertar únicamente nuevas (deduplicación)
- registrar cambios (history tracker)
- producir métricas
- NO implementar scoring todavía

Toda oportunidad debe recorrer: Provider -> Normalize -> Fingerprint -> Database -> Logs

Validación:
- duplicados (exact + approximate)
- errores (aislados, no rompen sistema)
- logs (monitor.log separado)
- métricas (total fetched, new, duplicates, updated, errors)
"""
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
import time
import json
from datetime import datetime

from core.logger import get_logger
from core.config import get_config
from core.db import get_db
from core.fingerprint import FingerprintEngine, Fingerprint
from core.plugin_loader import PluginLoader, get_plugin_loader
from core.history import HistoryTracker, get_history_tracker
from core.provider import NormalizedOpportunity

logger = get_logger("monitor")

# Notification engine opcional (Ticket 008) - import lazy para no romper si no existe
try:
    from core.notification_engine import get_notification_engine
    HAS_NOTIFICATION_ENGINE = True
except ImportError:
    HAS_NOTIFICATION_ENGINE = False
    get_notification_engine = None

@dataclass
class SourceMetrics:
    source_id: int
    source_url: str
    org_slug: str
    provider_slug: str
    fetched: int = 0
    normalized: int = 0
    new: int = 0
    duplicate_exact: int = 0
    duplicate_approximate: int = 0
    updated: int = 0
    history_entries: int = 0
    alternate_links_added: int = 0
    errors: int = 0
    error_messages: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self):
        return {
            "source_id": self.source_id,
            "source_url": self.source_url,
            "org_slug": self.org_slug,
            "provider_slug": self.provider_slug,
            "fetched": self.fetched,
            "normalized": self.normalized,
            "new": self.new,
            "duplicate_exact": self.duplicate_exact,
            "duplicate_approximate": self.duplicate_approximate,
            "updated": self.updated,
            "history_entries": self.history_entries,
            "alternate_links_added": self.alternate_links_added,
            "errors": self.errors,
            "duration_seconds": round(self.duration_seconds, 2)
        }

@dataclass
class MonitoringMetrics:
    total_sources: int = 0
    total_fetched: int = 0
    total_normalized: int = 0
    total_new: int = 0
    total_duplicate_exact: int = 0
    total_duplicate_approximate: int = 0
    total_updated: int = 0
    total_history_entries: int = 0
    total_alternate_links: int = 0
    total_errors: int = 0
    duration_seconds: float = 0.0
    sources: List[SourceMetrics] = field(default_factory=list)

    def to_dict(self):
        return {
            "total_sources": self.total_sources,
            "total_fetched": self.total_fetched,
            "total_normalized": self.total_normalized,
            "total_new": self.total_new,
            "total_duplicate_exact": self.total_duplicate_exact,
            "total_duplicate_approximate": self.total_duplicate_approximate,
            "total_updated": self.total_updated,
            "total_history_entries": self.total_history_entries,
            "total_alternate_links": self.total_alternate_links,
            "total_errors": self.total_errors,
            "duration_seconds": round(self.duration_seconds, 2),
            "sources": [s.to_dict() for s in self.sources]
        }

class MonitoringEngine:
    """
    Motor de monitoreo: ejecuta providers, pasa por fingerprint, inserta solo nuevas, registra cambios, produce métricas
    No scoring todavía (senior advice)
    Integración con Notification Engine (Ticket 008): genera notificaciones para nuevos, deadline cambiado, status cerrado, etc
    """
    
    def __init__(self, db=None, loader: PluginLoader = None, fingerprint_engine: FingerprintEngine = None, history_tracker: HistoryTracker = None, notification_engine=None, config=None):
        self.config = config or get_config()
        self.db = db or get_db()
        self.loader = loader or get_plugin_loader()
        self.fingerprint_engine = fingerprint_engine or FingerprintEngine(config=self.config)
        self.history_tracker = history_tracker or get_history_tracker()
        # Notification engine opcional, solo si existe (Ticket 008)
        if notification_engine:
            self.notification_engine = notification_engine
        elif HAS_NOTIFICATION_ENGINE:
            try:
                self.notification_engine = get_notification_engine(db=self.db, config=self.config)
            except Exception:
                self.notification_engine = None
        else:
            self.notification_engine = None
        self.logger = logger
        self.batch_size = self.config.get("scan.monitoring.batch_size", 25)
    
    def _resolve_organization(self, org_slug: str) -> Optional[Dict[str, Any]]:
        """Resuelve organization_id desde slug"""
        try:
            return self.db.find_organization_by_slug(org_slug)
        except Exception as e:
            self.logger.error(f"Failed to resolve org {org_slug}: {e}")
            return None
    
    def monitor_source(self, source: Dict[str, Any]) -> SourceMetrics:
        """
        Monitorea una fuente:
        Provider -> Normalize (via provider.run) -> Fingerprint -> Database -> Logs
        """
        start = time.time()
        source_id = source.get("id")
        source_url = source.get("url", "")
        org_slug = source.get("org_slug") or source.get("organization_slug") or ""
        provider_slug = org_slug  # por convención plugin slug == org slug
        
        metrics = SourceMetrics(
            source_id=source_id,
            source_url=source_url,
            org_slug=org_slug,
            provider_slug=provider_slug
        )
        
        self.logger.info(f"[MONITOR] Start source {source_id} {source_url} org={org_slug} provider={provider_slug}")
        
        # 1. Obtener plugin y provider instance (runtime)
        try:
            loaded_plugin = self.loader.get_plugin(provider_slug)
            if not loaded_plugin:
                # Intentar por org_slug
                loaded_plugin = self.loader.get_plugin(org_slug)
            
            if not loaded_plugin:
                msg = f"Plugin not found for org_slug {org_slug} (provider_slug {provider_slug}) -> source {source_id} skipped"
                self.logger.warning(msg)
                metrics.errors += 1
                metrics.error_messages.append(msg)
                return metrics
            
            if not loaded_plugin.enabled:
                msg = f"Plugin {provider_slug} disabled in config, source {source_id} skipped"
                self.logger.info(msg)
                return metrics
            
            if not loaded_plugin.is_loadable and loaded_plugin.status.value not in ("instantiated", "loaded"):
                msg = f"Plugin {provider_slug} not loadable: status={loaded_plugin.status} error={loaded_plugin.error}"
                self.logger.warning(msg)
                metrics.errors += 1
                metrics.error_messages.append(msg)
                return metrics
            
            # Obtener o crear instancia provider
            instance, error = self.loader.get_or_create_instance(provider_slug, org_slug)
            if error or not instance:
                msg = f"Failed to instantiate provider {provider_slug} org {org_slug}: {error}"
                self.logger.error(msg)
                metrics.errors += 1
                metrics.error_messages.append(msg)
                return metrics
            
            self.loader.mark_running(provider_slug, org_slug)
        
        except Exception as e:
            msg = f"Exception resolving provider for source {source_id} {source_url}: {e}"
            self.logger.error(msg, exc_info=True)
            metrics.errors += 1
            metrics.error_messages.append(msg)
            return metrics
        
        # 2. Ejecutar provider: fetch -> extract -> normalize (via provider.run)
        normalized_opps: List[NormalizedOpportunity] = []
        try:
            # provider.run(url) ya hace fetch+extract+normalize
            normalized_opps = instance.run(source_url)
            metrics.fetched = len(normalized_opps)  # En este caso run ya normaliza, pero contamos como fetched+normalized
            metrics.normalized = len(normalized_opps)
            self.logger.info(f"[MONITOR] Source {source_id} fetched {len(normalized_opps)} normalized opportunities via {provider_slug}")
        
        except Exception as e:
            msg = f"Provider {provider_slug} run failed for {source_url}: {e}"
            self.logger.error(msg, exc_info=True)
            metrics.errors += 1
            metrics.error_messages.append(msg)
            # Marcar failed pero no romper sistema completo
            try:
                self.loader.mark_failed(provider_slug, str(e), org_slug)
            except Exception:
                pass
            metrics.duration_seconds = time.time() - start
            return metrics
        
        # 3. Para cada oportunidad normalizada: Fingerprint -> Database -> Logs
        for norm_opp in normalized_opps:
            try:
                result = self.process_opportunity(norm_opp, source)
                # Acumular métricas según resultado
                if result["status"] == "new":
                    metrics.new += 1
                elif result["status"] == "duplicate_exact":
                    metrics.duplicate_exact += 1
                    if result.get("alternate_added"):
                        metrics.alternate_links_added += 1
                elif result["status"] == "duplicate_approximate":
                    metrics.duplicate_approximate += 1
                    if result.get("alternate_added"):
                        metrics.alternate_links_added += 1
                elif result["status"] == "updated":
                    metrics.updated += 1
                    metrics.history_entries += result.get("history_count", 0)
                
                # Si hubo actualización, contar también history y alternate
                if result.get("history_count"):
                    metrics.history_entries += result["history_count"]
                if result.get("alternate_added") and result["status"] != "duplicate_exact" and result["status"] != "duplicate_approximate":
                    # Ya contado arriba
                    pass
            
            except Exception as e:
                msg = f"Failed to process opportunity {getattr(norm_opp, 'title', 'unknown')} from {source_url}: {e}"
                self.logger.error(msg, exc_info=True)
                metrics.errors += 1
                metrics.error_messages.append(msg)
                continue
        
        # 4. Actualizar source last_scraped_at, last_success_at
        try:
            with self.db.connect() as conn:
                conn.execute("""
                    UPDATE sources 
                    SET last_scraped_at=CURRENT_TIMESTAMP, 
                        last_success_at=CURRENT_TIMESTAMP,
                        last_status_code=200,
                        consecutive_errors=0,
                        error_count=0
                    WHERE id=?
                """, (source_id,))
        except Exception as e:
            self.logger.warning(f"Failed to update source {source_id} success timestamp: {e}")
        
        metrics.duration_seconds = time.time() - start
        self.logger.info(f"[MONITOR] Completed source {source_id} {source_url} - new={metrics.new} dup_exact={metrics.duplicate_exact} dup_approx={metrics.duplicate_approximate} updated={metrics.updated} errors={metrics.errors} duration={metrics.duration_seconds:.2f}s")
        
        return metrics
    
    def process_opportunity(self, normalized_opp: NormalizedOpportunity, source: Dict[str, Any]) -> Dict[str, Any]:
        """
        Procesa una oportunidad normalizada:
        Fingerprint -> Database (insert only new, register changes)
        Toda oportunidad recorre: Provider (ya hecho) -> Normalize (ya hecho) -> Fingerprint -> Database -> Logs
        
        Returns dict con status y detalles
        """
        source_id = source.get("id")
        org_slug = source.get("org_slug") or getattr(normalized_opp, 'organization_slug', '') or ""
        
        # Resolver organization_id
        org = self._resolve_organization(org_slug)
        if not org:
            # Si no existe org, intentar crear? Por ahora error
            return {"status": "error", "reason": f"Organization {org_slug} not found"}
        
        org_id = org["id"]
        
        # Generar fingerprint
        try:
            fp = self.fingerprint_engine.generate({
                "title": normalized_opp.title,
                "official_link": normalized_opp.official_link,
                "organization_slug": normalized_opp.organization_slug or org_slug,
                "deadline": normalized_opp.deadline,
                "opportunity_type": normalized_opp.opportunity_type or normalized_opp.category or "contest",
                "country": normalized_opp.country or ""
            })
        except Exception as e:
            return {"status": "error", "reason": f"Fingerprint generation failed: {e}"}
        
        # Buscar duplicado en DB - primero exacto, luego aproximado para detectar cambios de deadline
        existing = None
        is_approximate = False
        
        try:
            existing = self.db.find_opportunity_by_fingerprint(fp.hash, org_id)
        except Exception as e:
            self.logger.error(f"DB find by fingerprint failed for {fp.hash}: {e}")
            existing = None
        
        # Si no existe exacto, intentar aproximado por título para detectar cambios (ej. deadline extendido)
        if not existing:
            try:
                approx = self._find_approximate_duplicate(fp, org_id, normalized_opp)
                if approx:
                    existing = approx
                    is_approximate = True
                    self.logger.info(f"[APPROX_DUP] Found approximate duplicate for {normalized_opp.title[:40]} -> existing {existing['id']} similarity high, treating as update not new")
            except Exception as e:
                self.logger.warning(f"Approximate duplicate search failed: {e}")
        
        # Si no existe: insertar nueva
        if not existing:
            try:
                opp_data = {
                    "organization_id": org_id,
                    "source_id": source_id,
                    "fingerprint_hash": fp.hash,
                    "title": normalized_opp.title,
                    "organizer_name": normalized_opp.organizer_name or org.get("name", org_slug),
                    "official_link": normalized_opp.official_link,
                    "description_raw": normalized_opp.description_raw,
                    "description_clean": normalized_opp.description_clean,
                    "deadline": self._normalize_deadline_for_db(normalized_opp.deadline),
                    "awards_text": normalized_opp.awards_text,
                    "economic_value": normalized_opp.economic_value,
                    "currency": normalized_opp.currency,
                    "country": normalized_opp.country,
                    "category": self._map_category(normalized_opp),
                    "language": normalized_opp.language,
                    "status": "open",
                    "alternate_links_json": json.dumps([])  # inicialmente vacío, official_link es principal
                }
                new_id = self.db.insert_opportunity(opp_data)
                self.logger.info(f"[NEW] Inserted opportunity {new_id} {normalized_opp.title[:50]} org={org_slug} fp={fp.hash}")
                
                # Notification Engine (Ticket 008): nueva oportunidad
                if self.notification_engine:
                    try:
                        # Obtener oportunidad completa para notificación
                        opp_for_notif = self.db.find_opportunity_by_id(new_id)
                        if opp_for_notif:
                            self.notification_engine.notify_new_opportunity(opp_for_notif, source)
                    except Exception as e:
                        self.logger.warning(f"Failed to notify new opportunity {new_id}: {e}")
                
                return {"status": "new", "opportunity_id": new_id, "fingerprint": fp}
            
            except Exception as e:
                # Puede ser race condition UNIQUE constraint -> tratar como duplicado exacto
                if "UNIQUE" in str(e) or "fingerprint_hash" in str(e):
                    # Re-buscar
                    try:
                        existing = self.db.find_opportunity_by_fingerprint(fp.hash, org_id)
                        if existing:
                            # Manejar como duplicado exacto
                            return self._handle_duplicate(normalized_opp, existing, source, fp, is_approximate=False)
                    except Exception:
                        pass
                return {"status": "error", "reason": f"Insert failed: {e}"}
        
        # Si existe: manejar duplicado
        return self._handle_duplicate(normalized_opp, existing, source, fp, is_approximate=False)

    def _handle_duplicate(self, normalized_opp, existing, source, fp, is_approximate=False):
        """
        Maneja duplicado con TRANSACCIÓN ATÓMICA por oportunidad (hardening Ticket 006 observación 1):
        BEGIN -> update opportunity + insert history + alternate links -> COMMIT
        Si falla history después de update, rollback para no dejar oportunidad actualizada sin historial

        Idempotencia (observación 2):
        - alternate_links: solo agrega si no existe
        - history: verifica último historial para mismo campo/valores y evita duplicado si ya existe reciente
        - updates: solo si detect_changes encuentra cambios, 2da pasada sin cambios no genera update ni history

        Escalabilidad (observación 3): _find_approximate_duplicate consulta todas oportunidades de org y compara una por una.
        Con 300 ok, con 30k-500k será cuello de botella. Documentado como optimización futura vía índice/candidatos.
        """
        opp_id = existing["id"]
        source_id = source.get("id")
        
        result = {
            "status": "duplicate_approximate" if is_approximate else "duplicate_exact",
            "opportunity_id": opp_id,
            "fingerprint": fp,
            "alternate_added": False,
            "history_count": 0,
            "updated": False
        }
        
        # Preparar dicts old y new para comparación
        old_dict = {
            "title": existing.get("title"),
            "deadline": existing.get("deadline"),
            "awards_text": existing.get("awards_text"),
            "economic_value": existing.get("economic_value"),
            "currency": existing.get("currency"),
            "status": existing.get("status"),
            "official_link": existing.get("official_link"),
            "description_raw": existing.get("description_raw"),
            "description_clean": existing.get("description_clean"),
            "organizer_name": existing.get("organizer_name"),
            "country": existing.get("country"),
            "category": existing.get("category"),
        }
        
        new_dict = {
            "title": normalized_opp.title,
            "deadline": normalized_opp.deadline,
            "awards_text": normalized_opp.awards_text,
            "economic_value": normalized_opp.economic_value,
            "currency": normalized_opp.currency,
            "status": "open",
            "official_link": normalized_opp.official_link,
            "description_raw": normalized_opp.description_raw,
            "description_clean": normalized_opp.description_clean,
            "organizer_name": normalized_opp.organizer_name,
            "country": normalized_opp.country,
            "category": self._map_category(normalized_opp),
        }
        
        changes = self.history_tracker.detect_changes(old_dict, new_dict)
        
        # Preparar updates (sin official_link que va a alternate)
        updates = {}
        for change in changes:
            if change.field_name == "official_link":
                continue
            if change.field_name == "deadline":
                updates["deadline"] = self._normalize_deadline_for_db(new_dict.get("deadline"))
            else:
                updates[change.field_name] = new_dict.get(change.field_name)
        
        new_url = normalized_opp.official_link or normalized_opp.source_url or ""
        
        # TRANSACCIÓN ATÓMICA: todo en una sola conexión
        try:
            with self.db.connect() as conn:
                # 1. Alternate link (idempotente)
                alternate_added = False
                if new_url:
                    cur = conn.execute("SELECT alternate_links_json, official_link FROM opportunities WHERE id=?", (opp_id,))
                    row = cur.fetchone()
                    if row:
                        existing_links = []
                        if row["alternate_links_json"]:
                            try:
                                import json as _json
                                existing_links = _json.loads(row["alternate_links_json"])
                            except Exception:
                                existing_links = []
                        
                        official = row["official_link"] or ""
                        if new_url != official and new_url not in existing_links:
                            existing_links.append(new_url)
                            if len(existing_links) > 20:
                                existing_links = existing_links[-20:]
                            conn.execute(
                                "UPDATE opportunities SET alternate_links_json=?, last_seen_at=CURRENT_TIMESTAMP WHERE id=?",
                                (_json.dumps(existing_links), opp_id)
                            )
                            alternate_added = True
                            self.logger.info(f"[ALT_LINK] Added alternate link {new_url} to opp {opp_id}")
                        else:
                            if not changes:
                                conn.execute("UPDATE opportunities SET last_seen_at=CURRENT_TIMESTAMP WHERE id=?", (opp_id,))
                
                result["alternate_added"] = alternate_added
                
                # 2. Si hay cambios, update + history en misma transacción
                if changes and updates:
                    # Update oportunidad
                    updates["last_changed_at"] = __import__("datetime").datetime.now().isoformat()
                    updates["updated_at"] = __import__("datetime").datetime.now().isoformat()
                    set_clause = ", ".join([f"{k}=?" for k in updates.keys()])
                    values = list(updates.values()) + [opp_id]
                    conn.execute(f"UPDATE opportunities SET {set_clause} WHERE id=?", values)
                    result["updated"] = True
                    result["status"] = "updated"
                    self.logger.info(f"[UPDATE] Opp {opp_id} updated fields: {[c.field_name for c in changes]}")
                    
                    # Insertar history con idempotencia
                    history_count = 0
                    for change in changes:
                        # Idempotencia: verificar último historial mismo campo/valores
                        try:
                            cur = conn.execute("""
                                SELECT old_value, new_value FROM opportunity_history 
                                WHERE opportunity_id=? AND field_name=? 
                                ORDER BY detected_at DESC LIMIT 1
                            """, (opp_id, change.field_name))
                            last = cur.fetchone()
                            if last and str(last["old_value"]) == str(change.old_value) and str(last["new_value"]) == str(change.new_value):
                                self.logger.debug(f"[HISTORY] Skipping duplicate history for opp {opp_id} field {change.field_name}")
                                continue
                        except Exception:
                            pass
                        
                        import json as _json
                        conn.execute("""
                            INSERT INTO opportunity_history (opportunity_id, field_name, old_value, new_value, change_type, source_id, metadata_json)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            opp_id,
                            change.field_name,
                            str(change.old_value) if change.old_value is not None else None,
                            str(change.new_value) if change.new_value is not None else None,
                            change.change_type,
                            source_id,
                            _json.dumps({"fingerprint": fp.hash, "source_url": source.get("url")})
                        ))
                        history_count += 1
                    
                    result["history_count"] = history_count
                    result["changes"] = [c.to_dict() for c in changes]
                    
                    if self.history_tracker.has_significant_changes(changes):
                        self.logger.info(f"[HISTORY] Significant changes for opp {opp_id}: {self.history_tracker.format_changes_for_log(changes)}")
                    
                    # Notification Engine (Ticket 008): notificar cambios significativos
                    if self.notification_engine:
                        try:
                            for change in changes:
                                if change.field_name == "deadline":
                                    self.notification_engine.notify_deadline_changed(
                                        opportunity_id=opp_id,
                                        old_deadline=change.old_value,
                                        new_deadline=change.new_value,
                                        change_type=change.change_type,
                                        opportunity=existing,
                                        source_id=source_id
                                    )
                                elif change.field_name == "status" and str(change.new_value).lower() == "closed":
                                    self.notification_engine.notify_status_closed(
                                        opportunity_id=opp_id,
                                        old_status=change.old_value,
                                        new_status=change.new_value,
                                        opportunity=existing
                                    )
                        except Exception as e:
                            self.logger.warning(f"Failed to notify changes for opp {opp_id}: {e}")
                
                elif not changes and not alternate_added:
                    # Solo last_seen_at
                    conn.execute("UPDATE opportunities SET last_seen_at=CURRENT_TIMESTAMP WHERE id=?", (opp_id,))
                
                # Commit automático al salir del context manager
        except Exception as e:
            self.logger.error(f"Failed atomic duplicate handling for opp {opp_id}: {e}", exc_info=True)
            result["error"] = str(e)
        
        return result


    def _find_approximate_duplicate(self, fp: Fingerprint, org_id: int, normalized_opp: NormalizedOpportunity) -> Optional[Dict[str, Any]]:
        """
        Busca duplicado aproximado para detectar cambios como deadline extendido
        que generan hash diferente (deadline está en hash).
        
        Lógica estricta para evitar falsos positivos como Test Opp 1 vs Test Opp 2:
        - Si official_link normalizado igual y org misma y title similarity >=0.85 -> duplicate (deadline extendido mismo URL)
        - Si official_link diferente, solo duplicate si title similarity >=0.95 AND deadline mismo exacto y org misma
          (cross-source misma oportunidad con URLs diferentes pero mismo deadline y título casi idéntico)
        Evita merge de oportunidades distintas con títulos similares pero URLs y deadlines diferentes.
        """
        try:
            with self.db.connect() as conn:
                cur = conn.execute("SELECT * FROM opportunities WHERE organization_id=? AND is_duplicate_of IS NULL", (org_id,))
                candidates = [dict(r) for r in cur.fetchall()]
                
                for candidate in candidates:
                    try:
                        cand_fp = self.fingerprint_engine.generate({
                            "title": candidate.get("title", ""),
                            "official_link": candidate.get("official_link", ""),
                            "organization_slug": normalized_opp.organization_slug or "",
                            "deadline": candidate.get("deadline", ""),
                            "opportunity_type": candidate.get("category", "contest"),
                            "country": candidate.get("country", "")
                        })
                        
                        title_sim = self.fingerprint_engine._title_similarity(fp.normalized_title, cand_fp.normalized_title)
                        
                        # Normalizar URLs
                        cand_url_norm = self.fingerprint_engine.normalize_url(candidate.get("official_link", ""))
                        new_url_norm = fp.normalized_url
                        
                        # Caso 1: official_link mismo -> mismo opp aunque deadline diferente (deadline extended)
                        if cand_url_norm and new_url_norm and cand_url_norm == new_url_norm:
                            if title_sim >= 0.85:
                                return candidate
                        
                        # Caso 2: URL diferente, solo duplicate si título muy similar >=0.95 Y deadline mismo exacto
                        # Esto evita merge de Test Opp 1 vs Test Opp 2 (deadlines diferentes)
                        if title_sim >= 0.95:
                            # Deadline mismo exacto
                            if fp.normalized_deadline and cand_fp.normalized_deadline and fp.normalized_deadline == cand_fp.normalized_deadline:
                                return candidate
                            # Ambos sin deadline y título casi idéntico >=0.98
                            if not fp.normalized_deadline and not cand_fp.normalized_deadline and title_sim >= 0.98:
                                return candidate
                    
                    except Exception as e:
                        continue
        except Exception as e:
            self.logger.warning(f"_find_approximate_duplicate failed: {e}")
        
        return None
    
    def _normalize_deadline_for_db(self, deadline: Any) -> Optional[str]:
        """Normaliza deadline para DB (YYYY-MM-DD HH:MM:SS o fecha)"""
        if not deadline:
            return None
        try:
            from dateutil import parser
            dt = parser.parse(str(deadline), fuzzy=True)
            return dt.isoformat(separators=' ')
        except Exception:
            try:
                return str(deadline)[:19]
            except Exception:
                return None
    
    def _map_category(self, norm_opp: NormalizedOpportunity) -> str:
        """Mapea opportunity_type a category válida para DB"""
        # DB category check: AI, Video, Motion, Publicidad, Arte Digital, Cine, Foto, Música, General
        # Norm opp type puede ser contest, grant, residency, etc. Mapear a General por defecto, pero intentar preservar
        # Si norm_opp tiene category, usar esa si es válida
        valid_cats = ["AI","Video","Motion","Publicidad","Arte Digital","Cine","Foto","Música","General"]
        # Si norm_opp.category ya es válida, usarla
        if hasattr(norm_opp, 'category') and norm_opp.category in valid_cats:
            return norm_opp.category
        # Si tiene opportunity_type, mapear algunos a categorías
        opp_type = getattr(norm_opp, 'opportunity_type', '') or getattr(norm_opp, 'category', '') or ""
        opp_type_lower = opp_type.lower()
        if "ai" in opp_type_lower or "generative" in opp_type_lower:
            return "AI"
        if "video" in opp_type_lower:
            return "Video"
        if "motion" in opp_type_lower:
            return "Motion"
        if "cine" in opp_type_lower or "film" in opp_type_lower or "festival" in opp_type_lower:
            return "Cine"
        return "General"
    
    def monitor_all(self, only_active: bool = True, batch_size: int = None) -> MonitoringMetrics:
        """
        Monitorea todas las fuentes activas (o batch_size)
        Flujo: Provider -> Normalize -> Fingerprint -> Database -> Logs
        """
        start = time.time()
        batch_size = batch_size or self.batch_size
        
        # Obtener fuentes
        try:
            sources = self.db.get_sources(only_active=only_active)
            # Limitar a batch_size ordenadas por priority desc (ya viene ordenada desde get_sources)
            sources = sources[:batch_size]
        except Exception as e:
            self.logger.error(f"Failed to get sources: {e}")
            return MonitoringMetrics(total_sources=0, total_errors=1)
        
        metrics = MonitoringMetrics(total_sources=len(sources))
        
        self.logger.info(f"[MONITOR_ALL] Starting monitoring for {len(sources)} sources, batch_size={batch_size}")
        
        for source in sources:
            try:
                src_metrics = self.monitor_source(source)
                metrics.sources.append(src_metrics)
                metrics.total_fetched += src_metrics.fetched
                metrics.total_normalized += src_metrics.normalized
                metrics.total_new += src_metrics.new
                metrics.total_duplicate_exact += src_metrics.duplicate_exact
                metrics.total_duplicate_approximate += src_metrics.duplicate_approximate
                metrics.total_updated += src_metrics.updated
                metrics.total_history_entries += src_metrics.history_entries
                metrics.total_alternate_links += src_metrics.alternate_links_added
                metrics.total_errors += src_metrics.errors
            
            except Exception as e:
                self.logger.error(f"Failed to monitor source {source.get('id')} {source.get('url')}: {e}", exc_info=True)
                metrics.total_errors += 1
                # Crear métrica de error para ese source
                err_metrics = SourceMetrics(
                    source_id=source.get("id", 0),
                    source_url=source.get("url", ""),
                    org_slug=source.get("org_slug", ""),
                    provider_slug=source.get("org_slug", ""),
                    errors=1,
                    error_messages=[str(e)]
                )
                metrics.sources.append(err_metrics)
                continue
        
        metrics.duration_seconds = time.time() - start
        
        # Log resumen final
        self.logger.info(
            f"[MONITOR_ALL] Completed {metrics.total_sources} sources in {metrics.duration_seconds:.2f}s - "
            f"fetched={metrics.total_fetched} new={metrics.total_new} dup_exact={metrics.total_duplicate_exact} "
            f"dup_approx={metrics.total_duplicate_approximate} updated={metrics.total_updated} "
            f"history={metrics.total_history_entries} alt_links={metrics.total_alternate_links} errors={metrics.total_errors}"
        )
        
        return metrics
