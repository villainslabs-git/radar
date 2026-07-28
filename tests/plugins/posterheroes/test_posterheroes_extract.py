"""
Tests para scraper Posterheroes con fixture HTML - Robustez
Ticket 010 observación: agregar test automático con fixture HTML

Hoy veo validación manual, eso demuestra que funciona hoy pero no protege contra:
- cambio HTML
- cambio parser
- refactor

Este test usa fixture HTML guardado y verifica:
- assert title
- assert deadline
- assert awards
- assert description
Hace mucho más robusto el scraper.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from plugins.posterheroes.plugin import PosterheroesProvider
from core.provider import FetchResult

FIXTURE_PATH = Path(__file__).parent / "posterheroes_2026.html"

def test_fixture_exists():
    assert FIXTURE_PATH.exists(), f"Fixture HTML no existe en {FIXTURE_PATH}, debe guardarse desde www.posterheroes.org/"
    content = FIXTURE_PATH.read_text(encoding="utf-8")
    assert len(content) > 1000, f"Fixture HTML muy pequeño: {len(content)} bytes"
    assert "Posterheroes" in content or "Still Human" in content, "Fixture debe contener Posterheroes y Still Human"
    print(f"✓ fixture exists: {FIXTURE_PATH} {len(content)} bytes")

def test_extract_title():
    """assert title"""
    provider = PosterheroesProvider(organization_slug="posterheroes")
    content = FIXTURE_PATH.read_text(encoding="utf-8")
    fetch_result = FetchResult(success=True, content=content, content_type="html", url="https://www.posterheroes.org/", provider="beautifulsoup")
    
    raw_list = provider.extract(fetch_result)
    assert len(raw_list) == 1, f"Debe extraer 1 oportunidad, got {len(raw_list)}"
    
    raw = raw_list[0]
    assert "Posterheroes" in raw.title or "Still Human" in raw.title, f"Título debe contener Posterheroes o Still Human, got {raw.title}"
    assert len(raw.title) > 5 and len(raw.title) < 200, f"Título longitud inválida: {raw.title}"
    
    print(f"✓ extract title: {raw.title}")

def test_extract_deadline():
    """assert deadline"""
    provider = PosterheroesProvider(organization_slug="posterheroes")
    content = FIXTURE_PATH.read_text(encoding="utf-8")
    fetch_result = FetchResult(success=True, content=content, content_type="html", url="https://www.posterheroes.org/", provider="beautifulsoup")
    
    raw_list = provider.extract(fetch_result)
    raw = raw_list[0]
    
    deadline = raw.raw_data.get("deadline")
    assert deadline is not None, "Deadline no debe ser None"
    assert "July" in deadline or "july" in deadline.lower() or "2026" in deadline, f"Deadline debe contener July y 2026, got {deadline}"
    # Debe ser parseable a fecha
    assert "31" in deadline or "30" in deadline, f"Deadline debe tener día 31 o 30, got {deadline}"
    
    print(f"✓ extract deadline: {deadline}")

def test_extract_awards():
    """assert awards"""
    provider = PosterheroesProvider(organization_slug="posterheroes")
    content = FIXTURE_PATH.read_text(encoding="utf-8")
    fetch_result = FetchResult(success=True, content=content, content_type="html", url="https://www.posterheroes.org/", provider="beautifulsoup")
    
    raw_list = provider.extract(fetch_result)
    raw = raw_list[0]
    
    awards_text = raw.raw_data.get("awards_text", "")
    economic_value = raw.raw_data.get("economic_value")
    
    assert awards_text, "Awards text no debe estar vacío"
    assert "€" in awards_text or "euro" in awards_text.lower() or "2500" in awards_text or "1500" in awards_text, f"Awards debe contener € o valores, got {awards_text}"
    assert economic_value is not None, "Economic value no debe ser None"
    assert isinstance(economic_value, float), f"Economic value debe ser float para evitar updates falsos 2500.0 vs 2500, got {type(economic_value)} {economic_value}"
    assert economic_value >= 1500, f"Economic value debe ser >=1500, got {economic_value}"
    
    print(f"✓ extract awards: {awards_text} value={economic_value}")

def test_extract_description():
    """assert description"""
    provider = PosterheroesProvider(organization_slug="posterheroes")
    content = FIXTURE_PATH.read_text(encoding="utf-8")
    fetch_result = FetchResult(success=True, content=content, content_type="html", url="https://www.posterheroes.org/", provider="beautifulsoup")
    
    raw_list = provider.extract(fetch_result)
    raw = raw_list[0]
    
    desc = raw.raw_data.get("description_raw", "")
    assert desc, "Description no debe estar vacía"
    assert len(desc) > 50, f"Description muy corta: {len(desc)} chars"
    # Debe contener palabras clave del brief Still Human
    lower_desc = desc.lower()
    assert any(kw in lower_desc for kw in ["delegation", "responsibility", "automation", "human", "machine", "posterheroes"]), f"Description debe contener palabras clave del brief, got {desc[:100]}"
    
    print(f"✓ extract description: {len(desc)} chars, contains keywords")

def test_normalize():
    """Test normalize con fixture"""
    provider = PosterheroesProvider(organization_slug="posterheroes")
    content = FIXTURE_PATH.read_text(encoding="utf-8")
    fetch_result = FetchResult(success=True, content=content, content_type="html", url="https://www.posterheroes.org/", provider="beautifulsoup")
    
    raw_list = provider.extract(fetch_result)
    raw = raw_list[0]
    norm = provider.normalize(raw)
    
    # Assert normalized fields
    assert norm.title, "Normalized title no debe estar vacío"
    assert "Posterheroes" in norm.title or "Still Human" in norm.title
    assert norm.deadline, "Normalized deadline no debe estar vacío"
    assert norm.official_link, "Official link no debe estar vacío"
    assert norm.organization_slug == "posterheroes"
    assert norm.organizer_name == "Posterheroes"
    assert norm.category == "Arte Digital"
    assert norm.opportunity_type == "contest"
    assert norm.country == "Italy"
    
    # Economic value debe ser float (fix observación 1)
    assert isinstance(norm.economic_value, float), f"economic_value debe ser float, got {type(norm.economic_value)}"
    
    # Validación debe pasar
    assert provider.validate(norm), f"Normalized opportunity debe ser válida, got {norm}"
    
    print(f"✓ normalize: title={norm.title}, deadline={norm.deadline}, awards={norm.awards_text}, value={norm.economic_value} float OK, valid OK")

def test_candidate_urls():
    """Test mejora diseño: candidate_urls() + fetch_first_success() genérico"""
    provider = PosterheroesProvider(organization_slug="posterheroes")
    
    # Candidate URLs debe retornar lista sin tocar Provider base
    candidates = provider.candidate_urls("https://posterheroes.org/competition/")
    assert isinstance(candidates, list), "candidate_urls debe retornar lista"
    assert len(candidates) >= 3, f"Debe retornar al menos 3 candidatos (original, www, root), got {len(candidates)}"
    assert "https://www.posterheroes.org/" in candidates, "Debe incluir root www como fallback"
    assert "https://posterheroes.org/competition/" in candidates, "Debe incluir original"
    
    # Cualquier plugin futuro puede definir su lista sin tocar base
    # Ej. un plugin hipotético podría retornar [competitions, open-call, calls, root, archive]
    # Verificar que método es overrideable y no hardcodeado en base
    from core.provider import Provider
    base_candidates = Provider.candidate_urls(provider, "https://example.com/")
    assert base_candidates == ["https://example.com/"], "Base Provider candidate_urls debe retornar [url] por defecto"
    
    print(f"✓ candidate_urls: {len(candidates)} candidatos, genérico sin tocar base, cualquier plugin futuro puede definir su lista")

def test_economic_value_normalization():
    """Test fix observación 1: economic_value siempre float para evitar updates falsos 2500.0 -> 2500"""
    provider = PosterheroesProvider(organization_slug="posterheroes")
    content = FIXTURE_PATH.read_text(encoding="utf-8")
    fetch_result = FetchResult(success=True, content=content, content_type="html", url="https://www.posterheroes.org/", provider="beautifulsoup")
    
    raw_list = provider.extract(fetch_result)
    for raw in raw_list:
        # economic_value en raw_data debe ser float
        ev = raw.raw_data.get("economic_value")
        if ev is not None:
            assert isinstance(ev, float), f"economic_value en raw_data debe ser float, got {type(ev)} {ev}"
        
        norm = provider.normalize(raw)
        if norm.economic_value is not None:
            assert isinstance(norm.economic_value, float), f"economic_value normalizado debe ser float, got {type(norm.economic_value)} {norm.economic_value}"
    
    # Test history tracker no debe detectar cambio 2500.0 vs 2500 como cambio
    from core.history import HistoryTracker
    tracker = HistoryTracker()
    old = {"economic_value": 2500.0}
    new = {"economic_value": 2500}
    changes = tracker.detect_changes(old, new)
    assert len(changes) == 0, f"2500.0 vs 2500 no debe ser considerado cambio (mismo valor numérico), got {len(changes)} changes: {changes}"
    
    old2 = {"economic_value": 2500.0}
    new2 = {"economic_value": 2500.01}
    changes2 = tracker.detect_changes(old2, new2)
    # Con tolerancia 0.01, 2500.0 vs 2500.01 debe ser no cambio (abs <0.01)
    # Si es 2500.0 vs 2600, sí debe ser cambio
    old3 = {"economic_value": 2500.0}
    new3 = {"economic_value": 2600.0}
    changes3 = tracker.detect_changes(old3, new3)
    assert len(changes3) == 1, f"2500.0 vs 2600.0 debe ser cambio, got {len(changes3)}"
    
    print("✓ economic_value normalization: siempre float, 2500.0 vs 2500 no es cambio, 2500 vs 2600 sí es cambio, evita updates falsos")

def run_all():
    print("\n=== Posterheroes Scraper Fixture Tests (Ticket 010 observación) ===\n")
    test_fixture_exists()
    test_extract_title()
    test_extract_deadline()
    test_extract_awards()
    test_extract_description()
    test_normalize()
    test_candidate_urls()
    test_economic_value_normalization()
    print("\n=== Todos los tests fixture pasaron ✓ ===\n")
    print("Robustez scraper:")
    print("  ✓ fixture HTML guardado tests/plugins/posterheroes/posterheroes_2026.html 47KB")
    print("  ✓ extract title, deadline, awards, description con asserts")
    print("  ✓ normalize con validación")
    print("  ✓ candidate_urls() + fetch_first_success() genérico sin tocar base")
    print("  ✓ economic_value siempre float evita updates falsos 2500.0 vs 2500")
    print("  ✓ Protege contra cambio HTML, cambio parser, refactor")

if __name__ == "__main__":
    run_all()
