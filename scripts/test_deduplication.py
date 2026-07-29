from core.monitoring_engine import MonitoringEngine
from core.db import RadarDB
from core.plugin_loader import get_plugin_loader
from core.config import get_config
import unittest.mock as mock
from core.provider import FetchResult
from pathlib import Path

def test_cross_source_deduplication():
    db = RadarDB()
    # Limpiar DB
    with db.connect() as conn:
        conn.execute("DELETE FROM opportunities")
        conn.execute("DELETE FROM opportunity_history")

    engine = MonitoringEngine()
    loader = get_plugin_loader()
    
    # Fixture Runway
    runway_fixture = Path("tests/plugins/runway/runway_2026.html").read_text()
    # Fixture Its Nice That (agregador apuntando a Runway)
    itsnicethat_html = """
    <html><body><article>
    <h2>AI Film Festival 2026</h2>
    <p>Check out this festival by Runway.</p>
    <a href="https://aiff.runwayml.com/">Official Site</a>
    </article></body></html>
    """

    # Mock fetch para ambos
    with mock.patch("plugins.runway.plugin.RunwayProvider.fetch") as mock_runway_fetch, \
         mock.patch("plugins.itsnicethat.plugin.ItsNiceThatProvider.fetch") as mock_int_fetch:
        
        mock_runway_fetch.return_value = FetchResult(
            success=True, content=runway_fixture, content_type="html", 
            url="https://aiff.runwayml.com/", provider="playwright"
        )
        mock_int_fetch.return_value = FetchResult(
            success=True, content=itsnicethat_html, content_type="html",
            url="https://www.itsnicethat.com/news", provider="beautifulsoup"
        )

        # Ejecutar monitor para Runway
        print("Monitoring Runway...")
        engine.monitor_source({
            "slug": "runway", "organization_slug": "runway", 
            "url": "https://aiff.runwayml.com/", "priority": 10
        })

        # Ejecutar monitor para Its Nice That
        print("Monitoring It's Nice That...")
        engine.monitor_source({
            "slug": "itsnicethat", "organization_slug": "itsnicethat",
            "url": "https://www.itsnicethat.com/news", "priority": 10
        })

    # Verificar DB
    with db.connect() as conn:
        opps = conn.execute("SELECT * FROM opportunities").fetchall()
        print(f"Total opportunities in DB: {len(opps)}")
        for op in opps:
            print(f"Title: {op['title']}, Links: {op['alternate_links_json']}")
        
        assert len(opps) == 1, "Should have only 1 opportunity due to deduplication"
        # It's Nice That links to same URL, so it should be deduplicated
        # Actually ItsNiceThatProvider extract returns title 'AI Film Festival 2026'
        # Runway extract returns 'AIF 2026 | AI Festival'
        # Let's see if Fingerprint catches it.

if __name__ == "__main__":
    try:
        test_cross_source_deduplication()
        print("DEDUPLICATION TEST: OK")
    except Exception as e:
        print(f"DEDUPLICATION TEST: FAILED - {e}")
        import traceback
        traceback.print_exc()
