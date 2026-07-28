# Guía Rápida de Implementación v3.0

Este doc te dice cómo pasar del papel al código en 1 día.

## 0. Crear estructura

```bash
mkdir -p data/raw config core jobs cli scrapers/selectors prompt_templates
cp config.yaml config/config.yaml
sqlite3 data/radar_v3.db < schema.sql
```

## 1. Core: Fingerprint (core/fingerprint.py)

```python
import re, hashlib
from unidecode import unidecode # pip install unidecode
from datetime import datetime

def normalize_title(t: str) -> str:
    t = unidecode(t.lower())
    t = re.sub(r'\b(2026|2027|2025|festival|edition|edicion|convocatoria|open call)\b','',t)
    t = re.sub(r'[^a-z0-9]', '', t)
    return t[:60]

def bucket_deadline(d: datetime | None) -> str:
    if not d: return "no_deadline"
    return f"{d.year}-{d.month:02d}-{d.day//15}"

def bucket_prize(v: float|None, txt: str) -> str:
    txt = (txt or "").lower()
    if not v:
        if any(k in txt for k in ["exposure","screening","exhibition"]): return "prestige"
        return "unknown"
    if v >= 10000: return "10k+"
    if v >= 2000: return "2k-10k"
    if v >= 500: return "500-2k"
    return "0-500"

def generate_fingerprint(org_id: int, title: str, deadline: datetime|None, prize_val, prize_txt) -> str:
    parts = [str(org_id), normalize_title(title), bucket_deadline(deadline), bucket_prize(prize_val, prize_txt)]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
```

## 2. Core: History Tracker (core/history.py)

```python
def track_changes(db, opportunity_id, old: dict, new: dict, source_id: int):
    changes = []
    fields_to_track = ["deadline","awards_text","economic_value","status","title","official_link"]
    for f in fields_to_track:
        if str(old.get(f)) != str(new.get(f)):
            ctype = "info_updated"
            if f=="deadline":
                ctype = "deadline_extended" if new[f] > old[f] else "deadline_shortened"
            elif f in ("awards_text","economic_value"):
                ctype = "prize_updated"
            elif f=="status":
                ctype="status_changed"
            db.execute("INSERT INTO opportunity_history (opportunity_id, field_name, old_value, new_value, change_type, source_id) VALUES (?,?,?,?,?,?)",
                       (opportunity_id, f, str(old.get(f)), str(new.get(f)), ctype, source_id))
            changes.append((f, ctype))
            # Generar notificación si es crítico
            if ctype in ("deadline_extended","deadline_shortened") and db.in_watchlist(opportunity_id):
                db.create_notification(
                    opportunity_id=opportunity_id,
                    type="deadline_changed",
                    title=f"Deadline cambiado: {new['title']}",
                    message=f"Antes: {old.get(f)} -> Ahora: {new.get(f)}",
                    priority="urgent"
                )
    return changes
```

## 3. Jobs: Monitoring Separation Example (jobs/monitoring.py)

```python
# Pseudo-código aislado
import yaml
from core.db import get_db
from scrapers import get_scraper_for_source

config = yaml.safe_load(open("config/config.yaml"))

def run_monitoring():
    db = get_db(config["project"]["db_path"])
    sources = db.execute("""
        SELECT * FROM sources 
        WHERE status='active' 
        ORDER BY priority DESC, last_scraped_at ASC NULLS FIRST 
        LIMIT ?
    """, (config["scan"]["monitoring"]["batch_size"],)).fetchall()

    for src in sources:
        scraper = get_scraper_for_source(src) # elige playwright si src.type en use_playwright_for
        raw = scraper.fetch(src["url"])
        opps = scraper.extract_opportunities(raw) # lista de dicts
        
        for opp_dict in opps:
            opp_dict["organization_id"] = src["organization_id"]
            opp_dict["source_id"] = src["id"]
            fingerprint = generate_fingerprint(...)
            existing = db.find_by_fingerprint(src["organization_id"], fingerprint)
            if existing:
                # merge alternate links, update last_seen
                db.add_alternate_link(existing["id"], opp_dict["official_link"])
            else:
                # check possible duplicate por similitud
                # si no, crear nueva + history created + scoring + notification new_opportunity
                new_id = db.insert_opportunity(opp_dict, fingerprint)
```

## 4. CLI Digest - MVP Sin UI (cli/__main__.py)

```python
# python -m cli digest
def show_digest():
    db = get_db()
    stats = db.query_stats_last_24h()
    print(f"""[DIGEST 24H]
Hay {stats['new']} convocatorias nuevas:
""")
    for opp in db.get_top_ranked(5):
        print(f"  [{opp['final_score']:.2f}] {opp['org_name']} - {opp['title']} - {opp['days_left']} días")
    
    changing = db.get_recent_deadline_changes()
    if changing:
        print(f"\n{len(changing)} modificó su deadline (URGENTE si está en tu watchlist):")
        for c in changing:
            print(f"  ! {c['title']} -> {c['new_value']} (antes {c['old_value']})")
```

## 5. Orden recomendado de implementación (1 semana)

Día 1: schema.sql + config.yaml loader + db.py + organizations seed
Día 2: jobs/monitoring.py solo con 2 sources fijas (Runway oficial, Posterheroes) + scraping hardcoded
Día 3: fingerprint + history tracker + scoring simple
Día 4: notifications + watchlist + CLI digest
Día 5: jobs/discovery.py separado (solo print de "encontré 5 posibles nuevas orgs")
Día 6: APScheduler que orquesta los 3 jobs según config.yaml
Día 7: Test end-to-end: "Hay 3 nuevas, 1 cambió deadline, 2 cerraron"

Listo. Con eso ya tenés el Radar v3.0 funcionando headless.
