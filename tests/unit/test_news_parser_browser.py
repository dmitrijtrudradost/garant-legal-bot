from datetime import date
import asyncio

import pytest

from core.models import NewsItem, NewsQuery
from core.news.parser_browser import (
    GarantPrimeParser,
    browser_theme_keywords,
    document_url,
    login_blocked_reason,
    query_fingerprint,
    startpage_url,
)
from core.news.parser_base import NewsSourceBusyError


def test_login_blocked_reason_detects_alreadyused():
    assert (
        login_blocked_reason(
            "https://www.garant.ru/mobileonline/alreadyused/", "<html></html>"
        )
        == "busy"
    )
    assert (
        login_blocked_reason(
            "https://internet.garant.ru/#/startpage:1",
            "Ваш логин и пароль уже используются",
        )
        == "busy"
    )
    assert login_blocked_reason("https://internet.garant.ru/", "<button>Войти</button>") is None
    splash = (
        '<p>доступ к Интернет.</p><div class="rules">'
        '<a href="http://www.garant.ru/mobileonline/rules/">Правила работы</a></div>'
    )
    assert (
        login_blocked_reason("https://internet.garant.ru/#/startpage:1", splash) == "busy"
    )


def test_query_fingerprint_same_filters_match():
    first = NewsQuery(date_from=date(2026, 1, 12), date_to=date(2026, 9, 9), topic=["охранная деятельность"])
    second = NewsQuery(date_from=date(2026, 1, 12), date_to=date(2026, 9, 9), topic=["охранная деятельность"])
    other = NewsQuery(date_from=date(2026, 8, 1), date_to=date(2026, 9, 9))
    assert query_fingerprint(first) == query_fingerprint(second)
    assert query_fingerprint(first) != query_fingerprint(other)


def test_browser_theme_keywords_skips_all_main_bundle():
    from core.news.presets import PRESET_ALL_MAIN, PRESET_SECURITY_ORG

    assert browser_theme_keywords(PRESET_SECURITY_ORG()) == [
        "Частная сыскная и охранная деятельность"
    ]
    assert browser_theme_keywords(PRESET_ALL_MAIN()) is None
    assert browser_theme_keywords(NewsQuery(date_from=date(2026, 1, 1), date_to=date(2026, 1, 2))) is None


def test_parse_html_from_joined_card_fragments():
    parser = GarantPrimeParser(login="fake-login", password="fake-password")
    html = (
        '<div class="primeDate">06 сентября 2026</div>'
        '<div class="primeDocument"><div class="documentTitle">'
        '<a href="/#/document/1">Первая</a></div></div>\n'
        '<div class="primeDate">05 сентября 2026</div>'
        '<div class="primeDocument"><div class="documentTitle">'
        '<a href="/#/document/2">Вторая</a></div></div>'
    )
    items = parser._parse_html(html)
    assert [item.title for item in items] == ["Первая", "Вторая"]
    assert items[0].url == "https://internet.garant.ru/#/document/1"
    assert items[1].published_at == date(2026, 9, 5)


@pytest.mark.asyncio
async def test_click_start_login_missing_button_is_busy_not_empty():
    parser = GarantPrimeParser(login="fake-login", password="fake-password")

    class _Locator:
        first = None

        def __init__(self):
            self.first = self

        async def wait_for(self, **kwargs):
            raise TimeoutError("waiting for locator(\"button[type=\\\"submit\\\"]\")")

        async def click(self):
            raise AssertionError("нельзя кликать, если кнопки нет")

    class _Page:
        url = "https://internet.garant.ru/#/startpage:1"

        def locator(self, selector):
            assert "submit" in selector
            return _Locator()

        async def content(self):
            return "<html><body><center>stub</center></body></html>"

    with pytest.raises(NewsSourceBusyError) as exc:
        await parser._click_start_login(_Page())
    assert exc.value.retry_after_seconds == GarantPrimeParser.MIN_SECONDS_BETWEEN_LOGINS


@pytest.mark.asyncio
async def test_click_start_login_splash_is_busy_without_waiting_for_submit():
    parser = GarantPrimeParser(login="fake-login", password="fake-password")

    class _Page:
        url = "https://internet.garant.ru/#/startpage:1"

        def locator(self, selector):
            raise AssertionError("на заглушке mobileonline нельзя ждать submit")

        async def content(self):
            return (
                '<html><body><p>доступ к Интернет.</p>'
                '<a href="http://www.garant.ru/mobileonline/rules/">Правила работы</a>'
                "</body></html>"
            )

    with pytest.raises(NewsSourceBusyError):
        await parser._click_start_login(_Page())


