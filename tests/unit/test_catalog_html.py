import pytest

from core.news.catalog_html import html_to_pdf, render_catalog_html, save_catalog_html, save_catalog_pdf
from interfaces.vk.vk_interface import CATALOG_DOC_FILENAME, catalog_doc_url_from_save


def test_render_catalog_html_is_mobile_and_contains_both_branches(
    garant_api_categories_branched_sample,
):
    html = render_catalog_html(garant_api_categories_branched_sample["categories"])

    assert 'name="viewport"' in html
    assert "width=device-width" in html
    assert "<h2>Справка</h2>" in html
    assert "Новости в сфере образование за 6 месяцев" in html
    assert "Сферы интересов" in html
    assert "Фильтры" in html
    assert "Воздушный транспорт" in html
    assert "Строительство" in html
    assert "г.Москва" in html
    assert "F7F1E8" in html
    assert "<script" not in html.lower()


def test_save_catalog_html_writes_docs_file(tmp_path, garant_api_categories_branched_sample):
    html = render_catalog_html(garant_api_categories_branched_sample["categories"])
    path = save_catalog_html(html, path=tmp_path / "garant-sfery-i-filtry.html")

    assert path.is_file()
    saved = path.read_text(encoding="utf-8")
    assert "Воздушный транспорт" in saved
    assert "viewport" in saved


def test_save_catalog_pdf_writes_docs_file(tmp_path):
    path = save_catalog_pdf(b"%PDF-1.4 catalog", path=tmp_path / "garant-sfery-i-filtry.pdf")

    assert path.is_file()
    assert path.read_bytes().startswith(b"%PDF")


def test_catalog_doc_url_from_save_models_and_dicts():
    class Doc:
        owner_id = -111
        id = 222

    class Saved:
        doc = Doc()

    assert catalog_doc_url_from_save(Saved()) == "https://vk.com/doc-111_222"
    assert catalog_doc_url_from_save({"owner_id": 5, "id": 9}) == "https://vk.com/doc5_9"
    assert catalog_doc_url_from_save(None) is None
    assert CATALOG_DOC_FILENAME.endswith(".pdf")


@pytest.mark.asyncio
async def test_html_to_pdf_prints_via_chromium(monkeypatch):
    recorded: dict = {}

    class FakePage:
        async def set_content(self, html, wait_until=None):
            recorded["html"] = html

        async def pdf(self, **kwargs):
            recorded["pdf_kwargs"] = kwargs
            return b"%PDF-1.4 mock"

    class FakeBrowser:
        async def new_page(self):
            return FakePage()

        async def close(self):
            recorded["closed"] = True

    class FakeChromium:
        async def launch(self, headless=True):
            recorded["headless"] = headless
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr("playwright.async_api.async_playwright", lambda: FakePlaywright())

    result = await html_to_pdf("<html>каталог</html>")

    assert result.startswith(b"%PDF")
    assert recorded["html"] == "<html>каталог</html>"
    assert recorded["headless"] is True
    assert recorded["pdf_kwargs"]["print_background"] is True
    assert recorded["closed"] is True
