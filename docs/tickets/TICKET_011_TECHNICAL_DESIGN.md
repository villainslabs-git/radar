# Ticket 011 — Technical Design Proposal: Runway Provider (Playwright + Graceful Fallback)

**Proyecto:** Radar — Opportunity Intelligence Engine  
**Ticket:** 011  
**Target Provider:** Runway (AI Film Festival, Grants, Beta Programs)  
**Branch:** `arena/019fac46-radar`  
**Workspace:** `/home/user/radar`  

---

## 1. Arquitectura Actual de RADAR v3.0

### Estructura del Proyecto
- **`core/`**: Motor agnóstico y cerrado. Contiene base de datos (`db.py`), motor de huellas digitales (`fingerprint.py`), seguimiento de historial (`history.py`, `opportunity_history.py`), notificaciones (`notification_engine.py`), motor de monitoreo (`monitoring_engine.py`), cargador dinámico de plugins (`plugin_loader.py`), clase abstracta `Provider` (`provider.py`), configuración (`config.py`), logger (`logger.py`) y diagnóstico (`doctor.py`).
- **`plugins/`**: Conectores específicos por organización (`posterheroes`, `runway`, `adobe`, `ai-film-festival`, `itsnicethat`, etc.), cada uno con su `manifest.yaml` y `plugin.py`.
- **`jobs/`**: Programador y ejecución de tareas asíncronas (`scheduler_runtime.py`, `monitoring.py`).
- **`tests/`**: Tests unitarios y fixtures HTML reales (`tests/plugins/runway/runway_2026.html`, `tests/plugins/posterheroes/posterheroes_2026.html`, etc.).

### Responsabilidades de Componentes Clave
- **`plugins/base.py`**: Re-exporta la clase abstracta `Provider` del core para facilitar la importación limpia dentro de cada plugin.
- **`plugins/registry.py`**: Módulo de compatibilidad/registro (aunque el discovery real y dinámico se gestiona mediante `core/plugin_loader.py`).
- **Plugins Existentes**: Ej. Posterheroes (`plugins/posterheroes/plugin.py`) validado exitosamente en el Ticket 010, sirviendo como referencia canónica para parsers basados en `BeautifulSoup` con fallback de URLs candidatas y normalización estricta.
- **Sistema de Tests**: Basado en `pytest`, utilizando fixtures locales fuera de línea para garantizar pruebas deterministas y sin dependencia de internet.

---

## 2. Estado Actual del Patrón de Plugins

- **Registro:** El `PluginLoader` (`core/plugin_loader.py`) realiza un escaneo dinámico del directorio `plugins/` en tiempo de ejecución. No requiere listas manuales ni modificaciones en el core. Valida el `manifest.yaml` y carga el módulo `plugin.py` usando `importlib` (con análisis AST para prohibir imports estáticos desde el core como `from plugins.xxx import ...`).
- **Interfaz Requerida:** Todo plugin debe heredar de `Provider` (definido en `core/provider.py`) e implementar:
  - `provider_type` (propiedad: `"playwright"`, `"httpx"`, etc.)
  - `candidate_urls()` (método opcional/heredado que retorna lista de URLs a intentar)
  - `fetch(url)` (ejecuta la obtención HTTP o Playwright retornando un `FetchResult`)
  - `extract(fetch_result)` (analiza el contenido y retorna una lista de `RawOpportunity`)
  - `normalize(raw_opportunity)` (convierte un `RawOpportunity` en un `NormalizedOpportunity`)
- **Datos Devueltos:** `NormalizedOpportunity` con campos estandarizados (título, enlace oficial, fechas normalizadas, valores económicos en formato `float`, etc.).
- **Separación de Responsabilidades:** El core gestiona la orquestación atómica, deduplicación (`fingerprint`), persistencia (`db`), historial y notificaciones. El plugin es estrictamente responsable de la adquisición (*fetch*), extracción (*extract*) y normalización (*normalize*) de los datos propios de su organización.

