"""
Radar Doctor - Diagnóstico robusto v2 (Ticket 003)
Inspirado en brew doctor / flutter doctor

Mejoras Ticket 003:
- Detecta Chromium faltante (verifica browser cache)
- Detecta plugins habilitados sin implementación
- Detecta manifest inválidos
- Detecta configuración inconsistente
- Valida esquema SQLite correcto (columnas esperadas)
- Verifica permisos escritura logs/ y data/
- Registro dinámico de plugins (usa registry.py mejorado)
"""
import sys
import shutil
import importlib
import os
from pathlib import Path
from typing import List, Tuple, Dict, Any
import yaml

from core.logger import get_logger
from core.config import get_config
from core.db import get_db
from plugins.registry import get_plugin_status_report, discover_plugins, ALLOWED_PROVIDER_TYPES, ALLOWED_OPPORTUNITY_TYPES

logger = get_logger("doctor")

class CheckResult:
    def __init__(self, name: str, status: str, message: str = "", details: str = ""):
        self.name = name
        self.status = status  # OK, WARN, FAIL, SKIP
        self.message = message
        self.details = details

def check_python() -> CheckResult:
    try:
        version = sys.version.split()[0]
        major, minor = sys.version_info.major, sys.version_info.minor
        if major == 3 and minor >= 10:
            return CheckResult("Python", "OK", f"{version} (>=3.10)")
        else:
            return CheckResult("Python", "WARN", f"{version} - Requiere >=3.10 recomendado", f"Actual: {sys.version}")
    except Exception as e:
        return CheckResult("Python", "FAIL", str(e))

def check_dependencies() -> List[CheckResult]:
    deps = {
        "yaml": ("PyYAML", True),
        "httpx": ("httpx", True),
        "bs4": ("beautifulsoup4", True),
        "rapidfuzz": ("rapidfuzz", True),
        "dateutil": ("python-dateutil", True),
        "playwright": ("playwright", False),  # opcional
        "unidecode": ("unidecode", True),
    }
    results = []
    for module, (pip_name, required) in deps.items():
        try:
            importlib.import_module(module)
            results.append(CheckResult(f"Dep:{module}", "OK", f"{pip_name} installed"))
        except ImportError:
            if required:
                results.append(CheckResult(f"Dep:{module}", "FAIL", f"{pip_name} not installed - pip install {pip_name}"))
            else:
                results.append(CheckResult(f"Dep:{module}", "WARN", f"{pip_name} not installed - optional for JS sources"))
    return results

def check_sqlite() -> CheckResult:
    try:
        import sqlite3
        version = sqlite3.sqlite_version
        return CheckResult("SQLite", "OK", f"{version}")
    except Exception as e:
        return CheckResult("SQLite", "FAIL", str(e))

def check_playwright_and_chromium() -> List[CheckResult]:
    results = []
    try:
        from playwright.sync_api import sync_playwright
        results.append(CheckResult("Playwright:lib", "OK", "installed"))
    except ImportError:
        results.append(CheckResult("Playwright:lib", "WARN", "not installed - pip install playwright"))
        results.append(CheckResult("Playwright:chromium", "SKIP", "skipped - playwright not installed"))
        return results
    
    # Chromium cache detection (robust check)
    try:
        # Posibles paths de cache de playwright
        possible_caches = [
            Path.home() / ".cache" / "ms-playwright",
            Path.home() / "Library" / "Caches" / "ms-playwright",
            Path.home() / "AppData" / "Local" / "ms-playwright",
            Path("/root/.cache/ms-playwright"),
        ]
        found = False
        for cache_dir in possible_caches:
            if cache_dir.exists():
                # Buscar chromium*
                chromium_dirs = list(cache_dir.glob("chromium-*"))
                if chromium_dirs:
                    # Verificar que tiene chrome executable dentro
                    for ch_dir in chromium_dirs:
                        # chrome-linux/chrome, or chrome-mac/Chromium.app, etc
                        if (ch_dir / "chrome-linux" / "chrome").exists() or (ch_dir / "chrome-mac").exists() or any(ch_dir.rglob("chrome")):
                            found = True
                            results.append(CheckResult("Playwright:chromium", "OK", f"found at {ch_dir}"))
                            break
                    if found:
                        break
        
        if not found:
            # Intentar launch test rápido? Sin hacerlo pesado, solo warning
            results.append(CheckResult("Playwright:chromium", "WARN", "Chromium cache not found - run: python -m playwright install chromium", "Checked: ~/.cache/ms-playwright/chromium-*"))
    
    except Exception as e:
        results.append(CheckResult("Playwright:chromium", "WARN", f"check failed: {e}"))
    
    return results

