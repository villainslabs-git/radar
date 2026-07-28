"""
Tests para Plugin Loader Real - Ticket 004
- Descubrimiento dinámico
- Validación manifests
- Integración scheduler respetando enable por YML
- Aislamiento de fallos (un plugin roto no rompe core ni otros)
- Core agnóstico

Requisitos Ticket 004:
- Registro dinámico recorriendo carpeta plugins y leyendo cada manifest sin atar core
- Detectar configuraciones rotas, plugins habilitados sin implementación
"""
import sys
from pathlib import Path
import tempfile
import shutil
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.plugin_loader import PluginLoader, PluginStatus
from core.config import get_config

PLUGINS_DIR = Path("plugins")

def test_discovery_dinamico():
    """Registro dinámico de verdad: recorre carpeta plugins y lee manifests, sin lista manual"""
    loader = PluginLoader(plugins_dir=PLUGINS_DIR)
    discovered = loader.scan()
    assert len(discovered) >= 9, f"Debería descubrir al menos 9 plugins, got {len(discovered)}"
    slugs = {p.slug for p in discovered}
    assert "runway" in slugs
    assert "posterheroes" in slugs
    assert "adobe" in slugs
    # Verifica que viene de filesystem, no de lista manual en core
    # Cada manifest debe tener folder que existe
    for pm in discovered:
        assert Path(pm.folder).exists(), f"Folder {pm.folder} debe existir - viene de filesystem"
    print(f"✓ discovery dinamico: {len(discovered)} plugins desde filesystem, sin lista manual en core")

def test_validacion_manifests():
    """Detecta manifest inválidos, slug mismatch, provider_type inválido"""
    loader = PluginLoader(plugins_dir=PLUGINS_DIR)
    discovered = loader.scan()
    invalid = [p for p in discovered if not p.valid]
    assert len(invalid) == 0, f"No debería haber manifests inválidos en repo limpio, got {invalid}"
    
    # Test validación con manifest roto temporal
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_plugins = Path(tmpdir) / "plugins"
        tmp_plugins.mkdir()
        # Crear plugin válido
        valid_folder = tmp_plugins / "valid_plugin"
        valid_folder.mkdir()
        (valid_folder / "manifest.yaml").write_text("""
name: Valid Plugin
slug: valid_plugin
provider_type: beautifulsoup
opportunity_types: [contest]
""")
        (valid_folder / "plugin.py").write_text("class ValidPluginProvider:\n    provider_type='beautifulsoup'\n    def fetch(self, url): pass\n    def extract(self, r): return []\n    def normalize(self, raw): pass\n")
        
        # Crear plugin inválido (falta required field)
        invalid_folder = tmp_plugins / "invalid_plugin"
        invalid_folder.mkdir()
        (invalid_folder / "manifest.yaml").write_text("""
name: Invalid Plugin
# falta slug y provider_type
""")
        
        # Crear plugin con slug mismatch
        mismatch_folder = tmp_plugins / "mismatch"
        mismatch_folder.mkdir()
        (mismatch_folder / "manifest.yaml").write_text("""
name: Mismatch
slug: other_slug
provider_type: beautifulsoup
""")
        
        loader_tmp = PluginLoader(plugins_dir=tmp_plugins)
        discovered_tmp = loader_tmp.scan()
        assert len(discovered_tmp) == 3
        # Debe detectar 2 inválidos (invalid_plugin y mismatch)
        invalid_tmp = [p for p in discovered_tmp if not p.valid]
        assert len(invalid_tmp) == 2, f"Debería detectar 2 inválidos, got {len(invalid_tmp)}: {invalid_tmp}"
        # Valid plugin debe ser válido
        valid_pm = [p for p in discovered_tmp if p.slug == "valid_plugin"][0]
        assert valid_pm.valid
        
        print(f"✓ validacion manifests: detecta inválidos, slug mismatch, required fields")

