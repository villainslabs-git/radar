"""
Plugin Runway - Ejemplo de Provider concreto
Motor genérico: puede traer contests, grants, beta programs con misma interfaz

Para Ticket 002 es skeleton, implementación real en Ticket 011
"""
from core.provider import Provider, FetchResult, RawOpportunity, NormalizedOpportunity
from typing import List
import httpx
from core.logger import get_logger

logger = get_logger("provider")

class RunwayProvider(Provider):
    @property
    def provider_type(self) -> str:
        return "playwright"  # futuro: playwright, hoy httpx para demo
    
    def fetch(self, url: str) -> FetchResult:
        # Skeleton - en ticket real usará playwright + httpx
        try:
            resp = httpx.get(url, timeout=20, headers={"User-Agent": "Radar/3.0"})
            return FetchResult(
                success=resp.status_code == 200,
                content=resp.text if resp.status_code == 200 else None,
                content_type="html",
                status_code=resp.status_code,
                url=url,
                provider=self.provider_type
            )
        except Exception as e:
            logger.warning(f"Runway fetch failed {url}: {e}")
            return FetchResult(success=False, content=None, content_type="html", status_code=0, url=url, provider=self.provider_type, error=str(e))
    
    def extract(self, fetch_result: FetchResult) -> List[RawOpportunity]:
        # Skeleton: en futuro parsear con BeautifulSoup + selectors
        # Por ahora retorna vacío - solo demuestra interfaz Provider lista desde día 0
        return []
    
    def normalize(self, raw: RawOpportunity) -> NormalizedOpportunity:
        return NormalizedOpportunity(
            title=raw.title,
            organizer_name="Runway",
            organization_slug="runway",
            official_link=raw.url,
            description_raw=raw.raw_data.get("description", ""),
            source_url=raw.url,
            provider=self.provider_type
        )
