"""
Plugins Registry - Registro 100% dinámico desde filesystem
Actualizado Ticket 003: No listas manuales en core, solo filesystem + manifest.yaml

Cada plugin es una carpeta plugins/<slug>/ con:
- manifest.yaml (obligatorio para ser considerado plugin válido)
- plugin.py (opcional, pero requerido si enabled)

Validación de manifest incluida para doctor robusto.
"""
from pathlib import Path
import yaml
from typing import Dict, List, Any, Tuple
from core.config import get_config
from core.logger import get_logger

logger = get_logger("core")

PLUGINS_DIR = Path("plugins")

# Esquema mínimo esperado para manifest válido (para doctor)
REQUIRED_MANIFEST_FIELDS = ["name", "slug", "provider_type"]
OPTIONAL_MANIFEST_FIELDS = ["description", "opportunity_types", "version", "sources", "config"]
ALLOWED_PROVIDER_TYPES = ["beautifulsoup", "playwright", "rss", "api", "json", "github", "mcp"]
ALLOWED_OPPORTUNITY_TYPES = ["contest", "grant", "residency", "fellowship", "accelerator", "hackathon", "beta", "festival", "call_for_artists", "creative_tender", "challenge", "aggregator"]

def validate_manifest(manifest: Dict[str, Any], folder_name: str) -> List[str]:
    """Valida manifest.yaml y retorna lista de errores. Vacía = válido."""
    errors = []
    if not isinstance(manifest, dict):
        errors.append(f"manifest no es dict en {folder_name}")
        return errors
    
    for field in REQUIRED_MANIFEST_FIELDS:
        if field not in manifest:
            errors.append(f"Missing required field '{field}' in {folder_name}/manifest.yaml")
    
    # slug debe coincidir con folder
    if "slug" in manifest and manifest["slug"] != folder_name:
        errors.append(f"Slug mismatch: folder '{folder_name}' != manifest slug '{manifest['slug']}'")
    
    # provider_type válido
    if "provider_type" in manifest and manifest["provider_type"] not in ALLOWED_PROVIDER_TYPES:
        errors.append(f"Invalid provider_type '{manifest['provider_type']}' in {folder_name}, allowed: {ALLOWED_PROVIDER_TYPES}")
    
    # opportunity_types válidos
    if "opportunity_types" in manifest:
        ots = manifest["opportunity_types"]
        if not isinstance(ots, list):
            errors.append(f"opportunity_types debe ser lista en {folder_name}")
        else:
            for ot in ots:
                if ot not in ALLOWED_OPPORTUNITY_TYPES:
                    errors.append(f"Invalid opportunity_type '{ot}' in {folder_name}, allowed: {ALLOWED_OPPORTUNITY_TYPES}")
    
    return errors

def discover_plugins(validate: bool = True) -> List[Dict[str, Any]]:
    """
    Escanea plugins/ y retorna lista de plugins encontrados con manifest.
    100% dinámico: no hay lista manual en core, solo filesystem.
    
    Cada entrada contiene:
    - slug, name, provider_type, opportunity_types, manifest, manifest_errors, has_plugin_py, folder
    """
    plugins = []
    if not PLUGINS_DIR.exists():
        logger.warning(f"Plugins dir not exists: {PLUGINS_DIR}")
        return plugins
    
    for folder in PLUGINS_DIR.iterdir():
        if not folder.is_dir():
            continue
        if folder.name.startswith("__") or folder.name.startswith("."):
            continue
        if folder.name in ("selectors", "__pycache__"):
            continue
        
        manifest_path = folder / "manifest.yaml"
        plugin_py = folder / "plugin.py"
        
        # Si no hay manifest.yaml, NO es plugin válido (estricto para registro dinámico real)
        if not manifest_path.exists():
            logger.debug(f"Skipping {folder.name}: no manifest.yaml")
            continue
        
        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        except Exception as e:
            logger.warning(f"Failed to parse manifest {folder.name}/manifest.yaml: {e}")
            manifest = {}
            # Registrar igualmente como inválido para doctor
            plugins.append({
                "slug": folder.name,
                "name": folder.name.title(),
                "provider_type": "unknown",
                "opportunity_types": [],
                "has_plugin_py": plugin_py.exists(),
                "folder": str(folder),
                "manifest": manifest,
                "manifest_errors": [f"YAML parse error: {e}"],
                "manifest_valid": False,
                "is_valid": False
            })
            continue
        
        errors = validate_manifest(manifest, folder.name) if validate else []
        
        plugin_info = {
            "slug": manifest.get("slug", folder.name),
            "name": manifest.get("name", folder.name.title()),
            "description": manifest.get("description", ""),
            "provider_type": manifest.get("provider_type", "beautifulsoup"),
            "opportunity_types": manifest.get("opportunity_types", ["contest"]),
            "has_plugin_py": plugin_py.exists(),
            "folder": str(folder),
            "manifest": manifest,
            "manifest_errors": errors,
            "manifest_valid": len(errors) == 0,
            "is_valid": len(errors) == 0,  # para doctor
            "version": manifest.get("version", "0.0")
        }
        plugins.append(plugin_info)
    
    # Ordenado por slug para determinismo
    return sorted(plugins, key=lambda x: x["slug"])

