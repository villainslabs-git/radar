"""
Radar - Scheduler que respeta enable por YML y usa Plugin Loader real
Ticket 004: Integración loader + scheduler

Arquitectura ordenada:
- PluginLoader descubre plugins dinámicamente (sin listas manuales)
- Scheduler pide jobs a loader via get_jobs() -> respeta enable, schedule, priority
- Jobs independientes: discover -> monitor -> score(disabled) -> notify
- Cada plugin puede tener su propio schedule (daily, weekly, etc)
- Core nunca toca reglas específicas de orgs

Uso:
    scheduler = RadarScheduler()
    scheduler.print_schedule()  # muestra qué plugins se ejecutarán y cuándo
    scheduler.run_job('monitor', slug='runway') # futuro
"""
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
import logging

from core.logger import get_logger
from core.config import get_config
from core.plugin_loader import PluginLoader, get_plugin_loader

logger = get_logger("scheduler")

class RadarScheduler:
    """
    Scheduler que usa Plugin Loader real.
    No lista manual de plugins, no reglas org-specific en core.
    """
    
    def __init__(self, plugins_dir: Path = Path("plugins"), config=None):
        self.config = config or get_config()
        self.loader = get_plugin_loader(plugins_dir)
        self.logger = logger
    
    def get_jobs(self) -> List[Dict[str, Any]]:
        """Delega a loader: jobs respetando enable por YML"""
        return self.loader.get_jobs()
    
    def get_schedule_by_frequency(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Agrupa jobs por frecuencia para ejecución independiente.
        Ej: daily -> [runway, posterheroes, adobe], weekly -> [leonardo, openai]
        """
        jobs = self.get_jobs()
        grouped: Dict[str, List[Dict]] = {}
        for job in jobs:
            freq = job.get("schedule", "daily")
            if freq not in grouped:
                grouped[freq] = []
            grouped[freq].append(job)
        
        # Ordenar cada grupo por prioridad desc
        for freq in grouped:
            grouped[freq] = sorted(grouped[freq], key=lambda j: -j["priority"])
        
        return grouped
    
    def print_schedule(self):
        """Muestra schedule ordenado, útil para CLI y doctor"""
        grouped = self.get_schedule_by_frequency()
        print("\n=== RADAR SCHEDULE (respeta enable por YML) ===\n")
        for freq in ["hourly", "every 6h", "every 12h", "daily", "weekly", "monthly"]:
            if freq in grouped:
                jobs = grouped[freq]
                print(f"{freq.upper()} ({len(jobs)} jobs):")
                for job in jobs:
                    print(f"  - {job['slug']:.<20} priority={job['priority']} provider={job['provider_type']} types={job['opportunity_types']}")
                print()
        
        # Cron jobs adicionales no plugin-based: discover, notify
        print("SYSTEM JOBS:")
        scan_cfg = self.config.get("scan", {})
        print(f"  - discover: schedule={scan_cfg.get('discovery', {}).get('cron', '0 3 * * 0')} enabled={scan_cfg.get('discovery', {}).get('enabled', True)}")
        print(f"  - monitoring: schedule={scan_cfg.get('monitoring', {}).get('cron', '0 */12 * * *')} enabled={scan_cfg.get('monitoring', {}).get('enabled', True)}")
        print(f"  - notifications: digest_time={self.config.get('notifications.digest_time', '09:00')}")
        print()
    
    def validate_schedules(self) -> List[Dict[str, Any]]:
        """Valida que schedules sean coherentes, para doctor"""
        issues = []
        jobs = self.get_jobs()
        
        for job in jobs:
            schedule = job.get("schedule")
            # Validar schedule permitido
            allowed = ["daily", "weekly", "hourly", "every 12h", "every 6h", "monthly"]
            if schedule not in allowed and not schedule.startswith("0 ") and not schedule.startswith("@"):
                issues.append({
                    "slug": job["slug"],
                    "issue": f"Schedule '{schedule}' no estándar, permitidos {allowed} o cron",
                    "level": "WARN"
                })
            
            # Validar que plugin loadable
            plugin = self.loader.get_plugin(job["slug"])
            if plugin and not plugin.is_loadable:
                issues.append({
                    "slug": job["slug"],
                    "issue": f"Plugin enabled pero no loadable: status={plugin.status}, error={plugin.error}",
                    "level": "FAIL"
                })
        
        return issues
    
    def get_next_run_info(self) -> Dict[str, Any]:
        """Info de próxima ejecución (simplificado, sin APScheduler aún)"""
        jobs = self.get_jobs()
        # Simular next run basado en schedule
        now = datetime.now()
        next_runs = []
        for job in jobs:
            # Simplificación: daily -> mañana 09:00, weekly -> próximo domingo 03:00
            schedule = job["schedule"]
            if schedule == "daily":
                next_run = "mañana 09:00"
            elif schedule == "weekly":
                next_run = "domingo 03:00"
            elif schedule == "hourly":
                next_run = "próxima hora"
            else:
                next_run = f"según cron {schedule}"
            
            next_runs.append({
                "slug": job["slug"],
                "schedule": schedule,
                "next_run": next_run,
                "priority": job["priority"]
            })
        
        return {
            "now": now.isoformat(),
            "jobs": next_runs,
            "total": len(next_runs)
        }

# Singleton conveniencia

_scheduler_instance = None

def get_scheduler() -> RadarScheduler:
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = RadarScheduler()
    return _scheduler_instance
