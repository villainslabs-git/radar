import yaml
from pathlib import Path
from core.db import RadarDB

def refresh_seeds():
    db = RadarDB()
    sources_file = Path("data/seed/sources.yaml")
    print("\n--- Refreshing Sources ---")
    if sources_file.exists():
        with open(sources_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            for src in data.get("sources", []):
                org = db.find_organization_by_slug(src["org_slug"])
                if org:
                    new_id = db.insert_source(
                        org_id=org["id"],
                        url=src["url"],
                        name=src["name"],
                        type=src.get("type", "official_page"),
                        status=src.get("status", "active"),
                        priority=src.get("priority", 5),
                        discovery_method="seed_refresh"
                    )
                    print(f"Source: {src['url']} (ID: {new_id})")

if __name__ == "__main__":
    refresh_seeds()