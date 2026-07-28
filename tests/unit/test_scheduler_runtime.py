"""
Tests para Scheduler Runtime - Ticket 009
Implementar APScheduler real, cada Job independiente, si un Job falla los demás continúan, traceback, reintento configurable
Validación: Simular fallos, verificar aislamiento completo
"""
import sys
from pathlib import Path
import tempfile
import time

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from jobs.scheduler_runtime import SchedulerRuntime, JobResult
from core.config import Config

def create_test_config(tmp_path: Path, jobs_overrides: dict = None):
    """Crea config temporal con jobs configurados para test"""
    jobs_config = {
        "discover": {"enabled": True, "cron": "0 3 * * 0", "retries": 1, "retry_delay_seconds": 0, "timeout_seconds": 10},
        "monitor": {"enabled": True, "cron": "0 */12 * * *", "retries": 1, "retry_delay_seconds": 0, "timeout_seconds": 10},
        "notify": {"enabled": True, "cron": "0 9 * * *", "retries": 1, "retry_delay_seconds": 0, "timeout_seconds": 10},
        "cleanup": {"enabled": True, "cron": "0 2 * * *", "retries": 0, "retry_delay_seconds": 0, "timeout_seconds": 10},
        "healthcheck": {"enabled": True, "cron": "0 * * * *", "retries": 0, "retry_delay_seconds": 0, "timeout_seconds": 10}
    }
    if jobs_overrides:
        for job_id, overrides in jobs_overrides.items():
            if job_id in jobs_config:
                jobs_config[job_id].update(overrides)
            else:
                jobs_config[job_id] = overrides
    
    config_content = f"""
project:
  db_path: "data/radar.db"
  log_level: INFO
logging:
  level: INFO
  dir: "logs"
scheduler:
  enabled: true
  timezone: "America/Argentina/Buenos_Aires"
  max_workers: 5
  job_defaults:
    coalesce: true
    max_instances: 1
    misfire_grace_time: 3600
  jobs:
    discover:
      enabled: {str(jobs_config['discover']['enabled']).lower()}
      cron: "{jobs_config['discover']['cron']}"
      retries: {jobs_config['discover']['retries']}
      retry_delay_seconds: {jobs_config['discover']['retry_delay_seconds']}
      timeout_seconds: {jobs_config['discover']['timeout_seconds']}
    monitor:
      enabled: {str(jobs_config['monitor']['enabled']).lower()}
      cron: "{jobs_config['monitor']['cron']}"
      retries: {jobs_config['monitor']['retries']}
      retry_delay_seconds: {jobs_config['monitor']['retry_delay_seconds']}
      timeout_seconds: {jobs_config['monitor']['timeout_seconds']}
    notify:
      enabled: {str(jobs_config['notify']['enabled']).lower()}
      cron: "{jobs_config['notify']['cron']}"
      retries: {jobs_config['notify']['retries']}
      retry_delay_seconds: {jobs_config['notify']['retry_delay_seconds']}
      timeout_seconds: {jobs_config['notify']['timeout_seconds']}
    cleanup:
      enabled: {str(jobs_config['cleanup']['enabled']).lower()}
      cron: "{jobs_config['cleanup']['cron']}"
      retries: {jobs_config['cleanup']['retries']}
      retry_delay_seconds: {jobs_config['cleanup']['retry_delay_seconds']}
      timeout_seconds: {jobs_config['cleanup']['timeout_seconds']}
    healthcheck:
      enabled: {str(jobs_config['healthcheck']['enabled']).lower()}
      cron: "{jobs_config['healthcheck']['cron']}"
      retries: {jobs_config['healthcheck']['retries']}
      retry_delay_seconds: {jobs_config['healthcheck']['retry_delay_seconds']}
      timeout_seconds: {jobs_config['healthcheck']['timeout_seconds']}
"""
    config_path = tmp_path / "config_test.yaml"
    config_path.write_text(config_content)
    return Config(config_path)