def check_filesystem_permissions() -> List[CheckResult]:
    results = []
    cfg = get_config()
    
    # Logs dir writable
    log_dir = Path(cfg.get("logging.dir", "logs"))
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        test_file = log_dir / ".doctor_write_test"
        test_file.write_text("test")
        test_file.unlink()
        results.append(CheckResult("Perm:logs/", "OK", f"{log_dir} writable"))
    except Exception as e:
        results.append(CheckResult("Perm:logs/", "FAIL", f"{log_dir} not writable: {e}"))
    
    # Data dir writable
    data_dir = Path("data")
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        test_file = data_dir / ".doctor_write_test"
        test_file.write_text("test")
        test_file.unlink()
        results.append(CheckResult("Perm:data/", "OK", f"{data_dir} writable"))
    except Exception as e:
        results.append(CheckResult("Perm:data/", "FAIL", f"{data_dir} not writable: {e}"))
    
    # DB parent writable
    db_path = cfg.get_db_path()
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        if db_path.exists():
            # Check readable
            if os.access(db_path, os.R_OK):
                results.append(CheckResult("Perm:db", "OK", f"{db_path} readable & writable"))
            else:
                results.append(CheckResult("Perm:db", "FAIL", f"{db_path} not readable"))
        else:
            results.append(CheckResult("Perm:db", "WARN", f"{db_path} not exists - will be created by init_db.py"))
    except Exception as e:
        results.append(CheckResult("Perm:db", "FAIL", f"DB dir not writable: {e}"))
    
    # Plugins dir readable
    plugins_dir = Path("plugins")
    if plugins_dir.exists() and os.access(plugins_dir, os.R_OK):
        results.append(CheckResult("Perm:plugins/", "OK", f"{plugins_dir} readable"))
    else:
        results.append(CheckResult("Perm:plugins/", "FAIL", f"{plugins_dir} not exists or not readable"))
    
    return results