---

## 3. Análisis Específicamente de Runway

### Archivos Existentes
- `plugins/runway/manifest.yaml`: Define metadata (`name: "Runway"`, `slug: "runway"`, `provider_type: "playwright"`, `requires_js: true`, prioridad 10, y fuentes oficiales).
- `plugins/runway/plugin.py`: Actualmente es un skeleton básico con un fetch síncrono mediante `httpx` y extracción vacía.
- `tests/plugins/runway/runway_2026.html`: Fixture HTML real capturado (136 KB) de `https://aiff.runwayml.com/` correspondiente al AI Film Festival 2026 de Runway.

### Qué Falta para Convertirlo en un Provider Funcional
1. **Implementar `candidate_urls()`:** Retornar las URLs clave de Runway (ej. `https://aiff.runwayml.com/`, `https://runwayml.com/ai-film-festival`).
2. **Implementar Patrón Playwright con Graceful Fallback a Httpx:**
   - Intentar la obtención mediante Playwright (`playwright` + `chromium`) para renderizar JavaScript si la página lo requiere.
   - Si Playwright falla (no instalado, browser crash, timeout, falta de dependencias), capturar la excepción y delegar automáticamente a `httpx` + `BeautifulSoup`, registrando el motivo en los logs y continuando el pipeline sin detenerse.
3. **Implementar Extracción con BeautifulSoup (`extract()`):**
   - Parsear el fixture HTML `runway_2026.html` (y páginas reales).
   - Extraer la información clave del AI Film Festival 2026:
     - Título: *AIF 2026 | AI Festival* (o convocatorias específicas).
     - Deadline: Extraer fecha de cierre (ej. *April 27th at 4:59 PM ET* -> normalizar a fecha/hora UTC).
     - Premios / Awards: Extraer estructura de premios (Grand Prix $50,000 + 1,000,000 Runway credits, Gold $15,000, etc.) y calcular/normalizar el valor económico máximo (`economic_value = 50000.0`).
     - Descripción y enlaces.
4. **Implementar Normalización (`normalize()`):**
   - Mapear el `RawOpportunity` extraído a `NormalizedOpportunity` asegurando tipos correctos (ej. `economic_value` como `float`, fechas normalizadas).
5. **Crear Test Unitario Offline (`tests/plugins/runway/test_runway_extract.py`):**
   - Testear el proveedor usando exclusivamente el fixture local `runway_2026.html` sin llamadas a internet.

### Riesgos Identificados
- **Renderizado SPA / Next.js:** Runway utiliza Next.js (SSR/Client rendering). El fixture HTML contiene datos embebidos en el DOM estático renderizado, pero dependencias dinámicas podrían requerir Playwright. La regla de Playwright con fallback a `httpx` mitiga cualquier bloqueo.
- **Cambios de Estructura HTML:** Mitigado mediante selectores robustos en BeautifulSoup y tests offline con fixtures estables.

---

## 4. Ticket 011 — Technical Design Proposal

### Objetivo
Hacer que el plugin **Runway** sea un conector real, robusto y totalmente funcional dentro de RADAR, extrayendo oportunidades reales (como el Runway AI Film Festival 2026) desde su sitio web utilizando Playwright con fallback automático a `httpx` + `BeautifulSoup`, validado mediante tests offline con el fixture `runway_2026.html`.

### Flujo de Datos Esperado
```
Sitio Web Runway (aiff.runwayml.com)
  ↓
RunwayPlugin (Playwright → si falla → httpx)
  ↓
extract() (BeautifulSoup parseando HTML / fixture)
  ↓
normalize() (NormalizedOpportunity con fechas y economic_value float)
  ↓
RADAR Core (MonitoringEngine → Fingerprint → History → Database → Notification → Logs → Metrics)
```

### Cambios Necesarios
- **Archivos Modificados:**
  - `plugins/runway/plugin.py`: Implementación completa de `candidate_urls`, `fetch` con fallback Playwright -> `httpx`, `extract` con `BeautifulSoup` sobre el fixture/HTML, y `normalize`.