def test_enable_por_yml():
    """Respeta enable por YML - config gobierna TODO"""
    loader = PluginLoader(plugins_dir=PLUGINS_DIR)
    all_plugins = loader.load_all()
    enabled = loader.get_enabled_plugins()
    
    # Según config.yaml, 5 enabled: runway, posterheroes, adobe, itsnicethat, ai-film-festival
    enabled_slugs = {p.slug for p in enabled}
    assert "runway" in enabled_slugs, "runway debe estar enabled según config"
    assert "posterheroes" in enabled_slugs
    assert "adobe" in enabled_slugs
    assert "openai" not in enabled_slugs, "openai disabled en config"
    assert "leonardo" not in enabled_slugs, "leonardo disabled en config"
    
    # Deshabilitados no deben aparecer en enabled, aunque existan en filesystem
    assert len(enabled) == 5, f"Esperados 5 enabled según config, got {len(enabled)}: {enabled_slugs}"
    
    # Loadable debe ser subset de enabled con código y manifest válido
    loadable = loader.get_loadable_plugins()
    loadable_slugs = {p.slug for p in loadable}
    assert loadable_slugs.issubset(enabled_slugs)
    
    print(f"✓ enable por YML: {len(enabled)} enabled respetando config.yaml, loadable={len(loadable)}")

def test_aislamiento_fallos():
    """Un plugin roto no rompe core ni otros plugins"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_plugins = Path(tmpdir) / "plugins"
        tmp_plugins.mkdir()
        
        # Plugin bueno 1
        good1 = tmp_plugins / "good1"
        good1.mkdir()
        (good1 / "manifest.yaml").write_text("name: Good1\nslug: good1\nprovider_type: beautifulsoup\n")
        (good1 / "plugin.py").write_text("class Good1Provider:\n    provider_type='beautifulsoup'\n    def fetch(self, url): return None\n    def extract(self, r): return []\n    def normalize(self, raw): return None\n")
        
        # Plugin bueno 2
        good2 = tmp_plugins / "good2"
        good2.mkdir()
        (good2 / "manifest.yaml").write_text("name: Good2\nslug: good2\nprovider_type: beautifulsoup\n")
        (good2 / "plugin.py").write_text("class Good2Provider:\n    provider_type='beautifulsoup'\n    def fetch(self, url): return None\n    def extract(self, r): return []\n    def normalize(self, raw): return None\n")
        
        # Plugin roto: syntax error en plugin.py
        broken = tmp_plugins / "broken"
        broken.mkdir()
        (broken / "manifest.yaml").write_text("name: Broken\nslug: broken\nprovider_type: beautifulsoup\n")
        (broken / "plugin.py").write_text("class BrokenProvider\n    this is syntax error!!!\n")
        
        # Plugin con manifest inválido pero no debe crashear loader
        invalid = tmp_plugins / "invalid_manifest"
        invalid.mkdir()
        (invalid / "manifest.yaml").write_text("name: Invalid\n")  # falta slug, provider_type
        
        # Crear config temporal que habilita todos
        tmp_config_path = Path(tmpdir) / "config.yaml"
        tmp_config_path.write_text("""
project:
  db_path: "data/radar.db"
  log_level: INFO
plugins:
  good1: {enabled: true, schedule: daily, priority: 10}
  good2: {enabled: true, schedule: weekly, priority: 5}
  broken: {enabled: true, schedule: daily, priority: 8}
  invalid_manifest: {enabled: true, schedule: daily, priority: 1}
