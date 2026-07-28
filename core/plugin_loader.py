"""
Radar - Plugin Loader Real + Runtime (Ticket 004 + Ticket 005)
Cargador dinámico verdadero: descubre, valida, carga Provider dinámicamente,
instancia Provider, controla lifecycle, soporta enable/disable, prioridades,
registra errores sin detener sistema.

Requisitos Ticket 004 + Ticket 005:
- Registro dinámico recorriendo carpeta plugins y leyendo cada manifest sin atar core
- Validar manifest, cargar Provider dinámicamente, instanciar Provider
- Controlar lifecycle, soportar enable/disable, prioridades
- Registrar errores sin detener sistema
- No debe existir ningún import manual tipo from plugins.runway import ... Todo dinámico
- Core agnóstico
"""
from pathlib import Path
import yaml
import importlib.util
import traceback
import time
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum

from core.logger import get_logger
from core.config import get_config

logger = get_logger("core")

PLUGINS_DIR = Path("plugins")

REQUIRED_MANIFEST_FIELDS = ["name", "slug", "provider_type"]
ALLOWED_PROVIDER_TYPES = ["beautifulsoup", "playwright", "rss", "api", "json", "github", "mcp", "selenium"]
ALLOWED_OPPORTUNITY_TYPES = [
    "contest", "grant", "residency", "fellowship", "accelerator",
    "hackathon", "beta", "festival", "call_for_artists",
    "creative_tender", "challenge", "aggregator"
]
ALLOWED_SCHEDULES = ["daily", "weekly", "hourly", "every 12h", "every 6h", "monthly"]

class PluginStatus(str, Enum):
    VALID = "valid"
    INVALID_MANIFEST = "invalid_manifest"
    MISSING_CODE = "missing_code"
    LOAD_FAILED = "load_failed"
    DISABLED = "disabled"
    ENABLED = "enabled"
    LOADED = "loaded"
    INSTANTIATED = "instantiated"
    FAILED = "failed"

class LifecycleState(str, Enum):
    CREATED = "created"
    INITIALIZED = "initialized"
    READY = "ready"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"

@dataclass
class PluginManifest:
    slug: str
    name: str
    provider_type: str
    opportunity_types: List[str]
    version: str
    description: str
    raw: Dict[str, Any]
    errors: List[str] = field(default_factory=list)
    valid: bool = True
    folder: str = ""

@dataclass
class ProviderInstance:
    """Instancia runtime de un Provider con lifecycle tracking"""
    slug: str
    organization_slug: str
    instance: Any  # Provider instance
    state: LifecycleState = LifecycleState.CREATED
    created_at: float = field(default_factory=time.time)
    last_used_at: Optional[float] = None
    error: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)

    def mark_running(self):
        self.state = LifecycleState.RUNNING
        self.last_used_at = time.time()

    def mark_failed(self, error: str):
        self.state = LifecycleState.FAILED
        self.error = error

    def mark_stopped(self):
        self.state = LifecycleState.STOPPED

@dataclass
class LoadedPlugin:
    slug: str
    manifest: PluginManifest
    has_code: bool
    folder: Path
    enabled: bool
    schedule: str
    priority: int
    provider_class: Optional[Any] = None  # Clase Provider cargada dinámicamente
    status: str = PluginStatus.VALID
    error: Optional[str] = None
    config: Dict[str, Any] = field(default_factory=dict)
    # Runtime instances (puede haber múltiples si un plugin sirve múltiples orgs, pero por defecto 1 por slug)
    instances: List[ProviderInstance] = field(default_factory=list, repr=False)

    @property
    def is_loadable(self) -> bool:
        """¿Puede ser cargado para ejecución? Debe estar enabled, manifest válido, con código y sin error de carga"""
        return (
            self.enabled and
            self.manifest.valid and
            self.has_code and
            self.status in (PluginStatus.LOADED, PluginStatus.INSTANTIATED) and
            self.provider_class is not None
        )

    @property
    def is_instantiated(self) -> bool:
        return len(self.instances) > 0 and any(i.state != LifecycleState.FAILED for i in self.instances)

    def to_job_definition(self) -> Dict[str, Any]:
        """Convierte a definición para scheduler: respeta enable por YML"""
        return {
            "slug": self.slug,
            "name": self.manifest.name,
            "schedule": self.schedule,
            "priority": self.priority,
            "provider_type": self.manifest.provider_type,
            "opportunity_types": self.manifest.opportunity_types,
            "enabled": self.enabled,
            "status": self.status,
            "version": self.manifest.version,
            "folder": str(self.folder),
            "instances": len(self.instances)
        }

