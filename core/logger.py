"""
Radar - Core Logger
Incorporado desde Ticket 002. No más print().

Logs separados por job: monitor.log, discover.log, scheduler.log, doctor.log
"""
import logging
import sys
from pathlib import Path
from logging.handlers import RotatingFileHandler
import datetime

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

# Formato senior: timestamp | level | job | message
FORMAT = "%(asctime)s | %(levelname)-7s | %(name)-18s | %(message)s"
DATE_FMT = "%Y-%m-%d %H:%M:%S"

def setup_logger(name: str, log_file: str = None, level: str = "INFO", console: bool = True) -> logging.Logger:
    """
    Crea logger con file + console.
    name: monitor, discover, scheduler, doctor, db, provider, core
    """
    logger = logging.getLogger(name)
    
    # Evitar duplicar handlers si ya existe
    if logger.handlers:
        return logger
    
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    
    formatter = logging.Formatter(FORMAT, datefmt=DATE_FMT)
    
    # File handler rotativo 5MB x 3 backups
    if log_file:
        file_path = LOG_DIR / log_file
        fh = RotatingFileHandler(file_path, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
        fh.setFormatter(formatter)
        fh.setLevel(logging.DEBUG)  # archivo siempre DEBUG
        logger.addHandler(fh)
    
    # Console handler
    if console:
        ch = logging.StreamHandler(sys.stdout)
        ch.setFormatter(formatter)
        ch.setLevel(getattr(logging, level.upper(), logging.INFO))
        logger.addHandler(ch)
    
    logger.propagate = False
    return logger

# Loggers preconfigurados para jobs independientes (punto 3 del review)
monitor_logger = lambda level="INFO": setup_logger("monitor", "monitor.log", level)
discover_logger = lambda level="INFO": setup_logger("discover", "discover.log", level)
scheduler_logger = lambda level="INFO": setup_logger("scheduler", "scheduler.log", level)
doctor_logger = lambda level="INFO": setup_logger("doctor", "doctor.log", level)
db_logger = lambda level="INFO": setup_logger("db", "db.log", level)
core_logger = lambda level="INFO": setup_logger("core", "core.log", level)

def get_logger(name: str, level: str = "INFO") -> logging.Logger:
    """Factory genérico."""
    # Mapeo nombre -> archivo
    mapping = {
        "monitor": "monitor.log",
        "discover": "discover.log", 
        "scheduler": "scheduler.log",
        "doctor": "doctor.log",
        "db": "db.log",
        "core": "core.log",
        "provider": "provider.log",
        "radar": "radar.log"
    }
    log_file = mapping.get(name, f"{name}.log")
    return setup_logger(name, log_file, level)

# Utilidad para log de excepciones con contexto
def log_exception(logger: logging.Logger, msg: str, exc: Exception):
    logger.error(f"{msg} | exception={type(exc).__name__}: {exc}", exc_info=True)
