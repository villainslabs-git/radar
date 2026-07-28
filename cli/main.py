"""
Radar CLI - Entry point headless first
Comandos: python -m radar doctor, monitor, discover, digest, stats, plugins, schedule

Ticket 004: Plugin Loader real integración
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

app = typer.Typer(
    name="radar",
    help="Radar - Opportunity Intelligence Engine (Headless First)",
    add_completion=False
)
console = Console()

@app.command()
def doctor(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose logging")
):
    """Diagnostica todo el sistema. Comando sugerido por senior review para ahorrar tiempo."""
    from core.doctor import run_doctor
    ok = run_doctor(verbose=verbose)
    if not ok:
        raise typer.Exit(code=1)

@app.command(name="init-db")
def init_db_cmd(
    force: bool = typer.Option(False, "--force", "-f", help="Force recreate even if exists")
):
    """Crea/recrea DB desde schema + seeds (organizaciones y fuentes)"""
    from scripts.init_db import main as init_main
    console.print("[bold cyan]Inicializando DB reproducible...[/]")
    init_main()
    console.print("[green]DB inicializada OK[/]")

@app.command()
def stats():
    """Muestra estadísticas rápidas de DB + plugins (usa Plugin Loader real)"""
    from core.db import get_db
    from core.config import get_config
    from core.plugin_loader import get_plugin_loader
    
    cfg = get_config()
    db = get_db()
    validation = db.validate_integrity()
    
    table = Table(title=f"Radar Stats - {cfg.get('project.name')}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="magenta")
    
    table.add_row("DB Path", str(cfg.get_db_path()))
    for t, count in validation.get("counts", {}).items():
        table.add_row(f"Rows:{t}", str(count))
    
    loader = get_plugin_loader()
    report = loader.get_status_report()
    table.add_row("Plugins Discovered", str(report["total_discovered"]))
    table.add_row("Plugins Enabled", str(report["total_enabled"]))
    table.add_row("Plugins Loadable", str(report["total_loadable"]))
    table.add_row("Scoring", "DISABLED (collecting 300 opps first)" if not cfg.get("scoring.enabled") else "ENABLED")
    
    console.print(table)
    
    # Segunda tabla plugins usando Loader real
    p_table = Table(title="Plugins detalle (Plugin Loader real - respeta enable por YML)")
    p_table.add_column("Slug", style="cyan")
    p_table.add_column("Enabled", style="green")
    p_table.add_column("Status", style="yellow")
    p_table.add_column("Schedule", style="yellow")
    p_table.add_column("Types", style="magenta")
    p_table.add_column("Provider", style="white")
    p_table.add_column("Priority", style="white")
    
    for p in report["plugins"]:
        p_table.add_row(
            p.slug,
            "✓" if p.enabled else "✗",
            p.status,
            p.schedule,
            ",".join(p.manifest.opportunity_types),
            p.manifest.provider_type,
            str(p.priority)
        )
    console.print(p_table)

@app.command()
def plugins(
    enabled_only: bool = typer.Option(False, "--enabled", "-e", help="Solo plugins enabled por YML")
):
    """Lista plugins descubiertos dinámicamente desde filesystem (sin lista manual en core)"""
    from core.plugin_loader import get_plugin_loader
    loader = get_plugin_loader()
    
    if enabled_only:
        plugins_list = loader.get_enabled_plugins()
        title = "Plugins Enabled (respeta config.yaml)"
    else:
        plugins_list = loader.get_all_plugins()
        title = "All Plugins Discovered (dynamic registry desde filesystem)"
    
    table = Table(title=title)
    table.add_column("Slug", style="cyan")
    table.add_column("Name", style="white")
    table.add_column("Enabled", style="green")
    table.add_column("Status", style="yellow")
    table.add_column("Schedule", style="yellow")
    table.add_column("Priority", style="white")
    table.add_column("Has Code", style="magenta")
    table.add_column("Manifest Valid", style="green")
    table.add_column("Provider", style="white")
    table.add_column("Types", style="magenta")
    
    for p in plugins_list:
        table.add_row(
            p.slug,
            p.manifest.name,
            "✓" if p.enabled else "✗",
            p.status,
            p.schedule,
            str(p.priority),
            "✓" if p.has_code else "✗",
            "✓" if p.manifest.valid else "✗",
            p.manifest.provider_type,
            ",".join(p.manifest.opportunity_types)
        )
    
    console.print(table)
    
    report = loader.get_status_report()
    if report["total_invalid_manifest"] > 0:
        console.print(f"[red]WARN: {report['total_invalid_manifest']} manifests inválidos:[/]")
        for inv in report["invalid"]:
            console.print(f"  - {inv.slug}: {inv.manifest.errors}")
    
    if report["total_missing_code"] > 0:
        console.print(f"[yellow]WARN: {report['total_missing_code']} plugins enabled sin código:[/]")
        for mc in report["missing_code"]:
            console.print(f"  - {mc.slug}: enabled pero plugin.py falta en {mc.folder}")
    
    if report["total_load_failed"] > 0:
        console.print(f"[red]FAIL: {report['total_load_failed']} plugins con error de carga (aislados, no rompen core):[/]")
        for lf in report["load_failed"]:
            console.print(f"  - {lf.slug}: {lf.error}")

@app.command()
def schedule():
    """Muestra schedule de jobs respetando enable por YML (integración loader + scheduler)"""
    from jobs.scheduler import get_scheduler
    scheduler = get_scheduler()
    scheduler.print_schedule()
    
    # Validación adicional
    issues = scheduler.validate_schedules()
    if issues:
        console.print("[yellow]Schedule issues detectadas:[/]")
        for iss in issues:
            console.print(f"  [{iss['level']}] {iss['slug']}: {iss['issue']}")
    else:
        console.print("[green]Schedule OK - todos los jobs enabled tienen manifest válido y código[/]")

@app.command()
def digest():
    """CLI Summary - Hay 3 nuevas, 1 cambió deadline... (Headless MVP)"""
    from core.db import get_db
    db = get_db()
    try:
        with db.connect() as conn:
            cur = conn.execute("SELECT COUNT(*) as c FROM opportunities")
            total = cur.fetchone()["c"]
            cur = conn.execute("SELECT COUNT(*) as c FROM sources WHERE status='active'")
            active_sources = cur.fetchone()["c"]
            cur = conn.execute("SELECT name, slug FROM organizations ORDER BY name LIMIT 10")
            orgs = cur.fetchall()
        
        console.print(Panel(f"[bold]Radar Digest[/]\nTotal oportunidades: {total}\nFuentes activas: {active_sources}\nFase: Recolección inicial (objetivo 300 antes de scoring)", title="Radar Headless"))
        console.print("Organizaciones seed:")
        for o in orgs:
            console.print(f"  - {o['name']} ({o['slug']})")
        
        if total == 0:
            console.print("\n[yellow]No hay oportunidades aún. Ejecuta scrapers (Ticket 010+) para recolectar.[/]")
            console.print("[dim]Estado: Núcleo reproducible OK, Fingerprint Engine v1 OK, Plugin Loader real OK - listo para recolectar.[/]")
    
    except Exception as e:
        console.print(f"[red]Error en digest: {e}[/]")
        raise typer.Exit(code=1)

@app.command()
def monitor(
    batch_size: int = typer.Option(None, "--batch-size", "-b", help="Batch size de sources"),
    all_sources: bool = typer.Option(False, "--all", help="Incluir sources inactivas")
):
    """Job Monitoring - El Vigilante: ejecuta providers -> fingerprint -> DB -> logs"""
    from jobs.monitoring import run_monitoring
    console.print(f"[bold cyan]Iniciando Monitoring Engine (batch_size={batch_size})...[/]")
    console.print("[dim]Flujo: Provider -> Normalize -> Fingerprint -> Database -> Logs[/]")
    console.print("[dim]No scoring todavía, solo deduplicación + history tracker + métricas[/]")
    
    try:
        metrics = run_monitoring(batch_size=batch_size, only_active=not all_sources)
        
        # Tabla resumen
        table = Table(title="Monitoring Results - Metrics")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="magenta")
        table.add_row("Sources", str(metrics.total_sources))
        table.add_row("Fetched", str(metrics.total_fetched))
        table.add_row("New (inserted)", str(metrics.total_new))
        table.add_row("Duplicate exact", str(metrics.total_duplicate_exact))
        table.add_row("Duplicate approximate", str(metrics.total_duplicate_approximate))
        table.add_row("Updated (changes)", str(metrics.total_updated))
        table.add_row("History entries", str(metrics.total_history_entries))
        table.add_row("Alternate links", str(metrics.total_alternate_links))
        table.add_row("Errors", str(metrics.total_errors))
        table.add_row("Duration", f"{metrics.duration_seconds:.2f}s")
        
        console.print(table)
        
        # Tabla por source si hay pocos
        if len(metrics.sources) <= 10:
            src_table = Table(title="Per Source")
            src_table.add_column("Org", style="cyan")
            src_table.add_column("URL", style="white")
            src_table.add_column("New", style="green")
            src_table.add_column("Dup", style="yellow")
            src_table.add_column("Upd", style="magenta")
            src_table.add_column("Err", style="red")
            
            for src in metrics.sources:
                src_table.add_row(
                    src.org_slug,
                    src.source_url[:30],
                    str(src.new),
                    str(src.duplicate_exact + src.duplicate_approximate),
                    str(src.updated),
                    str(src.errors)
                )
            console.print(src_table)
        
        if metrics.total_errors > 0:
            console.print(f"[yellow]WARN: {metrics.total_errors} errors, ver logs/monitor.log[/]")
        else:
            console.print("[green]Monitoring OK - sin errores[/]")
    
    except Exception as e:
        console.print(f"[red]Monitoring failed: {e}[/]")
        raise typer.Exit(code=1)

@app.command()
def discover():
    """Placeholder Job Discovery - Implementación completa en Ticket 014"""
    console.print("[yellow]Job Discovery aún no implementado (Ticket 014)[/]")
    console.print("Semanal, busca nuevas orgs y fuentes desde seeds")

@app.command()
def version():
    """Versión"""
    from core import __version__
    from core.config import get_config
    cfg = get_config()
    console.print(f"Radar v{__version__} - {cfg.get('project.name')}")
    from core.plugin_loader import get_plugin_loader
    loader = get_plugin_loader()
    report = loader.get_status_report()
    console.print(f"Plugins: {report['total_discovered']} discovered, {report['total_enabled']} enabled, {report['total_loadable']} loadable - Loader real v1")

if __name__ == "__main__":
    app()
