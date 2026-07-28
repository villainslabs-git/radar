# Arquitectura del Agente Local de Monitoreo de Convocatorias

## 1. Resumen Ejecutivo

El presente documento detalla la arquitectura de un agente local mínimo diseñado para monitorear convocatorias dirigidas a creadores argentinos en los campos de la Inteligencia Artificial, cine, motion graphics, video, publicidad y arte digital. El objetivo principal es proporcionar un sistema autónomo, de bajo costo y fácil mantenimiento, que descubra, valide, deduplique y siga oportunidades relevantes, utilizando tecnologías preferidas como Python, SQLite, Playwright y BeautifulSoup. La solución prioriza la simplicidad y la modularidad, evitando la sobreingeniería y la dependencia de servicios externos para su funcionamiento central.

## 2. Visión General de la Arquitectura

La arquitectura propuesta se basa en un diseño modular que desacopla las responsabilidades clave del agente. Consiste en los siguientes componentes principales:

*   **Módulo de Orquestación (Scheduler/Controller):** Responsable de la programación y coordinación de las tareas del agente, como el descubrimiento de fuentes, el scraping y la validación. Actúa como el cerebro del sistema, asegurando que las operaciones se ejecuten de forma regular y eficiente.
*   **Módulo de Descubrimiento de Fuentes (Source Discovery):** Identifica nuevas fuentes de convocatorias (sitios web, PDFs) y las añade a la base de datos para su posterior monitoreo. Utiliza técnicas de rastreo limitado para expandir la cobertura sin depender de una lista fija.
*   **Módulo de Scraping (Scraper):** Extrae la información de las convocatorias de las fuentes identificadas. Emplea Playwright para la interacción con páginas dinámicas y BeautifulSoup para el parseo de contenido HTML/XML.
*   **Módulo de Procesamiento y Validación (Processor/Validator):** Se encarga de limpiar, normalizar, validar y deduplicar las convocatorias obtenidas. Asegura que solo las oportunidades vigentes y relevantes se almacenen en la base de datos.
*   **Base de Datos Local (SQLite):** Almacena todas las convocatorias descubiertas, su estado, historial de cambios y las fuentes de origen. SQLite se elige por su simplicidad, portabilidad y bajo requisito de recursos, ideal para una solución local.
*   **Módulo de Interfaz (Frontend Agnostic Interface):** Proporciona un punto de acceso para interactuar con el agente. Aunque el frontend es agnóstico en esta fase, este módulo define la API interna o los mecanismos para que una extensión de Chrome, una web local o una futura aplicación interactúen con el core del agente.
*   **Módulo de IA Bajo Demanda (On-Demand AI Module):** Un componente opcional que se activa solo cuando es necesario (por ejemplo, para resumir bases o interpretar cláusulas legales de una convocatoria específica). No forma parte del ciclo de ejecución regular del agente, sino que se invoca explícitamente.

Esta estructura garantiza que cada componente tenga una responsabilidad clara, facilitando el desarrollo, las pruebas y el mantenimiento. La comunicación entre módulos se realizará principalmente a través de la base de datos o llamadas a funciones internas, manteniendo la simplicidad del sistema local.


## 3. Diagrama de Componentes

Debido a un problema técnico con la herramienta de renderizado de diagramas, a continuación se presenta una descripción textual del diagrama de componentes. El diagrama visualizaría las interacciones entre los módulos descritos en la sección anterior.

```mermaid
graph TD
    subgraph Agente Local de Monitoreo
        A[Módulo de Orquestación (Scheduler)]
        B[Módulo de Descubrimiento de Fuentes]
        C[Módulo de Scraping (Playwright/BeautifulSoup)]
        D[Módulo de Procesamiento y Validación]
        E[Base de Datos Local (SQLite)]
        F[Módulo de Interfaz (Frontend Agnostic)]
        G[Módulo de IA Bajo Demanda]

        A --> B(Programa descubrimiento)
        A --> C(Programa scraping)
        A --> D(Programa validación)

        B --> E(Almacena nuevas fuentes)
        C --> E(Almacena datos crudos)
        D --> E(Actualiza convocatorias validadas)

        E --> C(Provee fuentes a scrapear)
        E --> D(Provee datos a validar)
        E --> F(Provee datos a mostrar)

        F <--> G(Solicita análisis de IA)
        F <--> E(Consulta/Actualiza datos)
    end
```

**Descripción de las interacciones:**