def test_startpage_url_adds_hash_to_origin():
    assert startpage_url("https://internet.garant.ru") == "https://internet.garant.ru/#/startpage:1"
    assert startpage_url("https://demo.garant.ru/") == "https://demo.garant.ru/#/startpage:1"
    assert startpage_url("https://demo.garant.ru/#/startpage:1") == "https://demo.garant.ru/#/startpage:1"


def test_parse_html_extracts_news_items(garant_prime_sample_html):
    parser = GarantPrimeParser(login="fake-login", password="fake-password")

    items = parser._parse_html(garant_prime_sample_html)

    assert len(items) == 3

    first = items[0]
    assert "Приказ Росгвардии" in first.title
    assert "Росгвардия уточнила порядок" in first.summary
    assert first.url == "https://internet.garant.ru/#/document/414837873/entry/0"
    assert first.published_at == date(2026, 9, 6)


def test_parse_html_document_url_follows_parser_origin(garant_prime_sample_html):
    parser = GarantPrimeParser(
        login="fake-login", password="fake-password", base_url="https://demo.garant.ru"
    )
    items = parser._parse_html(garant_prime_sample_html)
    assert items[0].url == "https://demo.garant.ru/#/document/414837873/entry/0"


def test_document_url_keeps_absolute_href():
    assert (
        document_url("https://internet.garant.ru", "https://internet.garant.ru/#/document/1")
        == "https://internet.garant.ru/#/document/1"
    )
    assert document_url("https://internet.garant.ru", None) is None


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
async def test_fetch_reuses_same_query_within_cooldown(monkeypatch):
    """Дубль того же запроса (два сообщения подряд) не логинится второй раз и не Busy."""
    parser = GarantPrimeParser(login="fake-login", password="fake-password")
    render_calls = []

    async def fake_render_page(query):
        render_calls.append(query)
        return (
            '<div class="primeDocument"><div class="documentTitle">'
            '<a href="/#/document/1">Новость</a></div></div>'
        )

    monkeypatch.setattr(parser, "_render_page", fake_render_page)
    query = _make_query()
    first = await parser.fetch(query)
    second = await parser.fetch(query)

    assert len(render_calls) == 1
    assert [item.title for item in first] == ["Новость"]
    assert [item.title for item in second] == ["Новость"]


@pytest.mark.asyncio
async def test_fetch_parallel_same_query_one_login(monkeypatch):
    parser = GarantPrimeParser(login="fake-login", password="fake-password")
    render_calls = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_render_page(query):
        render_calls.append(query)
        started.set()
        await release.wait()
        return "<html></html>"

    monkeypatch.setattr(parser, "_render_page", fake_render_page)
    query = _make_query()
    first_task = asyncio.create_task(parser.fetch(query))
    await started.wait()
    second_task = asyncio.create_task(parser.fetch(query))
    await asyncio.sleep(0.05)
    release.set()
    first, second = await asyncio.gather(first_task, second_task)

    assert len(render_calls) == 1
    assert first == second


@pytest.mark.asyncio
async def test_fetch_busy_for_other_query_within_cooldown(monkeypatch):
    parser = GarantPrimeParser(login="fake-login", password="fake-password")
    render_calls = []

    async def fake_render_page(query):
        render_calls.append(query)
        return "<html></html>"

    monkeypatch.setattr(parser, "_render_page", fake_render_page)

    await parser.fetch(_make_query())
    other = NewsQuery(date_from=date(2026, 8, 1), date_to=date(2026, 9, 9))
    with pytest.raises(NewsSourceBusyError):
        await parser.fetch(other)

    assert len(render_calls) == 1


@pytest.mark.asyncio
async def test_fetch_retries_after_cooldown_elapsed(monkeypatch):
    parser = GarantPrimeParser(login="fake-login", password="fake-password")
    render_calls = []
    fake_now = [1000.0]

    async def fake_render_page(query):
        render_calls.append(query)
        return "<html></html>"

    monkeypatch.setattr(parser, "_render_page", fake_render_page)
    monkeypatch.setattr("core.news.parser_browser.time.monotonic", lambda: fake_now[0])

    await parser.fetch(_make_query())
    fake_now[0] += GarantPrimeParser.MIN_SECONDS_BETWEEN_LOGINS + 1
    await parser.fetch(_make_query())

    assert len(render_calls) == 2
