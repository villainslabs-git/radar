from core.provider import Provider, FetchResult, RawOpportunity, NormalizedOpportunity
from typing import List
from bs4 import BeautifulSoup
import httpx
from core.logger import get_logger

logger = get_logger("provider.aifilmfest")

class AIFilmFestivalProvider(Provider):
    @property
    def provider_type(self) -> str:
        return "playwright" 

    def candidate_urls(self, url: str = None) -> List[str]:
        return ["https://aifilmfest.com/"]

    def fetch(self, url: str) -> FetchResult:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent="Radar/3.0")
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                content = page.content()
                status_code = 200
                browser.close()
                if len(content) > 500:
                    return FetchResult(
                        success=True, content=content, content_type="html",
                        status_code=status_code, url=url, provider="playwright"
                    )
        except Exception as e:
            logger.warning(f"Playwright failed for {url}: {e}, falling back to httpx")

        return self.fetch_single(url)

    def extract(self, fr: FetchResult) -> List[RawOpportunity]:
        if not fr.success or not fr.content: return []
        soup = BeautifulSoup(fr.content, "html.parser")
        opportunities = []
        
        main_title = soup.find("title")
        main_title_text = main_title.get_text(strip=True) if main_title else "AI Film Festival"
        main_title_text = main_title_text.split("|")[0].split("-")[0].strip()

        headings = soup.find_all(["h1", "h2", "h3"])
        found_sub = False
        for h in headings:
            text = h.get_text(" ", strip=True)
            if any(kw in text.lower() for kw in ["award", "category", "competition", "track", "submit", "open call"]):
                found_sub = True
                opportunities.append(RawOpportunity(
                    title=f"{main_title_text} - {text}",
                    url=fr.url,
                    raw_data={"section": text},
                    provider=self.provider_type,
                    organization_slug=self.organization_slug
                ))
        
        if not found_sub:
            opportunities.append(RawOpportunity(
                title=main_title_text,
                url=fr.url,
                raw_data={"source": "main_page"},
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