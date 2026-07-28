#!/usr/bin/env python3
"""
Ticket 002: Núcleo reproducible del sistema
init_db.py - Creación automática de DB + carga orgs y fuentes + validación integridad
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
import yaml
from core.logger import get_logger
from core.config import get_config
from core.db import get_db

logger = get_logger("db")

SCHEMA_PATH = Path("data/schema.sql")
ORGS_YAML = Path("data/seed/organizations.yaml")
SOURCES_YAML = Path("data/seed/sources.yaml")

def recreate_db(db_path: Path, schema_path: Path):
    if db_path.exists():
        backup = db_path.with_suffix(f".backup_{db_path.stat().st_mtime:.0f}.db")
        logger.info(f"DB exists, backing up to {backup}")
        db_path.rename(backup)
    
    sql = schema_path.read_text(encoding="utf-8")
    conn = sqlite3.connect(db_path)
    conn.executescript(sql)
    conn.commit()
    conn.close()
    logger.info(f"DB recreated from {schema_path} -> {db_path}")

def load_organizations(db, orgs_yaml: Path):
    data = yaml.safe_load(orgs_yaml.read_text()) if orgs_yaml.exists() else {"organizations": []}
    count = 0
    for org in data.get("organizations", []):
        try:
            db.insert_organization(
                name=org["name"],
                slug=org["slug"],
                website=org.get("website",""),
                type=org.get("type","company"),
                country=org.get("country","")
            )
            count += 1
        except Exception as e:
            logger.warning(f"Failed to insert org {org.get('slug')}: {e}")
    logger.info(f"Loaded {count} organizations from {orgs_yaml}")
    return count

def load_sources(db, sources_yaml: Path):
    if not sources_yaml.exists():
        logger.warning(f"Sources yaml not found: {sources_yaml}")
        return 0
    
    data = yaml.safe_load(sources_yaml.read_text())
    orgs = {o["slug"]: o for o in [dict(r) for r in db.get_organizations()]}  # need mapping id
    # We need id mapping
    with db.connect() as conn:
        cur = conn.execute("SELECT id, slug FROM organizations")
        slug_to_id = {r["slug"]: r["id"] for r in cur.fetchall()}
    
    count = 0
    for src in data.get("sources", []):
        org_slug = src["org_slug"]
        org_id = slug_to_id.get(org_slug)
        if not org_id:
            logger.warning(f"Org slug {org_slug} not found for source {src['url']}")
            continue
        try:
            db.insert_source(
                org_id=org_id,
                url=src["url"],
                name=src["name"],
                type=src.get("type","official_page"),
                status=src.get("status","active"),
                priority=src.get("priority",5),
                discovery_method=f"seed_yaml:{org_slug}"
            )
            count += 1
        except Exception as e:
            logger.warning(f"Failed to insert source {src['url']}: {e}")
    logger.info(f"Loaded {count} sources from {sources_yaml}")
    return count

def main():
    cfg = get_config()
    db_path = cfg.get_db_path()
    db = get_db(db_path)
    
    logger.info(f"[INIT_DB] Starting with config {cfg.path}")
    logger.info(f"DB path: {db_path}")
    
    recreate_db(db_path, SCHEMA_PATH)
    
    # Reload db object after recreation
    db = get_db(db_path)
    
    orgs_loaded = load_organizations(db, ORGS_YAML)
    sources_loaded = load_sources(db, SOURCES_YAML)
    
    # Validate
    report = db.validate_integrity()
    logger.info(f"[INIT_DB] Validation: tables={report['tables']} counts={report['counts']} fk={report['fk_check']}")
    if report["issues"]:
        logger.error(f"[INIT_DB] Issues found: {report['issues']}")
        for issue in report["issues"]:
            print(f"ISSUE: {issue}")
        sys.exit(1)
    else:
        print(f"\n[INIT_DB] OK")
        print(f"  DB: {db_path}")
        print(f"  Organizations: {orgs_loaded}")
        print(f"  Sources: {sources_loaded}")
        print(f"  Tables: {', '.join([k for k,v in report['tables'].items() if v])}")
        print(f"  FK check: {report['fk_check']}")
        logger.info("[INIT_DB] Completed successfully")

if __name__ == "__main__":
    main()
