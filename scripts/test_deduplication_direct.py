from core.monitoring_engine import MonitoringEngine
from core.db import RadarDB
from core.fingerprint import FingerprintEngine
from core.provider import RawOpportunity, NormalizedOpportunity
import json

def test_fingerprint_deduplication_direct():
    db = RadarDB()
    engine = MonitoringEngine()
    fp_engine = FingerprintEngine()
    
    with db.connect() as conn:
        conn.execute("DELETE FROM opportunities")
        conn.execute("DELETE FROM opportunity_history")

    # 1. Simular Runway Original
    raw1 = RawOpportunity(
        title="AIF 2026 | AI Festival",
        url="https://aiff.runwayml.com/",
        provider="runway",
        organization_slug="runway",
        raw_data={"deadline_text": "April 27th at 4:59 PM ET"}
    )
    # En el plugin real Runway, normalize devuelve title="AIF 2026 | AI Festival"
    norm1 = NormalizedOpportunity(
        title=raw1.title, organizer_name="Runway", organization_slug="runway",
        official_link=raw1.url, source_url=raw1.url, provider="runway",
        deadline="2026-04-27T16:59:00"
    )

    # 2. Simular It's Nice That (Agregador) - RESOLVIENDO la organización real
    raw2 = RawOpportunity(
        title="AIF 2026 AI Festival", # Título muy similar
        url="https://aiff.runwayml.com/", # MISMA URL oficial
        provider="itsnicethat",
        organization_slug="runway", # El agregador identifica que es de Runway
        raw_data={}
    )
    norm2 = NormalizedOpportunity(
        title=raw2.title, organizer_name="Runway", organization_slug="runway",
        official_link=raw2.url, source_url="https://www.itsnicethat.com/news", 
        provider="itsnicethat",
        deadline=None 
    )

    # Procesar primera
    print("Processing Runway...")
    # source dict mínimo para process_opportunity
    source1 = {"id": 1, "url": "https://aiff.runwayml.com/", "org_slug": "runway"}
    engine.process_opportunity(norm1, source1)
    
    # Procesar segunda (debería ser duplicado por URL o por similitud aproximada)
    print("Processing It's Nice That...")
    # Pasamos org_slug=None para que el engine use el slug de la oportunidad (comportamiento de agregador)
    source2 = {"id": 6, "url": "https://www.itsnicethat.com/news", "org_slug": None}
    engine.process_opportunity(norm2, source2)

    with db.connect() as conn:
        opps = conn.execute("SELECT * FROM opportunities").fetchall()
        print(f"Total opportunities in DB: {len(opps)}")
        for op in opps:
            print(f"ID: {op['id']}, Title: {op['title']}, Org: {op['organization_id']}")
            print(f"Links: {op['alternate_links_json']}")
        
        assert len(opps) == 1, "Deduplication failed: Expected 1, found more."
        # El título debería haberse actualizado al del agregador (o mantenerse el original dependiendo de detect_changes)
        # En este caso MonitoringEngine actualizó el título.
        assert opps[0]['title'] == "AIF 2026 AI Festival"

if __name__ == "__main__":
    test_fingerprint_deduplication_direct()
    print("DEDUPLICATION TEST OK")