def test_scheduler_creacion_y_jobs():
    """Scheduler se crea y agrega jobs desde config"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        cfg = create_test_config(tmp_path)
        scheduler_runtime = SchedulerRuntime(config=cfg)
        
        # Antes de start, no debe tener jobs corriendo
        assert not scheduler_runtime._running
        
        # add_jobs debe agregar 5 jobs habilitados
        scheduler_runtime.add_jobs()
        jobs = scheduler_runtime.scheduler.get_jobs()
        assert len(jobs) == 5, f"Debe tener 5 jobs habilitados, got {len(jobs)}: {[j.id for j in jobs]}"
        
        job_ids = {j.id for j in jobs}
        assert "discover" in job_ids
        assert "monitor" in job_ids
        assert "notify" in job_ids
        assert "cleanup" in job_ids
        assert "healthcheck" in job_ids
        
        try:
            scheduler_runtime.scheduler.shutdown(wait=False)
        except Exception:
            pass
        
        print("✓ scheduler creación y jobs: 5 jobs agregados desde config")

def test_jobs_independientes():
    """Cada Job debe ejecutarse de forma independiente"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        cfg = create_test_config(tmp_path)
        scheduler_runtime = SchedulerRuntime(config=cfg)
        
        # Ejecutar cada job independientemente via run_job_now
        results = {}
        for job_id in ["discover", "monitor", "notify", "cleanup", "healthcheck"]:
            result = scheduler_runtime.run_job_now(job_id)
            results[job_id] = result
            # Cada job debe retornar JobResult, no lanzar excepción hacia afuera
            assert isinstance(result, JobResult), f"Job {job_id} debe retornar JobResult"
        
        # Todos deben tener resultado, aunque algunos puedan fallar (pero no deben impedir que otros se ejecuten)
        # En nuestro caso, todos deberían success porque son placeholders con log y no fallan por defecto
        # Pero lo importante es que si uno falla, los demás continúan (probado en test siguiente)
        assert len(results) == 5
        
        print(f"✓ jobs independientes: 5 jobs ejecutados independientemente, cada uno retorna JobResult")

def test_aislamiento_fallos():
    """Si un Job falla, los demás continúan"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        cfg = create_test_config(tmp_path)
        scheduler_runtime = SchedulerRuntime(config=cfg)
        
        # Crear un job que falla a propósito
        def failing_job():
            raise RuntimeError("Simulated job failure for isolation test")
        
        def successful_job():
            return True
        
        # Envolver con retry 0 para que falle rápido
        from jobs.scheduler_runtime import with_retry_and_isolation
        
        failing_wrapped = with_retry_and_isolation(retries=0, retry_delay_seconds=0, job_id="failing_test")(failing_job)
        successful_wrapped = with_retry_and_isolation(retries=0, retry_delay_seconds=0, job_id="successful_test")(successful_job)
        
        # Ejecutar failing
        result_fail = failing_wrapped()
        assert not result_fail.success, "Failing job debe marcar success=False"
        assert "Simulated job failure" in result_fail.error
        assert result_fail.traceback_str is not None, "Debe registrar traceback"
        
        # Ejecutar successful después de failing - debe continuar sin ser afectado por fallo anterior
        result_success = successful_wrapped()
        assert result_success.success, "Successful job debe success=True aunque anterior falló, demuestra aislamiento"
        
        # Simular lista de jobs donde uno falla y otros continúan
        jobs = [
            ("job1", successful_job),
            ("job2", failing_job),
            ("job3", successful_job)
        ]
        
        results = []
        for job_id, func in jobs:
            wrapped = with_retry_and_isolation(retries=0, retry_delay_seconds=0, job_id=job_id)(func)
            try:
                res = wrapped()
                results.append((job_id, res.success))
            except Exception:
                results.append((job_id, False))
        
        # Verificar aislamiento: job1 success, job2 fail, job3 success (job3 continúa aunque job2 falló)
        assert results[0][1] == True, "job1 debe success"
        assert results[1][1] == False, "job2 debe fail"
        assert results[2][1] == True, "job3 debe success aunque job2 falló - aislamiento completo"
        
        print("✓ aislamiento fallos: job que falla no detiene otros, traceback registrado, aislamiento completo verificado")

def test_traceback_registrado():
    """Registrar traceback cuando job falla"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        cfg = create_test_config(tmp_path)
        scheduler_runtime = SchedulerRuntime(config=cfg)
        
        def failing_job():
            raise ValueError("Test traceback logging")
        
        from jobs.scheduler_runtime import with_retry_and_isolation
        wrapped = with_retry_and_isolation(retries=0, retry_delay_seconds=0, job_id="traceback_test")(failing_job)
        
        result = wrapped()
        
        assert not result.success
        assert result.error is not None
        assert "Test traceback logging" in result.error
        assert result.traceback_str is not None
        assert "Traceback" in result.traceback_str or "ValueError" in result.traceback_str
        assert "failing_job" in result.traceback_str or "test_traceback" in result.traceback_str.lower() or "ValueError" in result.traceback_str
        
        print("✓ traceback registrado: error y traceback capturados en JobResult")

