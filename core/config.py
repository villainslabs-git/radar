"""
Radar - Config Loader
Gobierna TODO desde config.yaml (punto 2 del review senior).

Ahora config gobierna:
- scan (monitoring, discovery)
- notifications
- plugins (enabled, schedule, priority)
- logging
- countries, languages, categories
- deduplication
- etc

Un solo lugar para activar/desactivar conectores sin tocar código.
"""
import yaml
from pathlib import Path
from typing import Dict, Any, List
import os

CONFIG_PATH = Path("config/config.yaml")
DEFAULT_CONFIG = {
    "project": {
        "name": "Radar",
        "version": "3.0",
        "timezone": "America/Argentina/Buenos_Aires",
        "db_path": "data/radar.db",
        "log_level": "INFO"
    },
    "scan": {},
    "plugins": {},
    "notifications": {},
    "logging": {
        "level": "INFO",
        "files": {
            "monitor": "monitor.log",
            "discover": "discover.log",
            "scheduler": "scheduler.log",
            "doctor": "doctor.log"
        }
    }
}

class Config:
    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path
        self._data = self._load()
    
    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            # Fallback a defaults si no existe
            return DEFAULT_CONFIG
        
        with open(self.path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        
        # Merge con defaults para claves faltantes
        merged = {**DEFAULT_CONFIG, **data}
        return merged
    
    def reload(self):
        """Hot-reload para no reiniciar proceso (útil futuro)"""
        self._data = self._load()
        return self
    
    @property
    def data(self) -> Dict[str, Any]:
        return self._data
    
    def get(self, key_path: str, default=None):
        """
        Acceso por dot notation: get("plugins.runway.enabled")
        """
        keys = key_path.split(".")
        cur = self._data
        for k in keys:
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                return default
        return cur
    
    def get_plugins(self) -> Dict[str, Dict[str, Any]]:
        """Retorna dict de plugins configurados"""
        return self._data.get("plugins", {})
    
    def is_plugin_enabled(self, slug: str) -> bool:
        """¿Plugin activo? Si no está en config, default True si existe carpeta plugins/slug"""
        plugin_cfg = self.get(f"plugins.{slug}", {})
        if not plugin_cfg:
            # Si no está configurado pero carpeta existe, asumimos enabled para dev
            return (Path(f"plugins/{slug}").exists())
        return plugin_cfg.get("enabled", False)
    
    def get_plugin_schedule(self, slug: str) -> str:
        return self.get(f"plugins.{slug}.schedule", "daily")
    
    def get_db_path(self) -> Path:
        return Path(self.get("project.db_path", "data/radar.db"))
    
    def get_log_level(self) -> str:
        return self.get("project.log_level", self.get("logging.level", "INFO"))
    
    def validate(self) -> List[str]:
        """Valida config y retorna lista de warnings/errors. Para radar doctor."""
        issues = []
        # Check DB path dir exists
        db_path = self.get_db_path()
        if not db_path.parent.exists():
            issues.append(f"DB parent dir not exists: {db_path.parent}")
        
        # Check plugins
        plugins = self.get_plugins()
        for slug, cfg in plugins.items():
            if cfg.get("enabled") and not Path(f"plugins/{slug}").exists():
                issues.append(f"Plugin enabled but folder missing: plugins/{slug}")
        
        # Check required sections
        if not self.get("scan"):
            issues.append("Missing scan section")
        
        return issues

# Singleton cómodo
_config_instance = None

def get_config() -> Config:
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance
