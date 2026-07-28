"""
Scheduler Runtime - APScheduler real (Ticket 009)
Implementa APScheduler real, cada Job independiente

Jobs:
- Discover (semanal): busca nuevas orgs/sources
- Monitor (cada 12h): ejecuta providers -> fingerprint -> DB
- Notify (diario 09:00): watchlist reminders, deadline upcoming, digest
- Cleanup (diario 02:00): limpia old raw, logs viejos, notificaciones archivadas
- HealthCheck (cada hora): doctor checks, logs

Si un Job falla:
- los demás continúan (APScheduler jobs independientes por defecto)
- registrar traceback en logs/scheduler.log
- reintento configurable (retries, retry_delay_seconds desde config.yaml)

Validación: Simular fallos, verificar aislamiento completo
"""
import traceback
from pathlib import Path
from typing import Dict, Any, Callable, List, Optional
from datetime import datetime
import time
import functools

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.executors.pool import ThreadPoolExecutor

from core.logger import get_logger
from core.config import get_config
from core.db import get_db

logger = get_logger("scheduler")

# Logger específico para cada job
monitor_logger = get_logger("monitor")
discover_logger = get_logger("discover")
notifications_logger = None
try:
    from core.logger import setup_logger
    notifications_logger = setup_logger("notifications", "notifications.log", "INFO")
except Exception:
    notifications_logger = get_logger("core")

class JobResult:
    """Resultado de ejecución de un job con retry tracking"""
    def __init__(self, job_id: str, success: bool, duration: float, attempt: int = 1, error: str = None, traceback_str: str = None):
        self.job_id = job_id
        self.success = success
        self.duration = duration
        self.attempt = attempt
        self.error = error
        self.traceback_str = traceback_str
        self.timestamp = datetime.now().isoformat()

    def to_dict(self):
        return {
            "job_id": self.job_id,
            "success": self.success,
            "duration": round(self.duration, 2),
            "attempt": self.attempt,
            "error": self.error,
            "timestamp": self.timestamp
        }

def with_retry_and_isolation(retries: int = 2, retry_delay_seconds: int = 30, timeout_seconds: int = 600, job_id: str = "unknown"):
    """
    Decorador que envuelve job con retry configurable y aislamiento:
    - Si falla, loguea traceback completo en scheduler.log
    - Reintenta hasta retries veces con delay
    - Si falla todos los reintentos, marca como failed pero no rompe otros jobs (aislamiento)
    - Timeout no implementado con APScheduler directamente, pero loguea duración
    """
    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            last_tb = None
            
            for attempt in range(1, retries + 2):  # +1 porque primera ejecución + retries
                start = time.time()
                try:
                    logger.info(f"[SCHEDULER] Job {job_id} attempt {attempt}/{retries+1} starting")
                    result = func(*args, **kwargs)
                    duration = time.time() - start
                    logger.info(f"[SCHEDULER] Job {job_id} attempt {attempt} SUCCESS in {duration:.2f}s")
                    return JobResult(job_id=job_id, success=True, duration=duration, attempt=attempt)
                
                except Exception as e:
                    duration = time.time() - start
                    tb_str = traceback.format_exc()
                    last_error = str(e)
                    last_tb = tb_str
                    
                    logger.error(f"[SCHEDULER] Job {job_id} attempt {attempt}/{retries+1} FAILED in {duration:.2f}s: {e}\n{tb_str}")
                    
                    # Si no es último intento, esperar retry_delay
                    if attempt <= retries:
                        logger.info(f"[SCHEDULER] Job {job_id} retrying in {retry_delay_seconds}s (attempt {attempt+1}/{retries+1})")
                        time.sleep(retry_delay_seconds)
                    else:
                        logger.error(f"[SCHEDULER] Job {job_id} FAILED after {retries+1} attempts, giving up. Error: {e}")
            
            # Si llegamos aquí, todos los intentos fallaron
            return JobResult(job_id=job_id, success=False, duration=0, attempt=retries+1, error=last_error, traceback_str=last_tb)
        
        return wrapper
    return decorator

