from datetime import date

import pytest

from core.models import NewsItem, NewsQuery
from core.news.parser import GarantPrimeParser


def test_parse_html_extracts_news_items(garant_prime_sample_html):
    parser = GarantPrimeParser(login="fake-login", password="fake-password")

    items = parser._parse_html(garant_prime_sample_html)

    assert len(items) == 3

    first = items[0]
    assert "Приказ Росгвардии" in first.title
    assert "Росгвардия уточнила порядок" in first.summary
    assert first.url == "/#/document/414837873/entry/0"
    assert first.published_at == date(2026, 9, 6)


def test_parse_html_applies_date_to_all_documents_until_next_primedate(garant_prime_sample_html):
    parser = GarantPrimeParser(login="fake-login", password="fake-password")

    items = parser._parse_html(garant_prime_sample_html)

    # Первые два документа относятся к дате "06 сентября 2026", третий — к "05 сентября 2026".
    assert items[0].published_at == date(2026, 9, 6)
    assert items[1].published_at == date(2026, 9, 6)
    assert items[2].published_at == date(2026, 9, 5)


def test_parse_html_returns_empty_list_for_no_matches():
    parser = GarantPrimeParser(login="fake-login", password="fake-password")

    items = parser._parse_html("<html><body><p>Нет новостей</p></body></html>")

    assert items == []


def test_parse_russian_date():
    assert GarantPrimeParser._parse_russian_date("06 сентября 2026") == date(2026, 9, 6)
    assert GarantPrimeParser._parse_russian_date("1 января 2027") == date(2027, 1, 1)
    assert GarantPrimeParser._parse_russian_date("не дата") is None


def _make_query() -> NewsQuery:
    return NewsQuery(date_from=date(2026, 1, 1), date_to=date(2026, 1, 31))


@pytest.mark.asyncio
async def test_fetch_calls_render_page_on_first_request(monkeypatch):
    parser = GarantPrimeParser(login="fake-login", password="fake-password")
    render_calls = []

    async def fake_render_page(query):
        render_calls.append(query)
        return "<html></html>"

    monkeypatch.setattr(parser, "_render_page", fake_render_page)

    items = await parser.fetch(_make_query())

    assert len(render_calls) == 1
    assert items == []  # пустой HTML — пустой список, это нормально для этого теста


@pytest.mark.asyncio
async def test_fetch_skips_login_within_cooldown(monkeypatch):
    """Сайт просит не логиниться слишком часто — второй запрос сразу же не должен пытаться войти снова."""
    parser = GarantPrimeParser(login="fake-login", password="fake-password")
    render_calls = []

    async def fake_render_page(query):
        render_calls.append(query)
        return "<html></html>"

    monkeypatch.setattr(parser, "_render_page", fake_render_page)

    await parser.fetch(_make_query())
    items_second = await parser.fetch(_make_query())

    assert len(render_calls) == 1  # второй вызов пропущен из-за кулдауна
    assert items_second == []


@pytest.mark.asyncio
async def test_fetch_retries_after_cooldown_elapsed(monkeypatch):
    parser = GarantPrimeParser(login="fake-login", password="fake-password")
    render_calls = []
    fake_now = [1000.0]

    async def fake_render_page(query):
        render_calls.append(query)
        return "<html></html>"

    monkeypatch.setattr(parser, "_render_page", fake_render_page)
    monkeypatch.setattr("core.news.parser.time.monotonic", lambda: fake_now[0])

    await parser.fetch(_make_query())
    fake_now[0] += GarantPrimeParser.MIN_SECONDS_BETWEEN_LOGINS + 1
    await parser.fetch(_make_query())

    assert len(render_calls) == 2