def get_enabled_plugins() -> List[Dict[str, Any]]:
    """
    Retorna solo plugins con enabled=true en config.yaml
    Registro dinámico: primero descubre filesystem, luego filtra por config.
    Si plugin existe en filesystem pero no en config, por defecto DISABLED (más seguro para producto).
    """
    cfg = get_config()
    all_plugins = discover_plugins(validate=True)
    enabled = []
    
    for p in all_plugins:
        # Si no está en config, no está habilitado por defecto (salvo que config diga lo contrario)
        # Esto evita que un plugin skeleton se active solo por existir carpeta
        cfg_entry = cfg.get(f"plugins.{p['slug']}")
        if cfg_entry is None:
            # Si no está en config, asumimos disabled para producción
            is_enabled = False
        else:
            is_enabled = cfg_entry.get("enabled", False)
        
        if is_enabled:
            # Enriquecer con config
            p["config"] = cfg_entry or {}
            p["schedule"] = cfg_entry.get("schedule", "daily") if cfg_entry else "daily"
            p["priority"] = cfg_entry.get("priority", 5) if cfg_entry else 5
            enabled.append(p)
    
    return enabled

def get_plugin_status_report() -> Dict[str, Any]:
    """
    Reporte completo para doctor: incluye válidos, inválidos, enabled sin implementación, etc.
    """
    all_plugins = discover_plugins(validate=True)
    cfg = get_config()
    enabled_plugins = get_enabled_plugins()
    enabled_slugs = {p["slug"] for p in enabled_plugins}
    
    report = {
        "total_found": len(all_plugins),
        "total_valid": len([p for p in all_plugins if p["manifest_valid"]]),
        "total_invalid": len([p for p in all_plugins if not p["manifest_valid"]]),
        "total_enabled": len(enabled_plugins),
        "plugins": [],
        "invalid_manifests": [],
        "enabled_without_code": [],
        "config_orphans": []  # plugins en config pero sin folder
    }
    
    for p in all_plugins:
        is_enabled = p["slug"] in enabled_slugs
        plugin_report = {
            "slug": p["slug"],
            "name": p["name"],
            "enabled": is_enabled,
            "schedule": p.get("schedule") or (cfg.get(f"plugins.{p['slug']}.schedule") if cfg.get(f"plugins.{p['slug']}") else "daily"),
            "has_code": p["has_plugin_py"],
            "manifest_valid": p["manifest_valid"],
            "manifest_errors": p["manifest_errors"],
            "opportunity_types": p["opportunity_types"],
            "provider_type": p["provider_type"],
            "version": p["version"]
        }
        report["plugins"].append(plugin_report)
        
        if not p["manifest_valid"]:
            report["invalid_manifests"].append(p)
        
        if is_enabled and not p["has_plugin_py"]:
            report["enabled_without_code"].append(p)
    
    # Config orphans: plugins mencionados en config.yaml pero sin carpeta en filesystem
    config_plugins = cfg.get_plugins()
    fs_slugs = {p["slug"] for p in all_plugins}
    for slug in config_plugins.keys():
        if slug not in fs_slugs and slug != "discovery":  # discovery no es plugin, es job
            report["config_orphans"].append(slug)
    
    return report

def load_plugin_class(slug: str):
    """
    Carga dinámica de la clase Provider de un plugin.
    No lista manual, importa por convención plugins/<slug>/plugin.py
    Retorna clase o None.
    """
    import importlib.util
    plugin_path = PLUGINS_DIR / slug / "plugin.py"
    if not plugin_path.exists():
        return None
    
    spec = importlib.util.spec_from_file_location(f"plugins.{slug}.plugin", plugin_path)
    if not spec or not spec.loader:
        return None
    
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        # Convención: buscar clase que herede de Provider, o primera clase terminada en Provider
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if isinstance(attr, type):
                # Heuristic: nombre termina en Provider y no es base Provider
                if attr_name.endswith("Provider") and attr_name != "Provider":
                    return attr
        return None
    except Exception as e:
        logger.warning(f"Failed to load plugin class {slug}: {e}")
        return None