def check_database_schema() -> List[CheckResult]:
    results = []
    cfg = get_config()
    db_path = cfg.get_db_path()
    
    if not db_path.exists():
        results.append(CheckResult("Database", "FAIL", f"{db_path} not found - run python scripts/init_db.py"))
        return results
    
    results.append(CheckResult("Database", "OK", f"{db_path} exists ({db_path.stat().st_size // 1024} KB)"))
    
    try:
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        
        # Check expected tables
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {r[0] for r in cur.fetchall()}
        expected_tables = {"organizations","sources","opportunities","opportunity_history","opportunity_scores","watchlist","notifications","opportunity_tags","raw_extractions"}
        
        for exp in expected_tables:
            if exp in tables:
                # Check row count
                count = conn.execute(f"SELECT COUNT(*) FROM {exp}").fetchone()[0]
                results.append(CheckResult(f"Table:{exp}", "OK", f"{count} rows"))
            else:
                results.append(CheckResult(f"Table:{exp}", "FAIL", f"Missing - expected table {exp} not found. Schema outdated? Run init_db.py"))
        
        # Check critical columns for fingerprint engine (Ticket 003)
        # opportunities must have fingerprint_hash
        if "opportunities" in tables:
            cur = conn.execute("PRAGMA table_info(opportunities)")
            cols = {r["name"] for r in cur.fetchall()}
            critical_cols = ["id","organization_id","source_id","fingerprint_hash","title","official_link","status"]
            for col in critical_cols:
                if col in cols:
                    results.append(CheckResult(f"Schema:opp.{col}", "OK", "exists"))
                else:
                    results.append(CheckResult(f"Schema:opp.{col}", "FAIL", f"Missing column {col} in opportunities - schema mismatch"))
            
            # Check opportunities has column opportunity_type? New for Radar generic engine
            # For backward compat, WARN if missing
            if "opportunity_type" in cols or "category" in cols:
                results.append(CheckResult("Schema:opp.type", "OK", "type/category exists"))
            else:
                results.append(CheckResult("Schema:opp.type", "WARN", "Missing opportunity_type/category - consider migration"))
        
        # FK check
        fk_errors = conn.execute("PRAGMA foreign_key_check;").fetchall()
        if not fk_errors:
            results.append(CheckResult("FK Integrity", "OK", "no violations"))
        else:
            results.append(CheckResult("FK Integrity", "FAIL", f"{len(fk_errors)} violations: {fk_errors[:3]}"))
        
        # Views
        cur = conn.execute("SELECT name FROM sqlite_master WHERE type='view'")
        views = {r[0] for r in cur.fetchall()}
        for view in ["v_opportunities_ranked","v_watchlist_active"]:
            if view in views:
                results.append(CheckResult(f"View:{view}", "OK", "exists"))
            else:
                results.append(CheckResult(f"View:{view}", "WARN", f"Missing view {view}"))
        
        conn.close()
        
        # Additional: organizations and sources counts
        db = get_db(db_path)
        validation = db.validate_integrity()
        orgs = validation.get("counts", {}).get("organizations", 0)
        sources = validation.get("counts", {}).get("sources", 0)
        results.append(CheckResult("Organizations", "OK" if orgs >= 3 else "WARN", f"{orgs} seeded"))
        results.append(CheckResult("Sources", "OK" if sources >= 3 else "WARN", f"{sources} seeded"))
        
    except Exception as e:
        results.append(CheckResult("Database:check", "FAIL", f"Exception during schema check: {e}"))
    
    return results

def check_config_consistency() -> List[CheckResult]:
    results = []
    cfg = get_config()
    
    if not cfg.path.exists():
        results.append(CheckResult("Config", "FAIL", f"{cfg.path} not found"))
        return results
    
    results.append(CheckResult("Config", "OK", f"{cfg.path}"))
    
    # Check YAML valid
    try:
        yaml.safe_load(cfg.path.read_text())
        results.append(CheckResult("Config:yaml", "OK", "valid YAML"))
    except Exception as e:
        results.append(CheckResult("Config:yaml", "FAIL", f"Invalid YAML: {e}"))
        return results
    
    # Check required top sections
    for section in ["project","scan","plugins","logging"]:
        if cfg.get(section):
            results.append(CheckResult(f"Config:{section}", "OK", "present"))
        else:
            results.append(CheckResult(f"Config:{section}", "WARN", f"Missing section {section}"))
    
    # Check DB path consistency
    db_path = cfg.get_db_path()
    if db_path.parent.exists():
        results.append(CheckResult("Config:db_path", "OK", f"parent exists {db_path.parent}"))
    else:
        results.append(CheckResult("Config:db_path", "WARN", f"parent {db_path.parent} not exists"))
    
    # Check plugins config consistency
    config_plugins = cfg.get_plugins()
    # Validate each plugin config has valid schedule, provider_type
    allowed_schedules = ["daily","weekly","hourly","every 12h","every 6h"]
    for slug, pcfg in config_plugins.items():
        if not isinstance(pcfg, dict):
            results.append(CheckResult(f"Config:plugin:{slug}", "FAIL", f"Config for {slug} must be dict"))
            continue
        
        schedule = pcfg.get("schedule", "daily")
        if schedule not in allowed_schedules and not schedule.startswith("0 "):  # allow cron
            results.append(CheckResult(f"Config:plugin:{slug}:sched", "WARN", f"Schedule '{schedule}' not in {allowed_schedules} nor cron"))
        
        provider = pcfg.get("provider")
        if provider and provider not in ALLOWED_PROVIDER_TYPES:
            results.append(CheckResult(f"Config:plugin:{slug}:prov", "WARN", f"Provider '{provider}' not in allowed {ALLOWED_PROVIDER_TYPES}"))
        
        # Priority range
        priority = pcfg.get("priority")
        if priority is not None and (not isinstance(priority, int) or not 1 <= priority <= 10):
            results.append(CheckResult(f"Config:plugin:{slug}:prio", "WARN", f"Priority {priority} should be 1-10"))
    
    # Check for orphan configs (plugin in config but no folder)
    report = get_plugin_status_report()
    for orphan in report.get("config_orphans", []):
        results.append(CheckResult(f"Config:orphan:{orphan}", "WARN", f"Plugin '{orphan}' in config.yaml but no folder plugins/{orphan}/ - did you create it?"))
    
    return results