*   El **Módulo de Orquestación (Scheduler)** inicia y coordina las operaciones de los módulos de Descubrimiento de Fuentes, Scraping y Procesamiento/Validación.
*   El **Módulo de Descubrimiento de Fuentes** identifica nuevas fuentes y las registra en la **Base de Datos Local (SQLite)**.
*   El **Módulo de Scraping** utiliza las fuentes de la Base de Datos para extraer información y almacenar los datos crudos en la misma Base de Datos.
*   El **Módulo de Procesamiento y Validación** toma los datos crudos de la Base de Datos, los limpia, valida y actualiza el estado de las convocatorias en la Base de Datos.
*   La **Base de Datos Local (SQLite)** es el repositorio central de todas las fuentes y convocatorias, sirviendo como fuente de verdad para todos los módulos.
*   El **Módulo de Interfaz (Frontend Agnostic)** interactúa con la Base de Datos para mostrar la información y con el **Módulo de IA Bajo Demanda** para solicitudes específicas de análisis.
*   El **Módulo de IA Bajo Demanda** se activa únicamente a petición del Módulo de Interfaz para tareas como resumir textos o interpretar cláusulas legales.


## 4. Flujo de Ejecución

El agente operará mediante un ciclo de ejecución programado, idealmente una o dos veces al día, para minimizar el consumo de recursos y asegurar la frescura de los datos. El flujo principal se describe a continuación:

1.  **Inicio de Ejecución (Scheduler):** El Módulo de Orquestación (Scheduler) inicia el ciclo de monitoreo según la programación establecida.
2.  **Descubrimiento y Actualización de Fuentes:**
    *   El Módulo de Descubrimiento de Fuentes consulta la Base de Datos Local para obtener la lista actual de fuentes a monitorear.
    *   Realiza un rastreo limitado en estas fuentes y en sitios relacionados para identificar nuevas URLs o documentos (PDFs) que puedan contener convocatorias.
    *   Las nuevas fuentes descubiertas se añaden a la Base de Datos Local, marcadas para su posterior scraping.
3.  **Scraping de Convocatorias:**
    *   El Módulo de Scraping obtiene de la Base de Datos las fuentes pendientes de scraping o aquellas que requieren una actualización.
    *   Para cada fuente, utiliza Playwright para interactuar con páginas dinámicas o BeautifulSoup para parsear contenido estático.
    *   Extrae el contenido relevante de las convocatorias (título, fechas, enlaces, etc.) en un formato crudo.
    *   Almacena estos datos crudos en la Base de Datos Local, asociados a su fuente original.
4.  **Procesamiento y Validación:**
    *   El Módulo de Procesamiento y Validación recupera los datos crudos de convocatorias de la Base de Datos.
    *   Realiza las siguientes operaciones:
        *   **Limpieza y Normalización:** Estandariza formatos de fechas, texto, etc.
        *   **Validación:** Verifica la vigencia de la convocatoria (fechas de inicio/fin, estado).
        *   **Deduplicación:** Identifica y elimina convocatorias duplicadas basándose en criterios como el enlace oficial o una combinación de título y organizador.
        *   **Seguimiento de Cambios:** Compara la información actual con versiones anteriores almacenadas para detectar modificaciones (ej. cambios en deadlines, premios).
    *   Actualiza el estado y los detalles de las convocatorias en la Base de Datos Local, marcando las que están vigentes, próximas a abrir o cerradas.
5.  **Fin de Ejecución:** El ciclo se completa, y el agente espera la próxima ejecución programada.

## 5. Modelo de Datos (Esquema SQLite)

El modelo de datos se diseñará para ser simple y eficiente, utilizando SQLite para el almacenamiento local. Se proponen las siguientes tablas:

### Tabla: `sources`
Almacena información sobre las fuentes de donde se extraen las convocatorias.

| Campo         | Tipo      | Restricciones           | Descripción                                      |
| :------------ | :-------- | :---------------------- | :----------------------------------------------- |
| `id`          | INTEGER   | PRIMARY KEY AUTOINCREMENT | Identificador único de la fuente.                |
| `url`         | TEXT      | NOT NULL UNIQUE         | URL principal de la fuente.                      |
| `name`        | TEXT      |                         | Nombre descriptivo de la fuente.                 |
| `type`        | TEXT      |                         | Tipo de fuente (ej. 'website', 'pdf_list', 'rss'). |
| `last_scraped`| DATETIME  |                         | Fecha y hora de la última vez que se scrapeó.    |
| `status`      | TEXT      | DEFAULT 'active'        | Estado de la fuente ('active', 'inactive', 'error'). |
| `priority`    | INTEGER   | DEFAULT 1               | Prioridad de scraping (mayor número = mayor prioridad). |

### Tabla: `opportunities`
Almacena los detalles de cada convocatoria descubierta.