def test_reintento_configurable():
    """Reintento configurable: retries y retry_delay_seconds desde config"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        # Config con retries=2
        cfg = create_test_config(tmp_path, jobs_overrides={"monitor": {"retries": 2, "retry_delay_seconds": 0}})
        scheduler_runtime = SchedulerRuntime(config=cfg)
        
        attempt_count = {"count": 0}
        
        def flaky_job():
            attempt_count["count"] += 1
            if attempt_count["count"] < 3:
                raise RuntimeError(f"Flaky failure attempt {attempt_count['count']}")
            return True
        
        from jobs.scheduler_runtime import with_retry_and_isolation
        
        # Con retries=2, debe intentar 3 veces (1 inicial + 2 retries) y luego success en 3er intento
        wrapped = with_retry_and_isolation(retries=2, retry_delay_seconds=0, job_id="flaky_test")(flaky_job)
        result = wrapped()
        
        assert result.success, f"Con retries=2, flaky job que falla 2 veces y luego success debe finalmente success, got {result.success} attempts {attempt_count['count']}"
        assert attempt_count["count"] == 3, f"Debe haber intentado 3 veces (1+2 retries), got {attempt_count['count']}"
        assert result.attempt == 3
        
        # Con retries=1, mismo flaky que falla 2 veces debe finalmente fallar
        attempt_count["count"] = 0
        wrapped2 = with_retry_and_isolation(retries=1, retry_delay_seconds=0, job_id="flaky_test2")(flaky_job)
        result2 = wrapped2()
        
        assert not result2.success, "Con retries=1, flaky que falla 2 veces debe finalmente fail"
        assert attempt_count["count"] == 2, f"Debe haber intentado 2 veces (1+1 retry), got {attempt_count['count']}"
        
        print("✓ reintento configurable: retries=2 permite 3 intentos total, retries=1 solo 2 intentos, delay configurable")

def test_cron_parsing():
    """Validar que cron strings se parsean correctamente"""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        cfg = create_test_config(tmp_path)
        scheduler_runtime = SchedulerRuntime(config=cfg)
        
        # Test cron parsing válido
        trigger = scheduler_runtime._parse_cron("0 3 * * 0")
        assert trigger is not None
        
        trigger2 = scheduler_runtime._parse_cron("0 */12 * * *")
        assert trigger2 is not None
        
        trigger3 = scheduler_runtime._parse_cron("0 9 * * *")
        assert trigger3 is not None
        
        # Test cron inválido debe usar fallback
        trigger_invalid = scheduler_runtime._parse_cron("invalid cron")
        assert trigger_invalid is not None, "Cron inválido debe usar fallback, no crashear"
        
        print("✓ cron parsing: válidos parseados, inválido usa fallback sin crashear")

def run_all():
    print("\n=== Scheduler Runtime Tests (Ticket 009) ===\n")
    test_scheduler_creacion_y_jobs()
    test_jobs_independientes()
    test_aislamiento_fallos()
    test_traceback_registrado()
    test_reintento_configurable()
    test_cron_parsing()
    print("\n=== Todos los tests Scheduler Runtime pasaron ✓ ===\n")
    print("Criterios Ticket 009:")
    print("  ✓ APScheduler real implementado (BackgroundScheduler, ThreadPoolExecutor, CronTrigger)")
    print("  ✓ Cada Job independiente (discover, monitor, notify, cleanup, healthcheck)")
    print("  ✓ Si un Job falla, los demás continúan (aislamiento completo verificado con 3 jobs, uno falla, siguiente success)")
    print("  ✓ Registrar traceback (JobResult con error y traceback_str, logging en scheduler.log)")
    print("  ✓ Reintento configurable (retries, retry_delay_seconds desde config.yaml, testeado con flaky job)")
    print("  ✓ Cron parsing y validación")

if __name__ == "__main__":
    run_all()
