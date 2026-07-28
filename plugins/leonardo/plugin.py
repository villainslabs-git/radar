from core.provider import Provider, FetchResult, RawOpportunity, NormalizedOpportunity
from typing import List
class GenericProvider(Provider):
    @property
    def provider_type(self): return "beautifulsoup"
    def fetch(self, url): return FetchResult(success=False, content=None, content_type="html", url=url, provider="beautifulsoup", error="skeleton")
    def extract(self, fr): return []
    def normalize(self, raw): return NormalizedOpportunity(title=raw.title, organizer_name=self.organization_slug, organization_slug=self.organization_slug, official_link=raw.url, source_url=raw.url, provider=self.provider_type)