| Campo             | Tipo      | Restricciones           | Descripción                                      |
| :---------------- | :-------- | :---------------------- | :----------------------------------------------- |
| `id`              | INTEGER   | PRIMARY KEY AUTOINCREMENT | Identificador único de la oportunidad.           |
| `source_id`       | INTEGER   | NOT NULL                | Clave foránea a `sources.id`.                    |
| `title`           | TEXT      | NOT NULL                | Título de la convocatoria.                       |
| `organizer`       | TEXT      |                         | Entidad que organiza la convocatoria.            |
| `official_link`   | TEXT      | NOT NULL UNIQUE         | Enlace oficial a la convocatoria.                |
| `country`         | TEXT      |                         | País del organizador.                            |
| `accepts_argentinians`| BOOLEAN |                         | Indica si acepta participantes argentinos.       |
| `geo_restrictions`| TEXT      |                         | Descripción de restricciones geográficas.       |
| `open_date`       | DATETIME  |                         | Fecha de apertura de la convocatoria.            |
| `deadline`        | DATETIME  |                         | Fecha límite para la inscripción.                |
| `awards`          | TEXT      |                         | Descripción de los premios.                      |
| `currency`        | TEXT      |                         | Moneda de los premios económicos.                |
| `economic_awards` | REAL      |                         | Valor económico de los premios.                  |
| `category`        | TEXT      |                         | Categoría principal (ej. 'IA', 'Cine').          |
| `modality`        | TEXT      |                         | Modalidad (ej. 'online', 'presencial').          |
| `fee_type`        | TEXT      |                         | Tipo de inscripción ('gratuita', 'paga').        |
| `language`        | TEXT      |                         | Idioma de la convocatoria.                       |
| `format_requested`| TEXT      |                         | Formato de presentación solicitado.              |
| `ai_allowed`      | BOOLEAN   |                         | Indica si se permite el uso de IA.               |
| `ai_mandatory`    | BOOLEAN   |                         | Indica si el uso de IA es obligatorio.           |
| `requirements`    | TEXT      |                         | Requisitos principales.                          |
| `executive_summary`| TEXT      |                         | Resumen ejecutivo de la convocatoria.            |
| `status`          | TEXT      | NOT NULL                | Estado actual ('open', 'upcoming', 'closed').    |
| `created_at`      | DATETIME  | DEFAULT CURRENT_TIMESTAMP | Fecha de creación del registro.                  |
| `updated_at`      | DATETIME  | DEFAULT CURRENT_TIMESTAMP | Última fecha de actualización del registro.      |

### Tabla: `opportunity_tags`
Tabla de unión para la clasificación de oportunidades con múltiples etiquetas.

| Campo             | Tipo      | Restricciones           | Descripción                                      |
| :---------------- | :-------- | :---------------------- | :----------------------------------------------- |
| `opportunity_id`  | INTEGER   | NOT NULL                | Clave foránea a `opportunities.id`.              |
| `tag`             | TEXT      | NOT NULL                | Etiqueta asignada (ej. 'Generative AI', 'Video'). |
|                   |           | PRIMARY KEY (`opportunity_id`, `tag`) | Clave primaria compuesta.                        |

### Tabla: `opportunity_scores`
Almacena las puntuaciones calculadas para cada convocatoria.

| Campo             | Tipo      | Restricciones           | Descripción                                      |
| :---------------- | :-------- | :---------------------- | :----------------------------------------------- |
| `opportunity_id`  | INTEGER   | NOT NULL PRIMARY KEY    | Clave foránea a `opportunities.id`.              |
| `ease_of_participation_ar`| REAL |                         | Facilidad para participar desde Argentina (0-1). |
| `economic_value`  | REAL      |                         | Valor económico normalizado (0-1).               |
| `prestige`        | REAL      |                         | Prestigio de la convocatoria (0-1).              |
| `affinity_score`  | REAL      |                         | Afinidad con el perfil del usuario (0-1).        |
| `time_remaining`  | REAL      |                         | Tiempo restante hasta el deadline (en días).     |
| `estimated_difficulty`| REAL   |                         | Dificultad estimada (0-1).                       |
| `success_probability`| REAL    |                         | Probabilidad de éxito (0-1).                     |
| `calculated_at`   | DATETIME  | DEFAULT CURRENT_TIMESTAMP | Fecha de cálculo de las puntuaciones.            |

Este modelo de datos proporciona la estructura necesaria para almacenar y gestionar eficientemente la información de las convocatorias, permitiendo consultas y análisis posteriores.


## 6. Roadmap de Tareas Pequeñas

El desarrollo del agente se abordará de forma iterativa, siguiendo un roadmap que desglosa las fases del proyecto en tareas pequeñas y manejables. Este enfoque permite una implementación gradual, facilitando las pruebas y la validación en cada etapa.

### Fase 1: Diseño Técnico (Completada)

*   Definición de la arquitectura general del sistema.
*   Diseño del diagrama de componentes.
*   Especificación del flujo de ejecución.
*   Diseño del modelo de datos (esquema SQLite).
*   Elaboración del roadmap de implementación.

