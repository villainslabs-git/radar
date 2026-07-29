from core.db import RadarDB
from core.logger import get_logger
import json

logger = get_logger("validate")

def validate_recollection():
    db = RadarDB()
    print("=== VALIDACIÓN TICKET 013 - RECOLECCIÓN REAL ===")
    
    with db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
        print(f"Oportunidades totales en DB: {count}")
        
        orgs = conn.execute("SELECT org.name, COUNT(o.id) as total FROM organizations org LEFT JOIN opportunities o ON org.id = o.organization_id GROUP BY org.name").fetchall()
        print("\nDistribución por Organización:")
        for org in orgs:
            print(f"- {org['name']}: {org['total']}")
            
        history = conn.execute("SELECT COUNT(*) FROM opportunity_history").fetchone()[0]
        print(f"\nEntradas en historial: {history}")
        
        notifs = conn.execute("SELECT COUNT(*) FROM notifications WHERE is_read=0").fetchone()[0]
        print(f"Notificaciones pendientes: {notifs}")

    if count > 0:
        print("\nRESULTADO: ÉXITO - El sistema ha recolectado datos reales.")
    else:
        print("\nRESULTADO: PENDIENTE - No se encontraron oportunidades.")

if __name__ == "__main__":
    validate_recollection()