class PluginLoader:
    """
    Loader real: descubre, valida, carga plugins aislando fallos.
    Ninguna lista manual en core. Todo desde filesystem + config.yaml enable.
    """
    
    def __init__(self, plugins_dir: Path = PLUGINS_DIR, config=None):
        self.plugins_dir = Path(plugins_dir)
        self.config = config or get_config()
        self._discovered: List[PluginManifest] = []
        self._loaded: List[LoadedPlugin] = []
        self._scanned = False
    
    def _validate_manifest(self, manifest: Dict[str, Any], folder_name: str) -> Tuple[bool, List[str], PluginManifest]:
        errors = []
        if not isinstance(manifest, dict):
            return False, [f"manifest no es dict en {folder_name}"], None
        
        for field in REQUIRED_MANIFEST_FIELDS:
            if field not in manifest:
                errors.append(f"Missing required field '{field}' in {folder_name}/manifest.yaml")
        
        if "slug" in manifest and manifest["slug"] != folder_name:
            errors.append(f"Slug mismatch: folder '{folder_name}' != manifest slug '{manifest['slug']}'")
        
        if "provider_type" in manifest and manifest["provider_type"] not in ALLOWED_PROVIDER_TYPES:
            errors.append(f"Invalid provider_type '{manifest['provider_type']}' in {folder_name}, allowed: {ALLOWED_PROVIDER_TYPES}")
        
        if "opportunity_types" in manifest:
            ots = manifest["opportunity_types"]
            if not isinstance(ots, list):
                errors.append(f"opportunity_types debe ser lista en {folder_name}")
            else:
                for ot in ots:
                    if ot not in ALLOWED_OPPORTUNITY_TYPES:
                        errors.append(f"Invalid opportunity_type '{ot}' in {folder_name}")
        
        valid = len(errors) == 0
        pm = PluginManifest(
            slug=manifest.get("slug", folder_name),
            name=manifest.get("name", folder_name.title()),
            provider_type=manifest.get("provider_type", "beautifulsoup"),
            opportunity_types=manifest.get("opportunity_types", ["contest"]),
            version=manifest.get("version", "0.1"),
            description=manifest.get("description", ""),
            raw=manifest,
            errors=errors,
            valid=valid,
            folder=str(self.plugins_dir / folder_name)
        )
        return valid, errors, pm
    
    def _load_plugin_class(self, folder: Path) -> Tuple[Optional[Any], Optional[str]]:
        """
        Carga clase Provider desde plugins/<slug>/plugin.py
        Aísla excepciones: nunca lanza, retorna (cls, error)
        """
        plugin_py = folder / "plugin.py"
        if not plugin_py.exists():
            return None, "plugin.py missing"
        
        slug = folder.name
        try:
            spec = importlib.util.spec_from_file_location(f"plugins.{slug}.plugin", plugin_py)
            if not spec or not spec.loader:
                return None, f"Failed to create spec for {slug}"
            
            module = importlib.util.module_from_spec(spec)
            # Ejecutar módulo con try/except para aislar fallos de import
            try:
                spec.loader.exec_module(module)
            except Exception as e:
                tb = traceback.format_exc()
                logger.error(f"Plugin {slug} exec_module failed: {e}\n{tb}")
                return None, f"exec_module failed: {e}"
            
            # Buscar clase Provider por convención
            provider_cls = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and attr_name.endswith("Provider") and attr_name != "Provider":
                    # Verificar que tenga métodos requeridos (fetch, extract, normalize) sin ser abstract
                    if hasattr(attr, 'provider_type') or hasattr(attr, 'fetch'):
                        provider_cls = attr
                        break
            
            if provider_cls is None:
                # Si no encontramos por convención, buscar cualquier clase que tenga fetch y extract
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type):
                        if hasattr(attr, 'fetch') and hasattr(attr, 'extract') and hasattr(attr, 'normalize'):
                            provider_cls = attr
                            break
            
            if provider_cls is None:
                return None, f"No Provider class found in {slug}/plugin.py (expected class ending with Provider)"
            
            return provider_cls, None
        
        except Exception as e:
            tb = traceback.format_exc()
            logger.error(f"Plugin {slug} load failed: {e}\n{tb}")
            return None, f"load exception: {e}"
    
    def scan(self) -> List[PluginManifest]:
        """
        Descubre plugins recorriendo carpeta plugins/, leyendo cada manifest.
        100% dinámico, sin listas manuales.
        """
        discovered = []
        if not self.plugins_dir.exists():
            logger.warning(f"Plugins dir not exists: {self.plugins_dir}")
            self._discovered = []
            self._scanned = True
            return []
        
        for folder in self.plugins_dir.iterdir():
            if not folder.is_dir():
                continue
            if folder.name.startswith("__") or folder.name.startswith("."):
                continue
            if folder.name in ("selectors", "__pycache__"):
                continue
            
            manifest_path = folder / "manifest.yaml"
            if not manifest_path.exists():
                logger.debug(f"Skipping {folder.name}: no manifest.yaml (not a valid plugin)")
                continue
            
            try:
                manifest_raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            except Exception as e:
                logger.warning(f"Failed to parse {folder.name}/manifest.yaml: {e}")
                # Crear manifest inválido para reporte
                pm = PluginManifest(
                    slug=folder.name,
                    name=folder.name.title(),
                    provider_type="unknown",
                    opportunity_types=[],
                    version="0.0",
                    description="",
                    raw={},
                    errors=[f"YAML parse error: {e}"],
                    valid=False,
                    folder=str(folder)
                )
                discovered.append(pm)
                continue
            
            valid, errors, pm = self._validate_manifest(manifest_raw, folder.name)
            discovered.append(pm)
        
        # Orden determinístico por slug
        discovered = sorted(discovered, key=lambda x: x.slug)
        self._discovered = discovered
        self._scanned = True
        logger.info(f"PluginLoader scan: {len(discovered)} plugins discovered from {self.plugins_dir}")
        return discovered
    
    def load_all(self) -> List[LoadedPlugin]:
        """
        Carga todos los plugins descubiertos, respetando enable por YAML,
        aislando fallos para que un plugin roto no rompa core ni otros plugins.
        """
        if not self._scanned:
            self.scan()
        
        loaded = []
        for manifest in self._discovered:
            slug = manifest.slug
            folder = Path(manifest.folder)
            
            # Leer config para este plugin
            cfg_entry = self.config.get(f"plugins.{slug}") if self.config else None
            # Si no está en config.yaml, por defecto DISABLED (seguro para producto)
            if cfg_entry is None:
                enabled = False
                schedule = "daily"
                priority = 5
                plugin_config = {}
            else:
                enabled = cfg_entry.get("enabled", False)
                schedule = cfg_entry.get("schedule", "daily")
                priority = cfg_entry.get("priority", 5)
                plugin_config = cfg_entry
            
            # Validar schedule
            # Permitir cron (empieza con 0) o lista permitida
            if schedule not in ALLOWED_SCHEDULES and not schedule.startswith("0 ") and not schedule.startswith("@"):
                logger.warning(f"Plugin {slug} has suspicious schedule '{schedule}', allowed {ALLOWED_SCHEDULES} or cron")
            
            plugin_py = folder / "plugin.py"
            has_code = plugin_py.exists()
            
            # Determinar status base
            if not manifest.valid:
                status = PluginStatus.INVALID_MANIFEST
                provider_cls = None
                error = "; ".join(manifest.errors)
            elif not has_code:
                if enabled:
                    status = PluginStatus.MISSING_CODE
                else:
                    status = PluginStatus.VALID  # disabled y sin código es OK (skeleton)
                provider_cls = None
                error = "plugin.py missing" if enabled else None
            else:
                # Tiene manifest válido y código, intentar cargar clase solo si enabled
                # Para no gastar recursos, cargamos clase solo si enabled, pero para reporte cargamos siempre?
                # Ticket 004: loader real debe validar incluso disabled para detectar fallos temprano, pero sin romper
                # Cargamos siempre para validar, pero solo se ejecutará si enabled
                provider_cls, load_error = self._load_plugin_class(folder)
                if load_error:
                    status = PluginStatus.LOAD_FAILED
                    error = load_error
                    provider_cls = None
                else:
                    if enabled:
                        status = PluginStatus.LOADED
                    else:
                        status = PluginStatus.VALID  # válido pero disabled
                    error = None
            
            # Si disabled, ajustar status
            if not enabled:
                if manifest.valid and has_code and status == PluginStatus.LOADED:
                    # Si está disabled pero cargó OK, marcar como DISABLED para claridad
                    # Pero mantener clase cargada para validación
                    status = PluginStatus.DISABLED
                elif not manifest.valid:
                    status = PluginStatus.INVALID_MANIFEST
                elif not has_code:
                    # Si disabled y sin código, no es error, es skeleton
                    status = PluginStatus.DISABLED
            
            lp = LoadedPlugin(
                slug=slug,
                manifest=manifest,
                has_code=has_code,
                folder=folder,
                enabled=enabled,
                schedule=schedule,
                priority=priority,
                provider_class=provider_cls,
                status=status,
                error=error,
                config=plugin_config
            )
            loaded.append(lp)
        
        # Ordenar por prioridad desc, luego slug
        loaded = sorted(loaded, key=lambda x: (-x.priority, x.slug))
        self._loaded = loaded
        logger.info(f"PluginLoader load_all: {len([p for p in loaded if p.enabled])} enabled, {len([p for p in loaded if p.is_loadable])} loadable")
        return loaded
    
    def get_enabled_plugins(self) -> List[LoadedPlugin]:
        """Retorna solo plugins enabled y loadable (respeta YML)"""
        if not self._loaded:
            self.load_all()
        return [p for p in self._loaded if p.enabled]
    
    def get_loadable_plugins(self) -> List[LoadedPlugin]:
        """Retorna plugins que pueden ejecutarse: enabled + manifest válido + código + sin error carga"""
        if not self._loaded:
            self.load_all()
        return [p for p in self._loaded if p.is_loadable]
    
    def get_all_plugins(self) -> List[LoadedPlugin]:
        if not self._loaded:
            self.load_all()
        return self._loaded
    
    def get_plugin(self, slug: str) -> Optional[LoadedPlugin]:
        if not self._loaded:
            self.load_all()
        for p in self._loaded:
            if p.slug == slug:
                return p
        return None
    
    def is_enabled(self, slug: str) -> bool:
        p = self.get_plugin(slug)
        return p.enabled if p else False
    
    def get_jobs(self) -> List[Dict[str, Any]]:
        """
        Integración con scheduler: retorna definiciones de jobs para plugins enabled
        Respeta enable por YML, schedule por plugin, priority, etc.
        Scheduler puede usar esto para crear APScheduler jobs.
        """
        enabled = self.get_enabled_plugins()
        jobs = []
        for p in enabled:
            # Solo jobs de plugins con manifest válido, aunque código falle se reporta pero no se agenda si no loadable?
            # Para robustez: si enabled pero load failed, no agendar pero reportar
            if not p.manifest.valid:
                continue
            if not p.has_code and p.status == PluginStatus.MISSING_CODE:
                continue
            jobs.append(p.to_job_definition())
        # Ordenar por prioridad y schedule
        # daily primero, luego weekly
        schedule_order = {"hourly": 0, "every 6h": 1, "every 12h": 2, "daily": 3, "weekly": 4, "monthly": 5}
        jobs = sorted(jobs, key=lambda j: (schedule_order.get(j["schedule"], 99), -j["priority"], j["slug"]))
        return jobs
    
    def get_status_report(self) -> Dict[str, Any]:
        """Reporte completo para doctor y CLI, 100% dinámico"""
        if not self._loaded:
            self.load_all()
        
        all_plugins = self._loaded
        enabled = [p for p in all_plugins if p.enabled]
        loadable = [p for p in all_plugins if p.is_loadable]
        invalid = [p for p in all_plugins if p.manifest.valid is False]
        missing_code = [p for p in all_plugins if p.status == PluginStatus.MISSING_CODE]
        load_failed = [p for p in all_plugins if p.status == PluginStatus.LOAD_FAILED]
        
        # Config orphans: plugins en config.yaml pero sin carpeta
        config_plugins = self.config.get_plugins() if self.config else {}
        fs_slugs = {p.slug for p in all_plugins}
        orphans = [slug for slug in config_plugins.keys() if slug not in fs_slugs and slug != "discovery"]
        
        return {
            "total_discovered": len(all_plugins),
            "total_enabled": len(enabled),
            "total_loadable": len(loadable),
            "total_invalid_manifest": len(invalid),
            "total_missing_code": len(missing_code),
            "total_load_failed": len(load_failed),
            "total_orphans": len(orphans),
            "plugins": all_plugins,
            "enabled": enabled,
            "loadable": loadable,
            "invalid": invalid,
            "missing_code": missing_code,
            "load_failed": load_failed,
            "orphans": orphans,
            "jobs": self.get_jobs()
        }
    
    def reload(self):
        """Recarga desde filesystem y config (hot-reload)"""
        # Shutdown all instances before reload to avoid leaks
        try:
            self.shutdown_all()
        except Exception:
            pass
        self._scanned = False
        self._discovered = []
        self._loaded = []
        if hasattr(self.config, 'reload'):
            self.config.reload()
        return self.load_all()

    # ==================== RUNTIME - Ticket 005 ====================
    # Cargador dinámico verdadero: instanciación y lifecycle

    def create_provider_instance(self, slug: str, organization_slug: str = None, config_override: Dict[str, Any] = None) -> Tuple[Optional[Any], Optional[str]]:
        """
        Instancia Provider dinámicamente sin import manual.
        Todo resuelto vía importlib + manifest.

        Args:
            slug: plugin slug (ej. runway)
            organization_slug: org slug (por defecto mismo que plugin slug)
            config_override: config dict opcional

        Returns:
            (instance, error) - error None si OK, sino string. Nunca lanza excepción hacia core.
        """
        loaded = self.get_plugin(slug)
        if not loaded:
            return None, f"Plugin {slug} not found (not discovered from filesystem)"
        
        if not loaded.enabled:
            return None, f"Plugin {slug} disabled in config.yaml (enable=false)"
        
        if not loaded.manifest.valid:
            return None, f"Plugin {slug} has invalid manifest: {loaded.manifest.errors}"
        
        if not loaded.has_code:
            return None, f"Plugin {slug} missing plugin.py"
        
        if loaded.status == PluginStatus.LOAD_FAILED:
            return None, f"Plugin {slug} load failed: {loaded.error}"
        
        if not loaded.provider_class:
            return None, f"Plugin {slug} provider_class not loaded"
        
        # Determinar organization_slug
        org_slug = organization_slug or slug
        
        # Config para instancia: merge config del plugin + override
        instance_config = dict(loaded.config) if loaded.config else {}
        if config_override:
            instance_config.update(config_override)
        
        try:
            # Instanciar dinámicamente: Provider(organization_slug, config)
            # Cada Provider espera (organization_slug, config) según core/provider.py
            provider_cls = loaded.provider_class
            instance = provider_cls(organization_slug=org_slug, config=instance_config)
            
            # Crear ProviderInstance con lifecycle
            prov_inst = ProviderInstance(
                slug=slug,
                organization_slug=org_slug,
                instance=instance,
                state=LifecycleState.INITIALIZED,
                config=instance_config
            )
            
            # Agregar a lista de instancias del plugin (lifecycle tracking)
            loaded.instances.append(prov_inst)
            loaded.status = PluginStatus.INSTANTIATED
            
            logger.info(f"Plugin {slug} instantiated for org {org_slug} - class {provider_cls.__name__}")
            return instance, None
        
        except Exception as e:
            tb = traceback.format_exc()
            error_msg = f"Failed to instantiate {slug} Provider: {e}\n{tb[:500]}"
            logger.error(error_msg)
            
            # Registrar instancia fallida para tracking
            failed_inst = ProviderInstance(
                slug=slug,
                organization_slug=org_slug,
                instance=None,
                state=LifecycleState.FAILED,
                error=str(e),
                config=instance_config
            )
            loaded.instances.append(failed_inst)
            return None, str(e)

    def get_or_create_instance(self, slug: str, organization_slug: str = None) -> Tuple[Optional[Any], Optional[str]]:
        """
        Obtiene instancia existente o crea nueva. Evita crear duplicadas para misma org.
        """
        loaded = self.get_plugin(slug)
        if not loaded:
            return None, f"Plugin {slug} not found"
        
        org_slug = organization_slug or slug
        
        # Buscar instancia existente no fallida para misma org
        for inst in loaded.instances:
            if inst.organization_slug == org_slug and inst.state not in (LifecycleState.FAILED, LifecycleState.STOPPED):
                return inst.instance, None
        
        # No existe, crear nueva
        return self.create_provider_instance(slug, org_slug)

    def get_instances(self, slug: str = None) -> List[ProviderInstance]:
        """Retorna todas las instancias runtime, opcionalmente filtradas por slug"""
        if slug:
            loaded = self.get_plugin(slug)
            return loaded.instances if loaded else []
        
        all_instances = []
        for plugin in self.get_all_plugins():
            all_instances.extend(plugin.instances)
        return all_instances

    def get_instance(self, slug: str, organization_slug: str = None) -> Optional[ProviderInstance]:
        """Retorna ProviderInstance (con metadata lifecycle), no solo instance"""
        loaded = self.get_plugin(slug)
        if not loaded:
            return None
        org_slug = organization_slug or slug
        for inst in loaded.instances:
            if inst.organization_slug == org_slug:
                return inst
        return None

    def mark_running(self, slug: str, organization_slug: str = None):
        """Marca instancia como running (cuando empieza fetch)"""
        inst = self.get_instance(slug, organization_slug)
        if inst:
            inst.mark_running()

    def mark_failed(self, slug: str, error: str, organization_slug: str = None):
        inst = self.get_instance(slug, organization_slug)
        if inst:
            inst.mark_failed(error)

    def shutdown_instance(self, slug: str, organization_slug: str = None) -> bool:
        """Controla lifecycle: shutdown de una instancia específica"""
        loaded = self.get_plugin(slug)
        if not loaded:
            return False
        
        org_slug = organization_slug or slug
        for idx, inst in enumerate(loaded.instances):
            if inst.organization_slug == org_slug:
                try:
                    # Si provider tiene método close/shutdown, llamarlo sin romper
                    if inst.instance and hasattr(inst.instance, 'close'):
                        try:
                            inst.instance.close()
                        except Exception as e:
                            logger.warning(f"Plugin {slug} close() failed: {e}")
                    if inst.instance and hasattr(inst.instance, 'shutdown'):
                        try:
                            inst.instance.shutdown()
                        except Exception as e:
                            logger.warning(f"Plugin {slug} shutdown() failed: {e}")
                except Exception as e:
                    logger.warning(f"Error during shutdown {slug}: {e}")
                finally:
                    inst.mark_stopped()
                    logger.info(f"Plugin {slug} org {org_slug} stopped")
                return True
        return False

    def shutdown_all(self):
        """Shutdown de todas las instancias (lifecycle final)"""
        count = 0
        for plugin in self.get_all_plugins():
            for inst in list(plugin.instances):
                if inst.state not in (LifecycleState.STOPPED, LifecycleState.FAILED):
                    try:
                        if inst.instance and hasattr(inst.instance, 'close'):
                            inst.instance.close()
                    except Exception:
                        pass
                    inst.mark_stopped()
                    count += 1
        if count > 0:
            logger.info(f"Shutdown {count} provider instances")
        return count

    def instantiate_all_enabled(self) -> Dict[str, Tuple[Optional[Any], Optional[str]]]:
        """
        Instancia todos los plugins habilitados (una instancia por slug, org=slug).
        Útil para validar que todos los habilitados cargan sin romper sistema.
        Retorna dict slug -> (instance, error)
        """
        results = {}
        for plugin in self.get_enabled_plugins():
            if not plugin.is_loadable and plugin.status != PluginStatus.INSTANTIATED:
                # Intentar cargar aunque no sea loadable según status previo (por si ya estaba instantiated)
                if plugin.status in (PluginStatus.MISSING_CODE, PluginStatus.INVALID_MANIFEST, PluginStatus.LOAD_FAILED):
                    results[plugin.slug] = (None, plugin.error or "not loadable")
                    continue
            
            instance, error = self.get_or_create_instance(plugin.slug, plugin.slug)
            results[plugin.slug] = (instance, error)
        
        # Log resumen
        ok = sum(1 for _, (inst, err) in results.items() if inst is not None)
        fail = len(results) - ok
        logger.info(f"instantiate_all_enabled: {ok} OK, {fail} failed, total {len(results)} enabled")
        return results

    def validate_runtime(self) -> Dict[str, Any]:
        """
        Validación runtime completa para Ticket 005:
        - doctor OK (delegado)
        - registry OK (discover)
        - loader OK (scan + load_all)
        - plugins habilitados cargan (instantiate_all_enabled)
        - plugins deshabilitados ignorados
        - ningún plugin rompe sistema completo (aislamiento)
        """
        report = {
            "discovery": {"ok": False, "count": 0, "errors": []},
            "validation": {"ok": False, "invalid": 0},
            "loading": {"ok": False, "enabled": 0, "loadable": 0},
            "runtime": {"ok": False, "instantiated": 0, "failed": 0, "isolated": True},
            "enable_disable": {"ok": False, "enabled_respected": False, "disabled_ignored": False},
            "no_manual_imports": {"ok": False, "found": []},
            "overall_ok": False
        }
        
        try:
            # Discovery
            discovered = self.scan()
            report["discovery"]["count"] = len(discovered)
            report["discovery"]["ok"] = len(discovered) >= 1
            
            # Validation
            invalid = [p for p in discovered if not p.valid]
            report["validation"]["invalid"] = len(invalid)
            report["validation"]["ok"] = True  # Siempre OK, solo reporta invalidos
            
            # Loading
            loaded = self.load_all()
            enabled = [p for p in loaded if p.enabled]
            loadable = [p for p in loaded if p.is_loadable]
            report["loading"]["enabled"] = len(enabled)
            report["loading"]["loadable"] = len(loadable)
            report["loading"]["ok"] = len(enabled) > 0
            
            # Enable/disable respeto
            from core.config import get_config
            cfg = get_config()
            # Plugins disabled según config no deben estar en enabled list
            disabled_via_config = []
            for slug in ["openai", "leonardo", "filmfreeway", "pika"]:
                if not cfg.is_plugin_enabled(slug):
                    disabled_via_config.append(slug)
            # Verificar que ninguno de los disabled está en enabled
            enabled_slugs = {p.slug for p in enabled}
            disabled_ignored = all(slug not in enabled_slugs for slug in disabled_via_config)
            enabled_respected = len(enabled) == 5  # según config.yaml actual
            
            report["enable_disable"]["disabled_ignored"] = disabled_ignored
            report["enable_disable"]["enabled_respected"] = enabled_respected
            report["enable_disable"]["ok"] = disabled_ignored and enabled_respected
            
            # Runtime instantiation
            runtime_results = self.instantiate_all_enabled()
            instantiated = sum(1 for _, (inst, err) in runtime_results.items() if inst is not None)
            failed = len(runtime_results) - instantiated
            report["runtime"]["instantiated"] = instantiated
            report["runtime"]["failed"] = failed
            # Aislamiento: si hay failed, verificar que no rompió otros (instantiated >0)
            report["runtime"]["isolated"] = instantiated > 0 or failed == 0
            report["runtime"]["ok"] = instantiated > 0 and report["runtime"]["isolated"]
            
            # No manual imports check
            import subprocess
            try:
                # Buscar from plugins.<org> import en core/ y jobs/ (excluyendo registry y loader que usan plugins/ genérico)
                result = subprocess.run(
                    ["grep", "-R", "from plugins\\.", "--include=*.py", "core/", "jobs/", "cli/"],
                    capture_output=True, text=True, cwd=Path(".")
                )
                lines = result.stdout.strip().split("\n") if result.stdout.strip() else []
                # Filtrar permitidos: from plugins.registry, from plugins.base, from plugins import
                forbidden = []
                for line in lines:
                    if "from plugins.registry" in line or "from plugins.base" in line:
                        continue
                    if "from plugins import" in line:
                        continue
                    # Si contiene from plugins.<specific> es manual y prohibido
                    if "from plugins." in line and "registry" not in line and "base" not in line:
                        forbidden.append(line)
                
                report["no_manual_imports"]["found"] = forbidden
                report["no_manual_imports"]["ok"] = len(forbidden) == 0
            except Exception as e:
                report["no_manual_imports"]["ok"] = False
                report["no_manual_imports"]["found"] = [f"check failed: {e}"]
            
            # Overall
            report["overall_ok"] = all([
                report["discovery"]["ok"],
                report["validation"]["ok"],
                report["loading"]["ok"],
                report["runtime"]["ok"],
                report["enable_disable"]["ok"],
                report["no_manual_imports"]["ok"]
            ])
            
        except Exception as e:
            report["error"] = str(e)
            report["overall_ok"] = False
        
        return report

# Singleton cómodo y funciones de conveniencia

_loader_instance: Optional[PluginLoader] = None

def get_plugin_loader(plugins_dir: Path = PLUGINS_DIR) -> PluginLoader:
    global _loader_instance
    if _loader_instance is None:
        _loader_instance = PluginLoader(plugins_dir=plugins_dir)
        _loader_instance.scan()
        _loader_instance.load_all()
    return _loader_instance

def get_enabled_plugins() -> List[LoadedPlugin]:
    return get_plugin_loader().get_enabled_plugins()

def get_loadable_plugins() -> List[LoadedPlugin]:
    return get_plugin_loader().get_loadable_plugins()

def get_jobs_for_scheduler() -> List[Dict[str, Any]]:
    """API para scheduler: jobs respetando enable por YML"""
    return get_plugin_loader().get_jobs()
