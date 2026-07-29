from core.provider import Provider, FetchResult, RawOpportunity, NormalizedOpportunity
from typing import List
from bs4 import BeautifulSoup
import httpx
import re

class ItsNiceThatProvider(Provider):
    @property
    def provider_type(self) -> str:
        return "beautifulsoup"

    def candidate_urls(self, url: str = None) -> List[str]:
        urls = ["https://www.itsnicethat.com/news"]
        if url and url not in urls:
            urls.insert(0, url)
        return urls

    def fetch(self, url: str) -> FetchResult:
        return self.fetch_first_success(url)

    def extract(self, fr: FetchResult) -> List[RawOpportunity]:
        if not fr.success or not fr.content: return []
        soup = BeautifulSoup(fr.content, "html.parser")
        opportunities = []

        articles = soup.find_all("article")
        for art in articles:
            text = art.get_text(" ", strip=True).lower()
            keywords = [
                "competition", "open call", "award", "prize", "funding", 
                "grant", "residency", "fellowship", "opportunity", "submit", 
                "scholarship", "bursary", "commission"
            ]
            if any(re.search(rf"\b{kw}s?\b", text) for kw in keywords):
                title_elem = art.find(["h1", "h2", "h3", "h4"])
                link_elem = art.find("a")
                if title_elem and link_elem:
                    title = title_elem.get_text(strip=True)
                    url = link_elem.get("href")
                    if url and not url.startswith("http"):
                        url = "https://www.itsnicethat.com" + url
                    
                    opportunities.append(RawOpportunity(
                        title=title,
                        url=url,
                        raw_data={"snippet": text[:200]},
                        provider=self.provider_type,
                        organization_slug=self.organization_slug
                    ))

        return opportunities

    def normalize(self, raw: RawOpportunity) -> NormalizedOpportunity:
        target_org = self.organization_slug
        url = raw.url.lower()
        if "runwayml.com" in url:
            target_org = "runway"
        elif "posterheroes.org" in url:
            target_org = "posterheroes"
        elif "adobe.com" in url:
            target_org = "adobe"
            
        return NormalizedOpportunity(
            title=raw.title,
            organizer_name=target_org.replace("-", " ").title(),
            organization_slug=target_org,
            official_link=raw.url,
            source_url=raw.url,
            provider=self.provider_type,
            category="Magazine / Aggregator",
            opportunity_type="aggregator"
        )