"""
Job Monitoring - El Vigilante
Ticket 006: Usa Monitoring Engine

Flujo: Provider -> Normalize -> Fingerprint -> Database -> Logs
- Ejecuta providers via PluginLoader runtime (sin imports manuales)
- Recibe oportunidades
- Pasa todas por Fingerprint
- Inserta únicamente nuevas (deduplicación)
- Registra cambios (history tracker)
- Produce métricas
- NO scoring todavía

Uso:
    python -m jobs.monitoring --batch-size 25
    python -m radar monitor (CLI placeholder que llama a este job)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.logger import get_logger
from core.config import get_config
from core.db import get_db
from core.plugin_loader import get_plugin_loader
from core.fingerprint import FingerprintEngine
from core.history import get_history_tracker
from core.monitoring_engine import MonitoringEngine

logger = get_logger("monitor")

def run_monitoring(batch_size: int = None, only_active: bool = True):
    """
    Ejecuta monitoreo de todas las fuentes activas
    Retorna métricas
    """
    config = get_config()
    db = get_db()
    loader = get_plugin_loader()
    fingerprint_engine = FingerprintEngine(config=config)
    history_tracker = get_history_tracker()
    
    # Batch size desde config o param
    batch_size = batch_size or config.get("scan.monitoring.batch_size", 25)
    
    logger.info(f"[MONITOR_JOB] Starting with batch_size={batch_size} only_active={only_active}")
    
    engine = MonitoringEngine(
        db=db,
        loader=loader,
        fingerprint_engine=fingerprint_engine,
        history_tracker=history_tracker,
        config=config
    )
    
    metrics = engine.monitor_all(only_active=only_active, batch_size=batch_size)
    
    # Log resumen final para CLI
    logger.info(f"[MONITOR_JOB] Finished - {metrics.to_dict()}")
    
    return metrics

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Radar Monitoring Job - El Vigilante")
    parser.add_argument("--batch-size", type=int, default=None, help="Batch size de sources a monitorear")
    parser.add_argument("--all", action="store_true", help="Incluir sources inactivas")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    
    args = parser.parse_args()
    
    if args.verbose:
        import logging
        logging.getLogger("monitor").setLevel(logging.DEBUG)
    
    metrics = run_monitoring(batch_size=args.batch_size, only_active=not args.all)
    
    # Print resumen para CLI
    print("\n=== Monitoring Job Results ===")
    print(f"Sources: {metrics.total_sources}")
    print(f"Fetched: {metrics.total_fetched}")
    print(f"New: {metrics.total_new}")
    print(f"Duplicate exact: {metrics.total_duplicate_exact}")
    print(f"Duplicate approximate: {metrics.total_duplicate_approximate}")
    print(f"Updated: {metrics.total_updated}")
    print(f"History entries: {metrics.total_history_entries}")
    print(f"Alternate links added: {metrics.total_alternate_links}")
    print(f"Errors: {metrics.total_errors}")
    print(f"Duration: {metrics.duration_seconds:.2f}s")
    print("\nPer source:")
    for src in metrics.sources:
        print(f"  - {src.org_slug} {src.source_url[:40]}: new={src.new} dup={src.duplicate_exact} upd={src.updated} err={src.errors}")