- **Archivos Nuevos:**
  - `tests/plugins/runway/test_runway_extract.py`: Suite de tests unitarios offline para validar extracción, normalización, manejo de fallback y robustez del parser de Runway.
- **Archivos que NO deben tocarse:**
  - Todo el directorio `core/` (el núcleo está cerrado y agnóstico).
  - Configuración global (excepto habilitar/verificar que Runway esté enabled en `config.yaml` si procede, aunque ya está habilitado por defecto).
  - Otros plugins (`posterheroes`, `adobe`, etc.).

### Contrato del Plugin (`RunwayProvider`)
- **Métodos Requeridos:**
  - `provider_type -> str` (retorna `"playwright"` o `"httpx"` según el medio exitoso).
  - `candidate_urls() -> List[str]` (URLs oficiales de Runway AIF).
  - `fetch(url: str) -> FetchResult` (intenta Playwright; ante cualquier excepción o fallo, ejecuta `httpx.get` con User-Agent Radar/3.0, registrando advertencia y retornando `FetchResult`).
  - `extract(fetch_result: FetchResult) -> List[RawOpportunity]` (parsea el HTML con `BeautifulSoup`, extrae título, deadline, premios, economic value, descripción).
  - `normalize(raw: RawOpportunity) -> NormalizedOpportunity` (normaliza tipos de datos y metadatos).
- **Manejo de Errores:** Excepciones de red, timeouts de Playwright o ausencia de elementos HTML son capturadas de forma aislada, retornando `FetchResult(success=False)` o listas vacías de oportunidades, sin propagar excepciones al core.

### Estrategia de Testing
- **Fixtures:** Uso del archivo existente `tests/plugins/runway/runway_2026.html` (136 KB).
- **Tests Unitarios (`test_runway_extract.py`):**
  1. Test de carga offline del fixture HTML.
  2. Test de extracción correcta de título, deadline (*April 27th...*), y premios económicos (Grand Prix $50,000 -> `50000.0`).
  3. Test de normalización a `NormalizedOpportunity`.
  4. Test de fallback graceful (simulando fallo de Playwright y verificando éxito vía `httpx` con el fixture).
  5. Test de integración con el `PluginLoader` runtime (verificando que Runway se instancia correctamente y pasa el doctor).

### Riesgos Técnicos y Mitigaciones
- *Playwright no disponible en entorno de pruebas:* Mitigado por el diseño de fallback automático a `httpx` y tests offline basados en fixtures estáticos.
- *Formato de fechas variable:* Mitigado mediante expresiones regulares robustas y parseadores de fechas tolerantes.

### Plan de Implementación por Fases
- **Fase 1:** Diseño técnico (este documento).
- **Fase 2:** Implementación del parser y fetch con fallback en `plugins/runway/plugin.py`.
- **Fase 3:** Creación de los tests unitarios offline en `tests/plugins/runway/test_runway_extract.py`.
- **Fase 4:** Ejecución de pruebas (`pytest`), validación con `python -m radar doctor` y `python -m radar plugins`.
- **Fase 5:** Commit, push a `arena/019fac46-radar`, verificación en GitHub y cierre del ticket con reporte.

---

## 5. Criterios de Aceptación del Ticket 011

1. **Implementación Completa:** `plugins/runway/plugin.py` funcional con extracción real basada en BeautifulSoup y patrón Playwright con fallback a `httpx`.
2. **Cero Modificaciones al Core:** Ningún archivo en `core/` es modificado.
3. **Tests OK:** La suite de tests unitarios de Runway (`test_runway_extract.py`) pasa exitosamente en modo offline.
4. **Validación Doctor:** `python -m radar doctor` reporta estado OK.
5. **Respaldo en GitHub:** Commit y push realizados exitosamente a la rama `arena/019fac46-radar`.