### Fase 2: Módulo de Descubrimiento y Scraping (Core)

*   **Tarea 2.1: Configuración del Entorno:**
    *   Configurar un entorno de desarrollo Python con Playwright, BeautifulSoup y SQLite.
    *   Crear la estructura de directorios del proyecto.
*   **Tarea 2.2: Implementación del Scheduler Básico:**
    *   Desarrollar un script Python para ejecutar tareas programadas (ej. usando `schedule` o `APScheduler` para un entorno local).
    *   Definir la frecuencia de ejecución (una o dos veces al día).
*   **Tarea 2.3: Implementación del Módulo de Descubrimiento de Fuentes:**
    *   Desarrollar funciones para leer fuentes iniciales (ej. desde un archivo de configuración).
    *   Implementar lógica para identificar nuevas URLs o PDFs a partir de enlaces en las fuentes existentes (rastreo limitado).
    *   Almacenar nuevas fuentes en la tabla `sources` de SQLite.
*   **Tarea 2.4: Implementación del Módulo de Scraping:**
    *   Desarrollar funciones para leer URLs de la tabla `sources`.
    *   Utilizar Playwright para cargar páginas web y extraer contenido dinámico.
    *   Utilizar BeautifulSoup para parsear HTML y extraer datos estructurados de convocatorias.
    *   Implementar extracción de texto de PDFs (ej. con `PyPDF2` o `pdfminer.six`).
    *   Almacenar datos crudos de convocatorias en la tabla `opportunities` (con `source_id` y `official_link`).

### Fase 3: Módulo de Procesamiento y Validación

*   **Tarea 3.1: Limpieza y Normalización de Datos:**
    *   Implementar funciones para estandarizar formatos de fechas, texto y otros campos.
    *   Manejar casos de borde y errores en los datos extraídos.
*   **Tarea 3.2: Validación de Vigencia:**
    *   Desarrollar lógica para verificar fechas de apertura y cierre de convocatorias.
    *   Actualizar el campo `status` en la tabla `opportunities` (`open`, `upcoming`, `closed`).
*   **Tarea 3.3: Deduplicación:**
    *   Implementar un algoritmo de deduplicación basado en `official_link` y/o una combinación de `title` y `organizer`.
    *   Marcar duplicados o fusionar información si es necesario.
*   **Tarea 3.4: Seguimiento de Cambios:**
    *   Implementar lógica para comparar nuevas extracciones con registros existentes.
    *   Registrar cambios significativos (ej. `deadline` modificado) en un campo de historial o log.

### Fase 4: Módulo de Clasificación y Ranking

*   **Tarea 4.1: Clasificación Automática (Etiquetado):**
    *   Desarrollar lógica para asignar etiquetas (`opportunity_tags`) basadas en palabras clave o patrones en el título/descripción.
    *   Implementar un sistema de reglas configurable para la asignación de categorías.
*   **Tarea 4.2: Cálculo de Ranking:**
    *   Implementar funciones para calcular las puntuaciones en la tabla `opportunity_scores`.
    *   Definir la lógica para cada métrica (facilidad de participación, valor económico, prestigio, etc.).
    *   Considerar la posibilidad de ponderar estas métricas.

### Fase 5: Módulo de Interfaz y IA Bajo Demanda

*   **Tarea 5.1: API Interna para Consulta:**
    *   Exponer una API REST local (ej. con Flask o FastAPI) o una interfaz de línea de comandos para consultar la base de datos.
    *   Permitir filtros por estado, categoría, palabras clave, etc.
*   **Tarea 5.2: Integración de IA Bajo Demanda:**
    *   Desarrollar un módulo que, bajo demanda, pueda enviar texto (bases, cláusulas) a un LLM (ej. OpenAI API, si se configura) para resumen o interpretación.
    *   Asegurar que esta funcionalidad sea explícitamente invocada y no parte del ciclo regular.
*   **Tarea 5.3: Prototipo de Frontend (Opcional en esta fase):**
    *   Crear un prototipo muy básico (ej. una página HTML local o un script de consola) para demostrar la consulta de datos.

### Fase 6: Notificaciones y Extensión (Futuro)

*   **Tarea 6.1: Sistema de Notificaciones:**
    *   Implementar un mecanismo para detectar nuevas convocatorias o cambios importantes.
    *   Desarrollar un sistema de notificación (ej. por email, push local, o integración con servicios de mensajería si se decide).
*   **Tarea 6.2: Extensión de Chrome (Diseño):**
    *   Diseñar la interfaz y funcionalidades clave de la extensión (consultar, guardar favoritos, marcar como presentada, etc.).
    *   Definir la comunicación entre la extensión y el agente local.

Este roadmap proporciona una guía clara para la implementación, permitiendo un desarrollo incremental y enfocado en las funcionalidades esenciales del agente local.
