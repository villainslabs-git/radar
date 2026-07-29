import pytest
import importlib.util
from pathlib import Path
from core.provider import FetchResult

def get_provider():
    # Cargar dinámicamente debido al guion en el nombre del folder
    path = Path("plugins/ai-film-festival/plugin.py")
    spec = importlib.util.spec_from_file_location("plugins.ai_film_festival.plugin", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.AIFilmFestivalProvider(organization_slug="ai-film-festival")

def test_aifilmfest_extract():
    html = "<html><head><title>AI Film Festival 2026</title></head><body></body></html>"
    provider = get_provider()
    fr = FetchResult(success=True, content=html, content_type="html", url="https://aifilmfest.com/", provider="bs4")
    
    raw_list = provider.extract(fr)
    assert len(raw_list) == 1
    assert raw_list[0].title == "AI Film Festival 2026"
