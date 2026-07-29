from core.provider import Provider, FetchResult, RawOpportunity, NormalizedOpportunity
from typing import List
from bs4 import BeautifulSoup
import httpx

class AIFilmFestivalProvider(Provider):
    @property
    def provider_type(self) -> str:
        return "beautifulsoup"

    def candidate_urls(self, url: str = None) -> List[str]:
        return ["https://aifilmfest.com/"]

    def fetch(self, url: str) -> FetchResult:
        try:
            r = httpx.get(url, timeout=20, headers={"User-Agent": "Radar/3.0"})
            return FetchResult(
                success=r.status_code == 200,
                content=r.text,
                content_type="html",
                status_code=r.status_code,
                url=url,
                provider=self.provider_type
            )
        except Exception as e:
            return FetchResult(success=False, content=None, content_type="html", url=url, provider=self.provider_type, error=str(e))

    def extract(self, fr: FetchResult) -> List[RawOpportunity]:
        if not fr.success or not fr.content: return []
        soup = BeautifulSoup(fr.content, "html.parser")
        opportunities = []
        
        # Simulación de extracción para un festival específico
        # En una implementación real buscaríamos enlaces a 'Submit' o 'Open Call'
        title_tag = soup.find("title")
        if title_tag:
            opportunities.append(RawOpportunity(
                title=title_tag.get_text(strip=True),
                url=fr.url,
                raw_data={"source": "aggregator"},
                provider=self.provider_type,
                organization_slug=self.organization_slug
            ))
            
        return opportunities

    def normalize(self, raw: RawOpportunity) -> NormalizedOpportunity:
        return NormalizedOpportunity(
            title=raw.title,
            organizer_name="AI Film Festival",
            organization_slug=self.organization_slug,
            official_link=raw.url,
            source_url=raw.url,
            provider=self.provider_type,
            category="Festival"
        )