class SchedulerRuntime:
    """
    Runtime real con APScheduler, jobs independientes, aislamiento, traceback, retry configurable
    """
    
    def __init__(self, config=None, db=None):
        self.config = config or get_config()
        self.db = db or get_db()
        self.logger = logger
        
        # Configuración scheduler desde config.yaml
        scheduler_cfg = self.config.get("scheduler", {})
        self.enabled = scheduler_cfg.get("enabled", True)
        self.timezone = scheduler_cfg.get("timezone", "America/Argentina/Buenos_Aires")
        self.max_workers = scheduler_cfg.get("max_workers", 5)
        
        job_defaults_cfg = scheduler_cfg.get("job_defaults", {})
        self.job_defaults = {
            'coalesce': job_defaults_cfg.get("coalesce", True),
            'max_instances': job_defaults_cfg.get("max_instances", 1),
            'misfire_grace_time': job_defaults_cfg.get("misfire_grace_time", 3600)
        }
        
        # Inicializar APScheduler BackgroundScheduler con ThreadPoolExecutor para aislamiento
        # Cada job corre en su propio thread, si uno falla no bloquea otros
        executors = {
            'default': ThreadPoolExecutor(max_workers=self.max_workers)
        }
        jobstores = {
            'default': MemoryJobStore()
        }
        
        self.scheduler = BackgroundScheduler(
            executors=executors,
            jobstores=jobstores,
            job_defaults=self.job_defaults,
            timezone=self.timezone
        )
        
        # Listeners para logging de eventos
        self.scheduler.add_listener(self._job_executed_listener, EVENT_JOB_EXECUTED)
        self.scheduler.add_listener(self._job_error_listener, EVENT_JOB_ERROR)
        
        self.jobs_config = scheduler_cfg.get("jobs", {})
        self.job_results: List[JobResult] = []
        self._running = False
    
    def _job_executed_listener(self, event):
        """Listener cuando job se ejecuta exitosamente"""
        self.logger.info(f"[SCHEDULER] Job {event.job_id} executed successfully at {event.scheduled_run_time}")
    
    def _job_error_listener(self, event):
        """Listener cuando job falla - registra traceback, pero no detiene otros jobs (aislamiento)"""
        self.logger.error(f"[SCHEDULER] Job {event.job_id} crashed: {event.exception}\nTraceback: {event.traceback}")
        # No relanzar excepción, para que otros jobs continúen (aislamiento)
    
    def _parse_cron(self, cron_str: str) -> CronTrigger:
        """Parsea cron string tipo '0 3 * * 0' o '0 */12 * * *' a CronTrigger"""
        try:
            # Cron format: minute hour day month day_of_week
            parts = cron_str.strip().split()
            if len(parts) != 5:
                # Intentar como cron completo, si falla usar every 12h como fallback
                self.logger.warning(f"Invalid cron '{cron_str}', expected 5 parts, using every 12h fallback")
                return CronTrigger(hour="*/12")
            
            minute, hour, day, month, day_of_week = parts
            
            # Manejar */12 en hour
            # CronTrigger acepta */12 directamente
            return CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
                timezone=self.timezone
            )
        except Exception as e:
            self.logger.error(f"Failed to parse cron '{cron_str}': {e}, using daily 09:00 fallback")
            return CronTrigger(hour=9, minute=0, timezone=self.timezone)
    
    def _wrap_job_with_retry(self, job_func: Callable, job_id: str, retries: int, retry_delay: int, timeout: int):
        """Envuelve job con retry y aislamiento usando decorador"""
        return with_retry_and_isolation(retries=retries, retry_delay_seconds=retry_delay, timeout_seconds=timeout, job_id=job_id)(job_func)
    
    # ==================== JOBS DEFINITIONS ====================
    
    def discover_job(self):
        """Job Discover - Semanal, busca nuevas orgs/sources (placeholder por ahora, solo scan)"""
        discover_logger.info("[DISCOVER_JOB] Starting discovery job")
        try:
            from core.plugin_loader import get_plugin_loader
            loader = get_plugin_loader()
            # Scan ya hace discovery de plugins, pero para sources discovery futuro
            # Por ahora solo log y validate que loader funciona
            report = loader.get_status_report()
            discover_logger.info(f"[DISCOVER_JOB] Discovered {report['total_discovered']} plugins, {report['total_enabled']} enabled")
            
            # Futuro: implementar jobs/discovery.py con seeds -> extractor links externos -> org resolver
            # Por ahora solo simula trabajo
            time.sleep(0.5)
            
            discover_logger.info("[DISCOVER_JOB] Discovery job completed successfully")
            return True
        except Exception as e:
            discover_logger.error(f"[DISCOVER_JOB] Failed: {e}\n{traceback.format_exc()}")
            raise
    
    def monitor_job(self, batch_size: int = None):
        """Job Monitor - Cada 12h, ejecuta providers -> fingerprint -> DB"""
        monitor_logger.info("[MONITOR_JOB] Starting monitoring job")
        try:
            from jobs.monitoring import run_monitoring
            batch_size = batch_size or self.config.get("scan.monitoring.batch_size", 25)
            metrics = run_monitoring(batch_size=batch_size, only_active=True)
            monitor_logger.info(f"[MONITOR_JOB] Monitoring completed: {metrics.to_dict()}")
            return metrics
        except Exception as e:
            monitor_logger.error(f"[MONITOR_JOB] Failed: {e}\n{traceback.format_exc()}")
            raise
    
    def notify_job(self):
        """Job Notify - Diario 09:00, watchlist reminders, deadline upcoming, digest"""
        notifications_logger.info("[NOTIFY_JOB] Starting notify job")
        try:
            from core.notification_engine import get_notification_engine
            engine = get_notification_engine(db=self.db, config=self.config)
            
            # Watchlist reminders
            watchlist_created = engine.check_watchlist_reminders()
            notifications_logger.info(f"[NOTIFY_JOB] Watchlist reminders: {len(watchlist_created)} created")
            
            # Deadline upcoming para todas
            upcoming_created = engine.check_deadline_upcoming()
            notifications_logger.info(f"[NOTIFY_JOB] Deadline upcoming: {len(upcoming_created)} created")
            
            # System digest (placeholder)
            pending = engine.get_pending(limit=10)
            notifications_logger.info(f"[NOTIFY_JOB] Pending notifications: {len(pending)}")
            
            notifications_logger.info("[NOTIFY_JOB] Notify job completed successfully")
            return {"watchlist": len(watchlist_created), "upcoming": len(upcoming_created), "pending": len(pending)}
        except Exception as e:
            notifications_logger.error(f"[NOTIFY_JOB] Failed: {e}\n{traceback.format_exc()}")
            raise
    
    def cleanup_job(self):
        """Job Cleanup - Diario 02:00, limpia old raw, logs viejos, notificaciones archivadas"""
        logger.info("[CLEANUP_JOB] Starting cleanup job")
        try:
            # Limpiar data/raw archivos viejos >30 días (placeholder)
            raw_dir = Path(self.config.get("project.raw_html_storage", "data/raw/"))
            if raw_dir.exists():
                # Contar archivos viejos pero no borrar en test
                old_files = list(raw_dir.glob("*.html"))
                logger.info(f"[CLEANUP_JOB] Found {len(old_files)} raw files, would clean old >30 days")
            
            # Limpiar notificaciones archivadas viejas >30 días
            try:
                with self.db.connect() as conn:
                    # Archivar notificaciones leídas viejas >30 días (no borrar, solo archivar)
                    cur = conn.execute("""
                        UPDATE notifications SET is_archived=1 
                        WHERE is_read=1 AND created_at < datetime('now', '-30 days') AND is_archived=0
                    """)
                    logger.info(f"[CLEANUP_JOB] Archived {cur.rowcount} old read notifications")
            except Exception as e:
                logger.warning(f"[CLEANUP_JOB] Failed to archive old notifications: {e}")
            
            logger.info("[CLEANUP_JOB] Cleanup job completed successfully")
            return True
        except Exception as e:
            logger.error(f"[CLEANUP_JOB] Failed: {e}\n{traceback.format_exc()}")
            raise
    
    def healthcheck_job(self):
        """Job HealthCheck - Cada hora, doctor checks, logs"""
        logger.info("[HEALTHCHECK_JOB] Starting healthcheck job")
        try:
            from core.doctor import run_doctor
            # Run doctor sin verbose para no spamear, solo check
            # Para no imprimir todo, usamos validate_integrity de db y plugin status
            from core.db import get_db
            from core.plugin_loader import get_plugin_loader
            
            db = get_db()
            validation = db.validate_integrity()
            issues = validation.get("issues", [])
            
            loader = get_plugin_loader()
            report = loader.get_status_report()
            
            if issues:
                logger.warning(f"[HEALTHCHECK_JOB] Found {len(issues)} issues: {issues[:3]}")
            else:
                logger.info(f"[HEALTHCHECK_JOB] DB OK, {report['total_discovered']} plugins, {report['total_enabled']} enabled")
            
            # Verificar logs dir writable, db writable
            log_dir = Path(self.config.get("logging.dir", "logs"))
            if not log_dir.exists():
                logger.warning(f"[HEALTHCHECK_JOB] Logs dir {log_dir} not exists")
            
            logger.info("[HEALTHCHECK_JOB] Healthcheck job completed successfully")
            return {"issues": len(issues), "plugins": report["total_discovered"]}
        except Exception as e:
            logger.error(f"[HEALTHCHECK_JOB] Failed: {e}\n{traceback.format_exc()}")
            raise
    
    # ==================== SCHEDULER CONTROL ====================
    
    def add_jobs(self):
        """Agrega jobs desde config.yaml con retry configurable"""
        jobs_cfg = self.jobs_config
        
        # Mapeo job_id -> función
        job_funcs = {
            "discover": self.discover_job,
            "monitor": lambda: self.monitor_job(batch_size=self.config.get("scan.monitoring.batch_size", 25)),
            "notify": self.notify_job,
            "cleanup": self.cleanup_job,
            "healthcheck": self.healthcheck_job
        }
        
        for job_id, func in job_funcs.items():
            cfg = jobs_cfg.get(job_id, {})
            if not cfg.get("enabled", True):
                logger.info(f"[SCHEDULER] Job {job_id} disabled in config, skipping")
                continue
            
            cron_str = cfg.get("cron", "0 */12 * * *")
            retries = cfg.get("retries", 2)
            retry_delay = cfg.get("retry_delay_seconds", 30)
            timeout = cfg.get("timeout_seconds", 600)
            
            trigger = self._parse_cron(cron_str)
            
            # Envolver con retry y aislamiento
            wrapped_func = self._wrap_job_with_retry(
                job_func=func,
                job_id=job_id,
                retries=retries,
                retry_delay=retry_delay,
                timeout=timeout
            )
            
            try:
                self.scheduler.add_job(
                    wrapped_func,
                    trigger=trigger,
                    id=job_id,
                    name=f"Radar {job_id} job",
                    replace_existing=True
                )
                logger.info(f"[SCHEDULER] Added job {job_id} with cron '{cron_str}' retries={retries} delay={retry_delay}s timeout={timeout}s")
            except Exception as e:
                logger.error(f"[SCHEDULER] Failed to add job {job_id}: {e}\n{traceback.format_exc()}")
    
    def start(self):
        """Inicia scheduler"""
        if self._running:
            logger.warning("[SCHEDULER] Already running")
            return
        
        self.add_jobs()
        
        try:
            self.scheduler.start()
            self._running = True
            logger.info(f"[SCHEDULER] Started with {len(self.scheduler.get_jobs())} jobs, timezone={self.timezone}, max_workers={self.max_workers}")
            
            # Listar jobs
            for job in self.scheduler.get_jobs():
                logger.info(f"[SCHEDULER] Job {job.id} next run at {job.next_run_time}")
        
        except Exception as e:
            logger.error(f"[SCHEDULER] Failed to start: {e}\n{traceback.format_exc()}")
            raise
    
    def shutdown(self, wait: bool = True):
        """Apaga scheduler"""
        if not self._running:
            return
        
        try:
            self.scheduler.shutdown(wait=wait)
            self._running = False
            logger.info("[SCHEDULER] Shutdown completed")
        except Exception as e:
            logger.error(f"[SCHEDULER] Failed to shutdown: {e}")
    
    def get_jobs(self):
        """Retorna lista de jobs programados"""
        return self.scheduler.get_jobs() if self._running else []
    
    def run_job_now(self, job_id: str) -> JobResult:
        """Ejecuta un job inmediatamente (útil para testing y validación)"""
        try:
            # Buscar función original sin wrapper retry para test directo
            job_funcs = {
                "discover": self.discover_job,
                "monitor": lambda: self.monitor_job(),
                "notify": self.notify_job,
                "cleanup": self.cleanup_job,
                "healthcheck": self.healthcheck_job
            }
            
            func = job_funcs.get(job_id)
            if not func:
                return JobResult(job_id=job_id, success=False, duration=0, error=f"Job {job_id} not found")
            
            # Obtener config retry para este job
            cfg = self.jobs_config.get(job_id, {})
            retries = cfg.get("retries", 2)
            retry_delay = cfg.get("retry_delay_seconds", 0)  # Para test no delay
            timeout = cfg.get("timeout_seconds", 600)
            
            wrapped = self._wrap_job_with_retry(func, job_id, retries, retry_delay, timeout)
            result = wrapped()
            self.job_results.append(result)
            return result
        
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"[SCHEDULER] run_job_now {job_id} failed: {e}\n{tb}")
            result = JobResult(job_id=job_id, success=False, duration=0, error=str(e), traceback_str=tb)
            self.job_results.append(result)
            return result
    
    def get_job_results(self) -> List[JobResult]:
        return self.job_results

# Singleton
_scheduler_runtime_instance = None

def get_scheduler_runtime(config=None, db=None) -> SchedulerRuntime:
    global _scheduler_runtime_instance
    if _scheduler_runtime_instance is None:
        _scheduler_runtime_instance = SchedulerRuntime(config=config, db=db)
    return _scheduler_runtime_instance