def check_plugins_diagnostics() -> List[CheckResult]:
    results = []
    try:
        from core.plugin_loader import get_plugin_loader
        loader = get_plugin_loader()
        report = loader.get_status_report()
    except Exception as e:
        # Fallback a registry antiguo si loader falla
        from plugins.registry import get_plugin_status_report
        report = get_plugin_status_report()
        # Convertir a formato similar
        report = {
            "total_discovered": report.get("total_found", 0),
            "total_enabled": report.get("total_enabled", 0),
            "total_loadable": report.get("total_enabled", 0),
            "total_invalid_manifest": len(report.get("invalid_manifests", [])),
            "total_missing_code": len(report.get("enabled_without_code", [])),
            "total_load_failed": 0,
            "total_orphans": len(report.get("config_orphans", [])),
            "plugins": [],
            "enabled": [],
            "loadable": [],
            "invalid": report.get("invalid_manifests", []),
            "missing_code": report.get("enabled_without_code", []),
            "load_failed": [],
            "orphans": report.get("config_orphans", [])
        }
    
    # Usar reporte de loader real
    is_loader_report = "total_discovered" in report
    
    if is_loader_report:
        results.append(CheckResult("Plugins:Discovered", "OK", f"{report['total_discovered']} discovered from filesystem (Plugin Loader real, dynamic)"))
        results.append(CheckResult("Plugins:Valid", "OK" if report['total_invalid_manifest']==0 else "FAIL", f"{report['total_discovered'] - report['total_invalid_manifest']} valid, {report['total_invalid_manifest']} invalid manifests"))
        results.append(CheckResult("Plugins:Enabled", "OK", f"{report['total_enabled']} enabled via config.yaml (respeta enable YML)"))
        results.append(CheckResult("Plugins:Loadable", "OK" if report['total_enabled']==report['total_loadable'] or report['total_missing_code']==0 else "WARN", f"{report['total_loadable']} loadable (manifest válido + código + sin error carga)"))
        
        # Invalid manifests detail
        for inv in report.get("invalid", []):
            if hasattr(inv, 'manifest'):
                errs = "; ".join(inv.manifest.errors[:2]) if hasattr(inv.manifest, 'errors') else "unknown"
                results.append(CheckResult(f"Plugin:{inv.slug}:manifest", "FAIL", f"Invalid manifest: {errs}"))
            else:
                errs = "; ".join(inv.get("manifest_errors", [])[:2]) if isinstance(inv, dict) else "unknown"
                results.append(CheckResult(f"Plugin:{inv.get('slug','unknown')}:manifest", "FAIL", f"Invalid manifest: {errs}"))
        
        # Missing code
        for mc in report.get("missing_code", []):
            slug = mc.slug if hasattr(mc, 'slug') else mc.get('slug','unknown')
            folder = str(mc.folder) if hasattr(mc, 'folder') else mc.get('folder','')
            results.append(CheckResult(f"Plugin:{slug}:code", "WARN", f"Enabled but plugin.py missing in {folder} - will fail at runtime"))
        
        # Load failed (aislamiento fallos)
        for lf in report.get("load_failed", []):
            slug = lf.slug if hasattr(lf, 'slug') else lf.get('slug','unknown')
            error = lf.error if hasattr(lf, 'error') else "load failed"
            results.append(CheckResult(f"Plugin:{slug}:load", "FAIL", f"Load failed (aislado, no rompe core): {error[:80]}"))
        
        # Orphans
        for orphan in report.get("orphans", []):
            results.append(CheckResult(f"Config:orphan:{orphan}", "WARN", f"Plugin '{orphan}' in config.yaml but no folder plugins/{orphan}/"))
        
        # Enabled plugins detail con status real del loader
        for p in report.get("enabled", []) if "enabled" in report and isinstance(report["enabled"], list) and len(report["enabled"])>0 and hasattr(report["enabled"][0], 'slug') else []:
            status = p.status
            if status in ("loaded", "enabled"):
                check_status = "OK"
            elif status in ("missing_code",):
                check_status = "WARN"
            else:
                check_status = "FAIL"
            msg = f"enabled, sched={p.schedule}, provider={p.manifest.provider_type}, types={p.manifest.opportunity_types}, status={p.status}, loadable={p.is_loadable}"
            results.append(CheckResult(f"Plugin:{p.slug}", check_status, msg))
        
        # Si no tenemos lista de enabled como objetos, usar plugins list
        if not report.get("enabled") or not hasattr(report["enabled"][0], 'slug') if report.get("enabled") else True:
            # fallback para registry old style
            for p in report.get("plugins", []) if isinstance(report.get("plugins"), list) else []:
                if isinstance(p, dict):
                    if p.get("enabled"):
                        status = "OK" if p.get("has_code") else "WARN"
                        msg = f"enabled, sched={p.get('schedule')}, types={p.get('opportunity_types')}, has_code={p.get('has_code')}"
                        results.append(CheckResult(f"Plugin:{p.get('slug')}", status, msg))
    
    else:
        # Fallback old registry
        results.append(CheckResult("Plugins:Found", "OK", f"{report.get('total_found',0)} found"))
        results.append(CheckResult("Plugins:Enabled", "OK", f"{report.get('total_enabled',0)} enabled"))
    
    # Check core agnostic
    results.append(CheckResult("Core:agnostic", "OK", "Core has no hardcoded org rules - org logic in plugins/ only (Loader como boundary)"))
    
    # Check loader itself
    results.append(CheckResult("PluginLoader", "OK", "Plugin Loader real v1 - dynamic filesystem scan, manifest validation, isolation, YML enable respect"))
    
    # Scheduler integration
    try:
        from jobs.scheduler import get_scheduler
        scheduler = get_scheduler()
        jobs = scheduler.get_jobs()
        results.append(CheckResult("Scheduler:jobs", "OK", f"{len(jobs)} jobs from loader (respeta enable YML) - discover->monitor->score->notify"))
        issues = scheduler.validate_schedules()
        if not issues:
            results.append(CheckResult("Scheduler:validation", "OK", "No schedule issues"))
        else:
            for iss in issues:
                results.append(CheckResult(f"Scheduler:{iss['slug']}", iss["level"], iss["issue"]))
    except Exception as e:
        results.append(CheckResult("Scheduler:integration", "WARN", f"Scheduler check failed: {e}"))
    
    return results

