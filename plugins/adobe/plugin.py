from core.provider import Provider, FetchResult, RawOpportunity, NormalizedOpportunity
from typing import List
from bs4 import BeautifulSoup
import httpx
import re

class AdobeProvider(Provider):
    @property
    def provider_type(self) -> str:
        return "beautifulsoup"

    def candidate_urls(self, url: str = None) -> List[str]:
        return [
            "https://www.adobe.com/creativecloud/buy/students.html",
            "https://blog.adobe.com/en/topics/creative-residency.html"
        ]

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
            return FetchResult(
                success=False,
                content=None,
                content_type="html",
                url=url,
                provider=self.provider_type,
                error=str(e)
            )

    def extract(self, fr: FetchResult) -> List[RawOpportunity]:
        if not fr.success or not fr.content:
            return []
        
        soup = BeautifulSoup(fr.content, "html.parser")
        opportunities = []

        # Estrategia 1: Tarjetas específicas (opportunity-card)
        cards = soup.find_all(class_="opportunity-card")
        if cards:
            for card in cards:
                title_elem = card.find(class_="title") or card.find("h2")
                link_elem = card.find("a", class_="apply-link") or card.find("a")
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    url = link_elem.get("href") if link_elem else fr.url
                    opportunities.append(RawOpportunity(
                        title=title,
                        url=url,
                        raw_data={"description": card.get_text(" ", strip=True)},
                        provider=self.provider_type,
                        organization_slug=self.organization_slug
                    ))
        
        # Estrategia 2: Fallback si no hay tarjetas, buscar títulos sueltos
        if not opportunities:
            titles = soup.find_all(class_="title")
            for t in titles:
                opportunities.append(RawOpportunity(
                    title=t.get_text(strip=True),
                    url=fr.url,
                    raw_data={},
                    provider=self.provider_type,
                    organization_slug=self.organization_slug
                ))

        # Estrategia 3: Fallback a Meta Tags si sigue vacío
        if not opportunities:
            og_title = soup.find("meta", property="og:title")
            desc = soup.find("meta", attrs={"name": "description"})
            if og_title:
                opportunities.append(RawOpportunity(
                    title=og_title.get("content"),
                    url=fr.url,
                    raw_data={"description": desc.get("content") if desc else ""},
                    provider=self.provider_type,
                    organization_slug=self.organization_slug
                ))
            elif desc:
                opportunities.append(RawOpportunity(
                    title=desc.get("content")[:100], # Usar inicio de desc como título
                    url=fr.url,
                    raw_data={"description": desc.get("content")},
                    provider=self.provider_type,
                    organization_slug=self.organization_slug
                ))

        return opportunities

    def normalize(self, raw: RawOpportunity) -> NormalizedOpportunity:
        return NormalizedOpportunity(
            title=raw.title,
            organizer_name="Adobe",
            organization_slug=self.organization_slug,
            official_link=raw.url,
            description_raw=raw.raw_data.get("description", ""),
            source_url=raw.url,
            provider=self.provider_type,
            category="Creative Programs"
        )
