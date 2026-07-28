from core.provider import Provider, FetchResult, RawOpportunity, NormalizedOpportunity
from typing import List
class AdobeProvider(Provider):
    @property
    def provider_type(self): return "beautifulsoup"
    def fetch(self, url):
        import httpx
        try:
            r=httpx.get(url, timeout=20, headers={"User-Agent":"Radar/3.0"})
            return FetchResult(success=r.status_code==200, content=r.text, content_type="html", status_code=r.status_code, url=url, provider=self.provider_type)
        except Exception as e:
            return FetchResult(success=False, content=None, content_type="html", url=url, provider=self.provider_type, error=str(e))
    def extract(self, fr): return []
    def normalize(self, raw): return NormalizedOpportunity(title=raw.title, organizer_name="Adobe", organization_slug="adobe", official_link=raw.url, source_url=raw.url, provider=self.provider_type)