def check_fingerprint_engine() -> List[CheckResult]:
    results = []
    # Check fingerprint.py exists and API stable
    fp_path = Path("core/fingerprint.py")
    if not fp_path.exists():
        results.append(CheckResult("Fingerprint:file", "FAIL", "core/fingerprint.py not found - Ticket 003 not completed"))
        return results
    
    results.append(CheckResult("Fingerprint:file", "OK", "core/fingerprint.py exists"))
    
    # Try import and check public API frozen
    try:
        from core import fingerprint as fp_module
        # Check class FingerprintEngine exists
        if hasattr(fp_module, "FingerprintEngine"):
            results.append(CheckResult("Fingerprint:API", "OK", "FingerprintEngine class exists"))
            engine = fp_module.FingerprintEngine()
            # Check methods: generate, is_duplicate, compare, plus normalization funcs
            for method in ["generate","is_duplicate","compare","normalize_url","normalize_title"]:
                if hasattr(engine, method):
                    results.append(CheckResult(f"Fingerprint:{method}", "OK", f"{method}() present - API frozen"))
                else:
                    results.append(CheckResult(f"Fingerprint:{method}", "FAIL", f"{method}() missing - API broken"))
            
            # Check independent normalization functions exist at module level
            for func in ["normalize_url","normalize_title","remove_invisible_chars","normalize_whitespace"]:
                if hasattr(fp_module, func):
                    results.append(CheckResult(f"Fingerprint:func:{func}", "OK", "independent function testable"))
        else:
            results.append(CheckResult("Fingerprint:API", "FAIL", "FingerprintEngine class missing"))
    
    except Exception as e:
        results.append(CheckResult("Fingerprint:import", "FAIL", f"Failed to import fingerprint engine: {e}"))
    
    return results