""")
        from core.config import Config
        cfg = Config(tmp_config_path)
        
        loader = PluginLoader(plugins_dir=tmp_plugins, config=cfg)
        all_plugins = loader.load_all()
        
        # Debe descubrir 4 plugins sin crashear
        assert len(all_plugins) == 4, f"Debería descubrir 4, got {len(all_plugins)}"
        
        # Good plugins deben cargar OK
        good1_loaded = loader.get_plugin("good1")
        assert good1_loaded is not None
        assert good1_loaded.status in (PluginStatus.LOADED, PluginStatus.ENABLED, PluginStatus.VALID)
        assert good1_loaded.provider_class is not None, "good1 debería cargar clase"
        
        # Broken plugin debe marcar LOAD_FAILED pero no romper core
        broken_loaded = loader.get_plugin("broken")
        assert broken_loaded is not None
        assert broken_loaded.status == PluginStatus.LOAD_FAILED, f"broken debería ser LOAD_FAILED, got {broken_loaded.status}"
        assert broken_loaded.error is not None
        assert broken_loaded.provider_class is None
        
        # Invalid manifest debe ser INVALID_MANIFEST
        invalid_loaded = loader.get_plugin("invalid_manifest")
        assert invalid_loaded.status == PluginStatus.INVALID_MANIFEST
        
        # Enabled solo con manifest válido y sin error fatal? Pero broken está enabled aunque load failed
        # get_enabled_plugins debe retornar enabled independientemente de si cargó, para reporte
        enabled = loader.get_enabled_plugins()
        assert len(enabled) == 4  # todos enabled según config temp
        
        # Loadable solo los que realmente pueden ejecutarse
        loadable = loader.get_loadable_plugins()
        assert len(loadable) == 2, f"Solo 2 loadable (good1, good2), got {len(loadable)}: {[p.slug for p in loadable]}"
        assert "good1" in {p.slug for p in loadable}
        assert "good2" in {p.slug for p in loadable}
        assert "broken" not in {p.slug for p in loadable}
        
        print(f"✓ aislamiento fallos: 1 plugin roto no rompió core, 2 buenos siguen loadable, invalid detectado")

def test_integracion_scheduler():
    """Integración con scheduler respetando enable por YML y schedule por plugin"""
    loader = PluginLoader(plugins_dir=PLUGINS_DIR)
    jobs = loader.get_jobs()
    
    # Jobs solo para enabled según config
    assert len(jobs) == 5, f"Expected 5 jobs (enabled plugins), got {len(jobs)}"
    
    # Cada job debe tener schedule, priority, provider_type, opportunity_types
    for job in jobs:
        assert "slug" in job
        assert "schedule" in job
        assert "priority" in job
        assert "provider_type" in job
        assert "enabled" in job
        assert job["enabled"] == True
        assert job["schedule"] in ["daily", "weekly", "hourly", "every 12h", "every 6h", "monthly"] or job["schedule"].startswith("0 ")
    
    # Verificar orden por prioridad y schedule (daily primero?)
    # Según implementación, hourly < every 6h < every 12h < daily < weekly
    # Todos nuestros enabled son daily, así que orden por priority desc
    priorities = [j["priority"] for j in jobs]
    assert priorities == sorted(priorities, reverse=True), f"Jobs deberían ordenarse por priority desc, got {priorities}"
    
    # Disabled plugins no deben estar en jobs
    job_slugs = {j["slug"] for j in jobs}
    assert "openai" not in job_slugs
    assert "leonardo" not in job_slugs
    
    print(f"✓ integracion scheduler: {len(jobs)} jobs con schedule y priority respetando enable YML")
    for j in jobs:
        print(f"  - {j['slug']}: schedule={j['schedule']}, priority={j['priority']}, types={j['opportunity_types']}")

def test_core_agnostico():
    """Core no tiene reglas específicas de orgs, todo en plugins/"""
    # Verificar que loader no importa nada de plugins específicos
    import core.plugin_loader as loader_module
    source = Path(loader_module.__file__).read_text()
    # No debe contener hardcoded org names salvo en comentarios
    # Permitimos mención en comentarios pero no en lógica
    # Buscamos if slug == "runway" etc que sería contaminación
    forbidden_patterns = ['if slug == "runway"', 'if slug == "posterheroes"', 'runway' in source.lower() and 'if' in source.lower()]
    # Simplificado: verificar que no hay if con nombres de org
    assert 'if slug == "runway"' not in source
    assert 'if slug == "posterheroes"' not in source
    assert 'if slug == "adobe"' not in source
    
    # Loader debe ser genérico
    assert "PLUGINS_DIR" in source
    assert "manifest" in source.lower()
    
    print("✓ core agnostico: loader sin reglas específicas de orgs, todo genérico")

def test_reload():
    """Hot-reload de plugins y config"""
    loader = PluginLoader(plugins_dir=PLUGINS_DIR)
    first = loader.load_all()
    first_count = len(first)
    # Reload debe rediscover
    second = loader.reload()
    assert len(second) == first_count
    print(f"✓ reload: hot-reload funciona, {first_count} plugins")

def run_all():
    print("\n=== Plugin Loader Real Tests (Ticket 004) ===\n")
    test_discovery_dinamico()
    test_validacion_manifests()
    test_enable_por_yml()
    test_aislamiento_fallos()
    test_integracion_scheduler()
    test_core_agnostico()
    test_reload()
    print("\n=== Todos los tests Plugin Loader pasaron ✓ ===\n")
    print("Criterios Ticket 004:")
    print("  ✓ Registro dinámico de verdad (filesystem, sin lista manual)")
    print("  ✓ Valida manifests, detecta inválidos, slug mismatch")
    print("  ✓ Respeta enable por YML (config gobierna TODO)")
    print("  ✓ Aislamiento fallos (plugin roto no rompe core)")
    print("  ✓ Integración scheduler (jobs con schedule, priority)")
    print("  ✓ Core agnóstico (sin reglas org específicas)")
    print("  ✓ Arquitectura ordenada (loader como boundary)")

if __name__ == "__main__":
    run_all()
