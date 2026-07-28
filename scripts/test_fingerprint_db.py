#!/usr/bin/env python3
"""
Test deduplicación con DB real - Ticket 003
Verifica is_duplicate con RadarDB
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.fingerprint import FingerprintEngine
from core.db import get_db
import tempfile

engine = FingerprintEngine()

# Usar DB real
db = get_db()

print("=== Test Fingerprint con DB Real ===\n")

# Insertar oportunidades de prueba con fingerprint
from core.db import get_db
import sqlite3

# Limpiar oportunidades de prueba anteriores
with db.connect() as conn:
    conn.execute("DELETE FROM opportunities WHERE title LIKE '%Runway AI Film Festival%' OR title LIKE '%Posterheroes%' OR title LIKE '%Poster Heroes%' OR title LIKE '%AI Challenge%' OR title LIKE '%Adobe Creative Residency%'")
    conn.commit()
print("Cleanup previo OK")

# Oportunidad 1: Runway Festival
opp1 = {
    "title": "Runway AI Film Festival 2026",
    "official_link": "https://runwayml.com/ai-film-festival",
    "organization_slug": "runway",
    "deadline": "2026-09-15",
    "opportunity_type": "festival",
    "country": "USA"
}
fp1 = engine.generate(opp1)
print(f"Opp1 fingerprint: {fp1.hash} - {fp1.normalized_title}")

# Insertar opp1 manualmente en DB para probar duplicación
with db.connect() as conn:
    # Buscar org id runway
    cur = conn.execute("SELECT id FROM organizations WHERE slug='runway'")
    row = cur.fetchone()
    org_id = row["id"] if row else 1
    # Buscar source id
    cur = conn.execute("SELECT id FROM sources WHERE organization_id=? LIMIT 1", (org_id,))
    src_row = cur.fetchone()
    src_id = src_row["id"] if src_row else 1
    
    conn.execute("""
        INSERT INTO opportunities (organization_id, source_id, fingerprint_hash, title, organizer_name, official_link, deadline, category, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (org_id, src_id, fp1.hash, opp1["title"], "Runway", opp1["official_link"], "2026-09-15", "AI", "open"))
    conn.commit()
    print(f"Insertado opp1 en DB con hash {fp1.hash}")

# Oportunidad 2: Misma con tracking URL diferente - debería detectar duplicado exacto
opp2 = {
    "title": "Runway AI Film Festival 2026",
    "official_link": "https://runwayml.com/ai-film-festival?utm_source=newsletter",
    "organization_slug": "runway",
    "deadline": "2026-09-15",
    "opportunity_type": "festival",
    "country": "USA"  # mismo país que opp1 para hash exacto
}
fp2 = engine.generate(opp2)
print(f"\nOpp2 fingerprint (con tracking): {fp2.hash}")
print(f"Normalized URL opp2: {fp2.normalized_url}")
print(f"Opp1 normalized_url: {fp1.normalized_url}")
assert fp1.normalized_url == fp2.normalized_url, "URLs normalizadas deberían ser iguales"
assert fp1.hash == fp2.hash, f"Debería ser hash idéntico tras normalizar tracking, got {fp1.hash} vs {fp2.hash}"
print("✓ Hash idéntico tras normalizar tracking params")

# Probar is_duplicate contra DB
dup = engine.is_duplicate(fp2, db)
assert dup is not None and dup.is_duplicate
assert dup.level == "exact"
print(f"✓ is_duplicate DB detectó duplicado exacto: level={dup.level}, similarity={dup.similarity}")

# Oportunidad 3: Posterheroes vs Poster Heroes - approximate
opp3 = {
    "title": "Posterheroes 2026",
    "official_link": "https://posterheroes.org/competition/",
    "organization_slug": "posterheroes",
    "deadline": "2026-09-30",
    "opportunity_type": "contest"
}
fp3 = engine.generate(opp3)

# Insertar opp3
with db.connect() as conn:
    cur = conn.execute("SELECT id FROM organizations WHERE slug='posterheroes'")
    row = cur.fetchone()
    org_id = row["id"] if row else 2
    cur = conn.execute("SELECT id FROM sources WHERE organization_id=? LIMIT 1", (org_id,))
    src_row = cur.fetchone()
    src_id = src_row["id"] if src_row else 2
    conn.execute("""
        INSERT OR IGNORE INTO opportunities (organization_id, source_id, fingerprint_hash, title, organizer_name, official_link, deadline, category, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (org_id, src_id, fp3.hash, opp3["title"], "Posterheroes", opp3["official_link"], "2026-09-30", "General", "open"))
    conn.commit()

opp4 = {
    "title": "Poster Heroes 2026",  # con espacio
    "official_link": "https://posterheroes.org/competition/",
    "organization_slug": "posterheroes",
    "deadline": "2026-09-30",
    "opportunity_type": "contest"
}
fp4 = engine.generate(opp4)
print(f"\nOpp3 hash: {fp3.hash} title: {fp3.normalized_title}")
print(f"Opp4 hash: {fp4.hash} title: {fp4.normalized_title}")
sim = engine.compare(fp3, fp4)
print(f"Similarity Posterheroes vs Poster Heroes: {sim}")
# Con normalización agresiva, hash debería ser igual
if fp3.hash == fp4.hash:
    print("✓ Hash exact match por normalización agresiva (ideal)")
else:
    assert sim >= engine.title_threshold, f"Similarity {sim} debería >= threshold {engine.title_threshold}"
    print(f"✓ Approximate match similarity {sim} >= threshold")

dup2 = engine.is_duplicate(fp4, db)
assert dup2 is not None and dup2.is_duplicate
print(f"✓ is_duplicate DB detectó duplicado approximate/exact: level={dup2.level}, sim={dup2.similarity}")

# Oportunidad 5: Claramente distinta - no debe ser duplicado
opp5 = {
    "title": "Adobe Creative Residency 2026",
    "official_link": "https://adobe.com/residency",
    "organization_slug": "adobe",
    "deadline": "2026-11-01",
    "opportunity_type": "residency"
}
fp5 = engine.generate(opp5)
dup3 = engine.is_duplicate(fp5, db)
assert dup3 is None, f"No debería ser duplicado, got {dup3}"
print(f"\n✓ Oportunidad distinta correctamente NO detectada como duplicado (Adobe Residency)")

# Cleanup
with db.connect() as conn:
    conn.execute("DELETE FROM opportunities WHERE title LIKE 'Runway AI Film Festival 2026' OR title LIKE 'Posterheroes 2026' OR title LIKE 'Poster Heroes 2026'")
    conn.commit()

print("\n=== Todos los tests DB pasaron ✓ ===")
print("Fingerprint Engine v1 listo para scrapers:")
print("  - Detección exacta por hash (URL normalizada, título agresivo, org, deadline)")
print("  - Detección aproximada por RapidFuzz (threshold configurable desde config.yaml)")
print("  - Independiente de scrapers y scoring")
print("  - API congelada: generate(), is_duplicate(), compare()")