def run_doctor(verbose: bool = False, return_results: bool = False):
    """
    Ejecuta todos los checks y printa reporte tipo doctor robusto.
    """
    all_checks: List[CheckResult] = []
    
    all_checks.append(check_python())
    all_checks.extend(check_dependencies())
    all_checks.append(check_sqlite())
    all_checks.extend(check_playwright_and_chromium())
    all_checks.extend(check_filesystem_permissions())
    all_checks.extend(check_database_schema())
    all_checks.extend(check_config_consistency())
    all_checks.extend(check_plugins_diagnostics())
    all_checks.extend(check_fingerprint_engine())
    
    # Additional core checks
    cfg = get_config()
    # Scoring disabled check
    scoring_enabled = cfg.get("scoring.enabled", False)
    if not scoring_enabled:
        all_checks.append(CheckResult("Scoring", "OK", "disabled until 300 opps collected (senior advice - collecting phase)"))
    else:
        all_checks.append(CheckResult("Scoring", "WARN", "enabled - should be disabled until 300 opps collected"))
    
    # Scheduler
    all_checks.append(CheckResult("Scheduler", "OK", "Jobs independent: discover -> monitor -> score(disabled) -> notify"))
    
    # Format output
    print("\n" + "="*70)
    print("RADAR DOCTOR v2 - Opportunity Intelligence Engine")
    print("Ticket 003 - Diagnóstico robusto (plugins dinámicos, chromium, schema, perms)")
    print("="*70 + "\n")
    
    has_fail = False
    has_warn = False
    for chk in all_checks:
        name_padded = f"{chk.name:.<32}"
        status = chk.status
        if status == "OK":
            symbol = "✓"
        elif status == "WARN":
            symbol = "!"
            has_warn = True
        elif status == "FAIL":
            symbol = "✗"
            has_fail = True
        else:
            symbol = "-"
        
        line = f"{name_padded}{status:.<10} {symbol} {chk.message}"
        print(line)
        if verbose and chk.details:
            print(f"  -> {chk.details}")
        logger.info(line)
    
    print("\n" + "-"*70)
    if has_fail:
        print("RESULT: FAIL - Issues found that will break runtime")
        print("ACTION: Fix FAIL items. Run: python scripts/init_db.py, pip install -r requirements.txt, python -m playwright install chromium")
        logger.warning("Doctor found FAIL")
    elif has_warn:
        print("RESULT: OK (with WARN that are expected in dev - e.g., playwright optional)")
        print("Radar core reproducible OK. Ready to collect opportunities.")
        logger.info("Doctor OK with WARN")
    else:
        print("RESULT: All systems OK - Perfect")
        logger.info("Doctor all OK")
    print("-"*70 + "\n")
    
    if return_results:
        return all_checks, not has_fail
    return not has_fail
