"""
Radar - Provider Abstraction
Definido en Ticket 002 por review senior. Concepto desde día 0.

Provider es la interfaz que desacopla TODO el sistema de scraping.
Hoy puede ser Playwright/BeautifulSoup, mañana RSS, API, JSON, GitHub, Google Alerts, MCP.

Arquitectura:
Provider (abstract)
  ↓
  fetch()    -> trae raw (html, json, rss, api response)
  extract()  -> convierte raw en lista de dicts semi-estructurados
  normalize()-> convierte cada dict a formato canónico de opportunity
  validate() -> valida que la oportunidad tenga mínimos

Beneficio: Cada plugin implementa esta interfaz. El Job Monitoring no sabe si viene de HTML o API.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from pathlib import Path
import time

@dataclass
class FetchResult:
    """Resultado de fetch() - agnóstico al provider type"""
    success: bool
    content: Optional[str]  # html, json string, rss xml, etc
    content_type: str  # "html", "json", "rss", "pdf_text"
    status_code: int = 200
    url: str = ""
    provider: str = ""
    fetched_at: float = 0.0
    error: Optional[str] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.fetched_at == 0.0:
            self.fetched_at = time.time()
        if self.metadata is None:
            self.metadata = {}

@dataclass
class RawOpportunity:
    """Salida de extract() - aún no normalizada, pero ya estructurada"""
    title: str
    url: str
    raw_data: Dict[str, Any]  # todo lo que extrajo el provider
    provider: str
    organization_slug: str
    fetched_at: float = 0.0

    def __post_init__(self):
        if self.fetched_at == 0.0:
            self.fetched_at = time.time()

@dataclass
class NormalizedOpportunity:
    """Salida final de normalize() - lista para insertar en DB opportunities"""
    title: str
    organizer_name: str
    organization_slug: str
    official_link: str
    description_raw: str = ""
    description_clean: str = ""
    deadline: Optional[str] = None  # ISO 8601
    open_date: Optional[str] = None
    awards_text: str = ""
    economic_value: Optional[float] = None
    currency: str = ""
    category: str = "General"
    opportunity_type: str = "contest"  # contest, grant, residency, fellowship, accelerator, hackathon, beta, etc - MOTOR GENERICO
    country: str = ""
    language: str = ""
    source_url: str = ""  # de qué url vino
    provider: str = ""
    extra_json: Dict[str, Any] = None

    def __post_init__(self):
        if self.extra_json is None:
            self.extra_json = {}

    def is_valid(self) -> bool:
        """Mínimos para ser opportunity válida"""
        return bool(self.title and len(self.title) >= 3 and self.official_link)


class Provider(ABC):
    """
    Interfaz base que TODOS los plugins deben implementar.
    Diseño desacoplado para escalar a RSS, API, MCP, etc.
    """
    
    def __init__(self, organization_slug: str, config: Dict[str, Any] = None):
        self.organization_slug = organization_slug
        self.config = config or {}
        self.name = self.__class__.__name__
    
    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Tipo: 'playwright', 'beautifulsoup', 'rss', 'api', 'json', 'mcp', etc"""
        pass
    
    def candidate_urls(self, url: str) -> List[str]:
        """
        Retorna lista de URLs candidatas a probar para este provider.
        Por defecto solo [url].
        Plugins pueden overridear para definir múltiples candidatos sin tocar base Provider:
        Ej. Posterheroes:
        [
            "https://posterheroes.org/competition/",
            "https://www.posterheroes.org/competition/",
            "https://www.posterheroes.org/",
            "https://posterheroes.org/"
        ]
        Así cualquier plugin futuro puede definir [competitions, open-call, calls, root, archive] sin tocar base.
        """
        return [url]
    
    def fetch_first_success(self, url: str, candidate_urls: List[str] = None) -> FetchResult:
        """
        Intenta fetch en lista de URLs candidatas hasta primer éxito.
        Genérico, reutilizable por cualquier plugin futuro.
        Evita hardcodear fallback chain en cada provider de forma ad-hoc.
        
        Args:
            url: URL original
            candidate_urls: lista opcional, si None usa self.candidate_urls(url)
        
        Returns:
            FetchResult del primer éxito, o último fallo si todos fallan
        """
        from core.logger import get_logger
        logger = get_logger("provider")
        
        urls_to_try = candidate_urls or self.candidate_urls(url)
        
        last_error = None
        last_result = None
        
        for try_url in urls_to_try:
            try:
                logger.info(f"[{self.name}] Fetching {try_url} (candidate)")
                result = self.fetch_single(try_url)
                if result.success and result.content and len(result.content) > 500:
                    # Verificar no es 404 page camuflada
                    if "Page not found" in result.content and len(result.content) < 2000:
                        last_error = f"404 page for {try_url}"
                        last_result = result
                        continue
                    logger.info(f"[{self.name}] Fetched OK {try_url} {len(result.content)} bytes")
                    return result
                else:
                    last_error = f"Status {result.status_code} or empty content for {try_url}"
                    last_result = result
                    continue
            except Exception as e:
                last_error = str(e)
                logger.warning(f"[{self.name}] Fetch failed {try_url}: {e}")
                continue
        
        # Todos fallaron, retornar último resultado con error
        if last_result:
            return FetchResult(
                success=False,
                content=None,
                content_type="html",
                status_code=last_result.status_code if last_result else 0,
                url=url,
                provider=self.provider_type,
                error=last_error or "All candidate URLs failed"
            )
        
        return FetchResult(
            success=False,
            content=None,
            content_type="html",
            status_code=0,
            url=url,
            provider=self.provider_type,
            error=last_error or "All candidate URLs failed"
        )
    
    def fetch_single(self, url: str) -> FetchResult:
        """
        Fetch de una sola URL, sin fallback. Por defecto llama a fetch().
        Plugins pueden overridear fetch() con lógica específica, pero fetch_single es el bloque básico
        que usa fetch_first_success para no duplicar lógica.
        Por defecto implementa httpx GET con headers Radar, timeout 30s.
        Plugins que necesiten Playwright pueden overridear fetch_single.
        """
        import httpx
        from core.logger import get_logger
        logger = get_logger("provider")
        
        try:
            resp = httpx.get(
                url,
                timeout=30,
                headers={
                    "User-Agent": "Radar/3.0 Opportunity Intelligence (+https://radar.local)",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9"
                },
                follow_redirects=True
            )
            
            return FetchResult(
                success=resp.status_code == 200 and len(resp.text) > 500,
                content=resp.text if resp.status_code == 200 else None,
                content_type="html",
                status_code=resp.status_code,
                url=url,
                provider=self.provider_type,
                error=None if resp.status_code == 200 else f"Status {resp.status_code}"
            )
        except Exception as e:
            logger.warning(f"[{self.name}] fetch_single failed {url}: {e}")
            return FetchResult(
                success=False,
                content=None,
                content_type="html",
                status_code=0,
                url=url,
                provider=self.provider_type,
                error=str(e)
            )
    
    @abstractmethod
    def fetch(self, url: str) -> FetchResult:
        """
        Trae contenido crudo. No parsea.
        Puede ser: requests.get, playwright.goto, feedparser.parse, api client, etc.
        Por defecto, para providers que implementan candidate_urls() + fetch_single(),
        fetch() puede simplemente llamar fetch_first_success().
        
        Ejemplo Posterheroes:
        def fetch(self, url):
            return self.fetch_first_success(url)
        
        Así cualquier plugin futuro puede definir candidate_urls() sin tocar base.
        """
        pass
    
    @abstractmethod
    def extract(self, fetch_result: FetchResult) -> List[RawOpportunity]:
        """
        Convierte raw en lista de oportunidades semi-estructuradas.
        Aquí va BeautifulSoup, lxml, json.loads, etc.
        """
        pass
    
    @abstractmethod
    def normalize(self, raw: RawOpportunity) -> NormalizedOpportunity:
        """
        Normaliza a formato canónico de Radar.
        Aquí van dateparsers, limpieza de texto, mapeo de categorías, etc.
        """
        pass
    
    def validate(self, normalized: NormalizedOpportunity) -> bool:
        """Hook de validación - puede sobreescribirse por plugin"""
        if not normalized.is_valid():
            return False
        # Validaciones base
        if normalized.deadline:
            # Fecha debe ser parseable
            try:
                from dateutil import parser
                parser.parse(normalized.deadline)
            except:
                return False
        return True
    
    # Pipeline helper - el Job Monitoring solo llama a esto
    def run(self, url: str) -> List[NormalizedOpportunity]:
        """Pipeline completo: fetch -> extract -> normalize -> validate"""
        fetch_res = self.fetch(url)
        if not fetch_res.success:
            return []
        
        raw_list = self.extract(fetch_res)
        normalized = []
        for raw in raw_list:
            try:
                norm = self.normalize(raw)
                if self.validate(norm):
                    normalized.append(norm)
            except Exception as e:
                # Log pero no rompe el resto (ticket atómico)
                from core.logger import get_logger
                logger = get_logger("provider")
                logger.warning(f"[{self.name}] normalize failed for {raw.title[:50]}: {e}")
                continue
        return normalized


# Ejemplo de cómo se vería un provider RSS futuro (no implementar ahora, solo demostrar extensibilidad)
class RSSProvider(Provider):
    """Ejemplo de provider futuro - no usado en v3.0, pero demuestra que la interfaz está lista"""
    @property
    def provider_type(self) -> str:
        return "rss"
    
    def fetch(self, url: str) -> FetchResult:
        # import feedparser
        # return feedparser.parse(url)
        raise NotImplementedError("RSS provider para ticket futuro")
    
    def extract(self, fetch_result: FetchResult) -> List[RawOpportunity]:
        raise NotImplementedError
    
    def normalize(self, raw: RawOpportunity) -> NormalizedOpportunity:
        raise NotImplementedError
