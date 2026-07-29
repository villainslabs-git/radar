import unittest.mock as mock
from pathlib import Path
import json
from core.monitoring_engine import MonitoringEngine
from core.db import RadarDB
from core.provider import FetchResult

def simulate_massive_recollection():
    db = RadarDB()
    with db.connect() as conn:
        conn.execute("DELETE FROM opportunities")
        conn.execute("DELETE FROM opportunity_history")

    engine = MonitoringEngine()
    
    runway_html = Path("tests/plugins/runway/runway_2026.html").read_text()
    
    def mock_fetch(url):
        return FetchResult(success=True, content=runway_html, content_type="html", url=url, provider="playwright")

    print("Starting Simulation...")
    with mock.patch("core.provider.Provider.fetch", side_effect=mock_fetch):
        metrics = engine.monitor_all(batch_size=15)
        
    print(f"\nTotal New: {metrics.total_new}")

if __name__ == "__main__":
    simulate_massive_recollection()