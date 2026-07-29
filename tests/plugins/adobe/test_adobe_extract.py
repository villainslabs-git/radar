import pytest
from plugins.adobe.plugin import AdobeProvider
from core.provider import FetchResult, RawOpportunity, NormalizedOpportunity
from pathlib import Path

def _fixture_fetch_result():
    fixture_path = Path(__file__).parent / "Adobe.html"
    with open(fixture_path, "r", encoding="utf-8") as f:
        content = f.read()
    return FetchResult(
        success=True,
        content=content,
        content_type="html",
        status_code=200,
        url="https://www.adobe.com/creativecloud/buy/students.html",
        provider="beautifulsoup"
    )

def test_fixture_exists():
    fixture_path = Path(__file__).parent / "Adobe.html"
    assert fixture_path.exists()

def test_extract_returns_opportunities():
    provider = AdobeProvider(organization_slug="adobe")
    fr = _fixture_fetch_result()
    raw_list = provider.extract(fr)
    assert len(raw_list) > 0
    assert "Adobe Certified Professional" in raw_list[0].title

def test_normalize():
    provider = AdobeProvider(organization_slug="adobe")
    fr = _fixture_fetch_result()
    raw = provider.extract(fr)[0]
    normalized = provider.normalize(raw)
    assert normalized.title == raw.title
    assert normalized.organizer_name == "Adobe"
    assert normalized.official_link == "https://adobe.etciberoamerica.com/"
