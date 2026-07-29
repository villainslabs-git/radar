import pytest
from plugins.itsnicethat.plugin import ItsNiceThatProvider
from core.provider import FetchResult

def test_itsnicethat_extract():
    html = """
    <html>
        <body>
            <article>
                <h3>Open call for Poster Heroes 2026</h3>
                <p>The annual competition is now open...</p>
                <a href="/news/poster-heroes-2026-open-call">Read more</a>
            </article>
            <article>
                <h3>Random news</h3>
                <p>Just some news about design trends.</p>
                <a href="/news/random">Read more</a>
            </article>
        </body>
    </html>
    """
    provider = ItsNiceThatProvider(organization_slug="itsnicethat")
    fr = FetchResult(success=True, content=html, content_type="html", url="https://www.itsnicethat.com/news", provider="bs4")
    
    raw_list = provider.extract(fr)
    assert len(raw_list) == 1
    assert "Poster Heroes 2026" in raw_list[0].title
    assert raw_list[0].url == "https://www.itsnicethat.com/news/poster-heroes-2026-open-call"
