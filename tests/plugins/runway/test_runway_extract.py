"""
Tests para scraper Runway con fixture HTML - Ticket 011
Provider real: Playwright (primario) -> fallback graceful httpx, extract BeautifulSoup.

Usa fixture HTML guardado (tests/plugins/runway/runway_2026.html, captura real de
https://aiff.runwayml.com/ - AI Film Festival 2026) y verifica 100% offline:
- assert title
- assert description
- assert deadline (normalizada a ISO 8601 UTC)
- assert awards + economic_value (float)
- assert normalize
- assert fallback Playwright -> httpx (sin internet, con mocks)
- integración PluginLoader (carga dinámica, sin imports manuales)

Protege contra: cambio HTML, cambio parser, refactor, regresión del fallback.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from plugins.runway.plugin import RunwayProvider
from core.provider import FetchResult

FIXTURE_PATH = Path(__file__).parent / "runway_2026.html"


def _fixture_fetch_result() -> FetchResult:
    content = FIXTURE_PATH.read_text(encoding="utf-8")
    return FetchResult(
        success=True,
        content=content,
        content_type="html",
        url="https://aiff.runwayml.com/",
        provider="playwright"
    )


def test_fixture_exists():
    assert FIXTURE_PATH.exists(), f"Fixture HTML no existe en {FIXTURE_PATH}, debe guardarse desde aiff.runwayml.com"
    content = FIXTURE_PATH.read_text(encoding="utf-8")
    assert len(content) > 1000, f"Fixture HTML muy pequeño: {len(content)} bytes"
    assert "AIF 2026" in content or "Runway" in content, "Fixture debe contener AIF 2026 / Runway"
    print(f"✓ fixture exists: {FIXTURE_PATH} {len(content)} bytes")


def test_extract_title():
    """assert title"""
    provider = RunwayProvider(organization_slug="runway")
    raw_list = provider.extract(_fixture_fetch_result())
    assert len(raw_list) == 1, f"Debe extraer 1 oportunidad (AIF 2026), got {len(raw_list)}"

    raw = raw_list[0]
    assert "AIF" in raw.title or "Film Festival" in raw.title or "Runway" in raw.title, \
        f"Título debe referenciar AIF/Film Festival/Runway, got {raw.title}"
    assert 5 < len(raw.title) < 200, f"Título longitud inválida: {raw.title}"

    print(f"✓ extract title: {raw.title}")


def test_extract_description():
    """assert description"""
    provider = RunwayProvider(organization_slug="runway")
    raw_list = provider.extract(_fixture_fetch_result())
    desc = raw_list[0].raw_data.get("description_raw", "")

    assert desc, "Description no debe estar vacía"
    assert len(desc) > 50, f"Description muy corta: {len(desc)} chars"
    lower = desc.lower()
    assert any(kw in lower for kw in ["aif", "festival", "ai", "creative", "artists"]), \
        f"Description debe contener palabras clave del festival, got {desc[:100]}"

    print(f"✓ extract description: {len(desc)} chars, contains keywords")


def test_extract_deadline():
    """assert deadline: 'April 27th at 4:59 PM ET' desde payload RSC del fixture"""
    provider = RunwayProvider(organization_slug="runway")
    raw_list = provider.extract(_fixture_fetch_result())
    deadline_text = raw_list[0].raw_data.get("deadline_text")

    assert deadline_text is not None, "Deadline text no debe ser None"
    assert "April" in deadline_text, f"Deadline debe contener April, got {deadline_text}"
    assert "27" in deadline_text, f"Deadline debe contener día 27, got {deadline_text}"
    assert "PM" in deadline_text or "ET" in deadline_text, f"Deadline debe contener hora ET, got {deadline_text}"

    print(f"✓ extract deadline: {deadline_text}")


def test_extract_awards_and_economic_value():
    """assert awards: Grand Prix $50,000 + credits, Gold $15,000... economic_value float máximo"""
    provider = RunwayProvider(organization_slug="runway")
    raw_list = provider.extract(_fixture_fetch_result())
    raw = raw_list[0]

    awards = raw.raw_data.get("awards", [])
    awards_text = raw.raw_data.get("awards_text", "")
    economic_value = raw.raw_data.get("economic_value")

    assert awards, "Awards no debe estar vacío"
    assert awards_text, "Awards text no debe estar vacío"
    assert any(a["place"] == "Grand Prix" for a in awards), f"Debe existir Grand Prix en premios, got {awards}"
    assert "50,000" in awards_text or "50000" in awards_text, f"Awards debe contener $50,000, got {awards_text}"
    assert "15,000" in awards_text or "15000" in awards_text, f"Awards debe contener $15,000, got {awards_text}"

    assert economic_value is not None, "Economic value no debe ser None"
    assert isinstance(economic_value, float), \
        f"Economic value debe ser float (evita updates falsos 50000.0 vs 50000), got {type(economic_value)} {economic_value}"
    assert economic_value == 50000.0, f"Economic value debe ser el máximo cash prize 50000.0, got {economic_value}"
    assert raw.raw_data.get("currency") == "USD", f"Currency debe ser USD, got {raw.raw_data.get('currency')}"

    print(f"✓ extract awards: {len(awards)} premios, value={economic_value} (float OK)")


def test_normalize():
    """Test normalize con fixture: tipos correctos + deadline ISO 8601 UTC"""
    provider = RunwayProvider(organization_slug="runway")
    raw = provider.extract(_fixture_fetch_result())[0]
    norm = provider.normalize(raw)

    assert norm.title, "Normalized title no debe estar vacío"
    assert "AIF" in norm.title or "Film Festival" in norm.title
    assert norm.official_link, "Official link no debe estar vacío"
    assert norm.organization_slug == "runway"
    assert norm.organizer_name == "Runway"
    assert norm.category == "IA / Cine"
    assert norm.opportunity_type == "festival"
    assert norm.currency == "USD"

    # Deadline normalizada: 'April 27th at 4:59 PM ET' edición 2026 -> 2026-04-27T20:59:00+00:00 (EDT=UTC-4)
    assert norm.deadline is not None, "Normalized deadline no debe ser None"
    assert "2026-04-27" in norm.deadline, f"Deadline debe ser 2026-04-27, got {norm.deadline}"
    assert "20:59" in norm.deadline, f"Deadline debe ser 20:59 UTC (16:59 EDT), got {norm.deadline}"
    assert "+00:00" in norm.deadline or norm.deadline.endswith("Z"), f"Deadline debe estar en UTC ISO 8601, got {norm.deadline}"

    # Economic value debe ser float (fix evita updates falsos)
    assert isinstance(norm.economic_value, float), f"economic_value debe ser float, got {type(norm.economic_value)}"
    assert norm.economic_value == 50000.0

    # Validación del contrato base debe pasar
    assert provider.validate(norm), f"Normalized opportunity debe ser válida, got {norm}"

    print(f"✓ normalize: title={norm.title}, deadline={norm.deadline}, value={norm.economic_value} float OK, valid OK")


def test_candidate_urls():
    """Diseño Ticket 011: candidate_urls() soporta aiff.runwayml.com y runwayml.com/ai-film-festival"""
    provider = RunwayProvider(organization_slug="runway")

    candidates = provider.candidate_urls("https://runwayml.com/ai-film-festival")
    assert isinstance(candidates, list)
    assert "https://aiff.runwayml.com/" in candidates, "Debe incluir https://aiff.runwayml.com/"
    assert "https://runwayml.com/ai-film-festival" in candidates, "Debe incluir https://runwayml.com/ai-film-festival"
    assert len(candidates) == len(set(candidates)), "No debe haber duplicados"

    # Desde aiff también aparece la alternativa runwayml.com
    candidates2 = provider.candidate_urls("https://aiff.runwayml.com/")
    assert "https://runwayml.com/ai-film-festival" in candidates2
    assert "https://aiff.runwayml.com/" in candidates2

    # Base Provider sigue intacta: default [url]
    from core.provider import Provider
    base_candidates = Provider.candidate_urls(provider, "https://example.com/")
    assert base_candidates == ["https://example.com/"], "Base Provider candidate_urls debe retornar [url] por defecto"

    print(f"✓ candidate_urls: {candidates} (genérico, sin tocar base)")


def test_fetch_fallback_httpx_when_playwright_fails(monkeypatch):
    """
    Fallback graceful (diseño Ticket 011): si Playwright falla (no instalado,
    browser crash, timeout), fetch_single captura aislado y cae a httpx SIN
    propagar excepción ni depender de internet (httpx mockeado con fixture).
    """
    provider = RunwayProvider(organization_slug="runway")
    fixture_content = FIXTURE_PATH.read_text(encoding="utf-8")

    # Simular fallo de Playwright
    def _playwright_boom(url):
        raise RuntimeError("playwright chromium not available (simulado)")

    monkeypatch.setattr(provider, "_fetch_with_playwright", _playwright_boom)

    # Simular httpx offline devolviendo el fixture
    class _FakeResp:
        status_code = 200
        text = fixture_content

    monkeypatch.setattr("httpx.get", lambda *args, **kwargs: _FakeResp())

    result = provider.fetch_single("https://aiff.runwayml.com/")
    assert result.success, f"Fallback httpx debe tener éxito, got error: {result.error}"
    assert result.content == fixture_content, "Contenido debe ser el fixture vía httpx"
    assert result.status_code == 200
    assert result.metadata.get("fetch_strategy") == "httpx_fallback", \
        f"Debe marcar estrategia httpx_fallback, got {result.metadata}"

    # El pipeline completo sigue funcionando sobre el fallback
    raw_list = provider.extract(result)
    assert len(raw_list) == 1, "Extract sobre fallback httpx debe funcionar"
    norm = provider.normalize(raw_list[0])
    assert provider.validate(norm)
    assert norm.economic_value == 50000.0

    print("✓ fallback: Playwright falla -> httpx OK (sin internet), pipeline extract+normalize OK")


def test_economic_value_always_float():
    """economic_value siempre float en raw y normalizado (evita updates falsos en History)"""
    provider = RunwayProvider(organization_slug="runway")
    raw_list = provider.extract(_fixture_fetch_result())

    for raw in raw_list:
        ev = raw.raw_data.get("economic_value")
        if ev is not None:
            assert isinstance(ev, float), f"economic_value en raw_data debe ser float, got {type(ev)} {ev}"
        for award in raw.raw_data.get("awards", []):
            assert isinstance(award["amount"], float), f"award amount debe ser float, got {type(award['amount'])}"

        norm = provider.normalize(raw)
        if norm.economic_value is not None:
            assert isinstance(norm.economic_value, float), \
                f"economic_value normalizado debe ser float, got {type(norm.economic_value)} {norm.economic_value}"

    # History tracker: 50000.0 vs 50000 NO es cambio; 50000 vs 51000 SÍ
    from core.history import HistoryTracker
    tracker = HistoryTracker()
    assert len(tracker.detect_changes({"economic_value": 50000.0}, {"economic_value": 50000})) == 0, \
        "50000.0 vs 50000 no debe ser considerado cambio (mismo valor numérico)"
    assert len(tracker.detect_changes({"economic_value": 50000.0}, {"economic_value": 51000.0})) == 1, \
        "50000.0 vs 51000.0 debe ser cambio real"

    print("✓ economic_value normalization: siempre float, sin updates falsos en History")


def test_plugin_loader_integration():
    """Integración: PluginLoader instancia Runway dinámicamente (sin imports manuales, aislado)"""
    from core.plugin_loader import get_plugin_loader

    loader = get_plugin_loader()
    instance, error = loader.create_provider_instance("runway", "runway")
    assert error is None, f"Provider runway debe instanciarse sin error, got {error}"
    assert instance is not None, "Instancia de RunwayProvider no debe ser None"
    # El loader carga plugin.py con importlib (módulo distinto al import directo del test),
    # por lo que se verifica identidad estructural, no identidad de objeto de clase.
    assert type(instance).__name__ == "RunwayProvider", f"Debe ser RunwayProvider, got {type(instance)}"
    assert instance.provider_type == "playwright", f"provider_type debe ser playwright, got {instance.provider_type}"
    assert callable(getattr(instance, "fetch", None)), "Debe implementar fetch()"
    assert callable(getattr(instance, "extract", None)), "Debe implementar extract()"
    assert callable(getattr(instance, "normalize", None)), "Debe implementar normalize()"

    # Pipeline offline con fixture a través de la instancia del loader
    raw_list = instance.extract(_fixture_fetch_result())
    assert len(raw_list) == 1
    norm = instance.normalize(raw_list[0])
    assert instance.validate(norm)

    print(f"✓ plugin loader integration: runway instanciado dinámicamente y pipeline OK ({type(instance).__name__})")


def run_all():
    print("\n=== Runway Scraper Fixture Tests (Ticket 011) ===\n")
    test_fixture_exists()
    test_extract_title()
    test_extract_description()
    test_extract_deadline()
    test_extract_awards_and_economic_value()
    test_normalize()
    test_candidate_urls()
    test_economic_value_always_float()
    test_plugin_loader_integration()
    print("\n=== Todos los tests fixture pasaron ✓ ===\n")
    print("Robustez scraper Runway:")
    print("  ✓ fixture HTML guardado tests/plugins/runway/runway_2026.html (captura real aiff.runwayml.com)")
    print("  ✓ extract title, description, deadline, awards, economic_value con asserts")
    print("  ✓ deadline normalizada a ISO 8601 UTC (April 27th 4:59 PM ET -> 2026-04-27T20:59:00+00:00)")
    print("  ✓ normalize con validación de contrato base")
    print("  ✓ fetch Playwright primario + fallback graceful httpx (test con mocks, sin internet)")
    print("  ✓ candidate_urls() genérico sin tocar Provider base")
    print("  ✓ economic_value siempre float evita updates falsos 50000.0 vs 50000")
    print("  ✓ Protege contra cambio HTML, cambio parser, refactor, regresión del fallback")


if __name__ == "__main__":
    run_all()
