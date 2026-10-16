from datetime import date, timedelta

import pytest

from core.bot_core import (
    LIMITS_FAILED_TEXT,
    LIMITS_UNAVAILABLE_TEXT,
    BotCore,
    SHOW_MORE_EXHAUSTED_TEXT,
    SHOW_MORE_NO_RESULTS_TEXT,
    news_source_busy_text,
)
from core.dialogue_service import DialogueService
from core.history import InMemoryDialogueHistory
from core.intent_router import IntentRouter
from core.models import IncomingMessage, NewsItem
from core.news.formatter import NewsFormatter
from core.news.results_cache import InMemoryNewsResultsCache
from core.news.parser_base import NewsSourceBusyError


class FakeAIClient:
    async def complete(self, messages, *, temperature=None, max_tokens=None):
        raise AssertionError("Новостной запрос не должен доходить до AIClient")


class FakeNewsParser:
    def __init__(self, items):
        self._items = items
        self.received_query = None

    async def fetch(self, query):
        self.received_query = query
        return self._items


def make_bot_core(news_parser, *, intent_router=None):
    return BotCore(
        dialogue_service=DialogueService(InMemoryDialogueHistory(), FakeAIClient()),
        intent_router=intent_router or IntentRouter(),
        news_parser=news_parser,
        news_formatter=NewsFormatter(),
        results_cache=InMemoryNewsResultsCache(),
    )


@pytest.mark.asyncio
async def test_news_request_returns_formatted_items():
    news_parser = FakeNewsParser(
        [NewsItem(title="Новый закон", summary="Описание", published_at=date(2026, 1, 1))]
    )
    bot_core = make_bot_core(news_parser)

    incoming = IncomingMessage(
        peer_id="peer1", user_name=None, text="Предоставь мне изменения в законодательстве", interface="console"
    )
    outgoing = await bot_core.handle_message(incoming)

    assert "Новый закон" in outgoing.text
    assert news_parser.received_query is not None


@pytest.mark.asyncio
async def test_news_request_with_no_results_returns_placeholder():
    bot_core = make_bot_core(FakeNewsParser([]))

    incoming = IncomingMessage(peer_id="peer1", user_name=None, text="Что нового по охране?", interface="console")
    outgoing = await bot_core.handle_message(incoming)

    assert "не найдено" in outgoing.text.lower()


@pytest.mark.asyncio
async def test_news_source_failure_returns_friendly_message():
    class FailingNewsParser:
        async def fetch(self, query):
            raise RuntimeError("источник недоступен")

    bot_core = make_bot_core(FailingNewsParser())

    incoming = IncomingMessage(peer_id="peer1", user_name=None, text="Есть изменения по налогам?", interface="console")
    outgoing = await bot_core.handle_message(incoming)

    assert "не удалось" in outgoing.text.lower()


@pytest.mark.asyncio
async def test_news_source_busy_is_not_empty_feed():
    class BusyNewsParser:
        MIN_SECONDS_BETWEEN_LOGINS = 60

        async def fetch(self, query):
            raise NewsSourceBusyError("alreadyused", retry_after_seconds=self.MIN_SECONDS_BETWEEN_LOGINS)

    bot_core = make_bot_core(BusyNewsParser())
    outgoing = await bot_core.handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="Что нового по охране?", interface="console")
    )

    assert outgoing.text == news_source_busy_text(60)
    assert "1 минуту" in outgoing.text
    assert "не найдено" not in outgoing.text.lower()


@pytest.mark.asyncio
async def test_news_source_busy_wait_text_follows_cooldown_variable():
    class BusyNewsParser:
        MIN_SECONDS_BETWEEN_LOGINS = 120

        async def fetch(self, query):
            raise NewsSourceBusyError(retry_after_seconds=self.MIN_SECONDS_BETWEEN_LOGINS)

    bot_core = make_bot_core(BusyNewsParser())
    outgoing = await bot_core.handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="Что нового по охране?", interface="console")
    )

    assert outgoing.text == news_source_busy_text(120)
    assert "2 минуты" in outgoing.text


@pytest.mark.asyncio
async def test_custom_period_button_without_dates_returns_help_instead_of_news_or_dialogue():
    news_parser = FakeNewsParser([])  # не должен быть вызван вовсе
    bot_core = make_bot_core(news_parser)

    incoming = IncomingMessage(peer_id="peer1", user_name=None, text="📅 Свой период", interface="vk")
    outgoing = await bot_core.handle_message(incoming)

    assert "ДД.ММ.ГГГГ-ДД.ММ.ГГГГ" in outgoing.text
    assert news_parser.received_query is None


@pytest.mark.asyncio
async def test_help_request_does_not_fetch_news():
    news_parser = FakeNewsParser([NewsItem(title="Не должно попасть", summary="x")])
    bot_core = make_bot_core(news_parser)

    outgoing = await bot_core.handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="справка", interface="vk")
    )

    assert "Как спросить новости" in outgoing.text
    assert "остаток запросов" in outgoing.text
    assert "Новости в сфере образование за 6 месяцев" in outgoing.text
    assert news_parser.received_query is None
    assert "Список сфер недоступен" not in outgoing.text
    assert outgoing.catalog_html or outgoing.catalog_pdf


@pytest.mark.asyncio
async def test_help_attaches_catalog_html_when_parser_has_tree(
    garant_api_categories_branched_sample, monkeypatch, tmp_path
):
    class TreeNewsParser(FakeNewsParser):
        async def get_category_tree(self):
            return garant_api_categories_branched_sample["categories"]

    async def fake_html_to_pdf(html: str) -> bytes:
        assert "Воздушный транспорт" in html
        return b"%PDF-1.4 catalog-test"

    monkeypatch.setattr("core.bot_core.html_to_pdf", fake_html_to_pdf)
    monkeypatch.setattr("core.news.catalog_html.CATALOG_HTML_PATH", tmp_path / "garant-sfery-i-filtry.html")
    monkeypatch.setattr("core.news.catalog_html.CATALOG_PDF_PATH", tmp_path / "garant-sfery-i-filtry.pdf")

    news_parser = TreeNewsParser([])
    bot_core = make_bot_core(news_parser)

    outgoing = await bot_core.handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="Справка", interface="vk")
    )

    assert outgoing.catalog_html is not None
    assert outgoing.catalog_pdf == b"%PDF-1.4 catalog-test"
    assert "viewport" in outgoing.catalog_html
    assert "Воздушный транспорт" in outgoing.catalog_html
    assert "Список сфер недоступен" not in outgoing.text
    html_path = tmp_path / "garant-sfery-i-filtry.html"
    pdf_path = tmp_path / "garant-sfery-i-filtry.pdf"
    assert html_path.is_file()
    assert pdf_path.is_file()
    assert "Воздушный транспорт" in html_path.read_text(encoding="utf-8")
    assert pdf_path.read_bytes().startswith(b"%PDF")


@pytest.mark.asyncio
async def test_help_uses_docs_pdf_when_playwright_fails(
    garant_api_categories_branched_sample, monkeypatch, tmp_path
):
    class TreeNewsParser(FakeNewsParser):
        async def get_category_tree(self):
            return garant_api_categories_branched_sample["categories"]

    async def failing_html_to_pdf(html: str) -> bytes:
        raise RuntimeError("no chromium")

    fallback_pdf = tmp_path / "garant-sfery-i-filtry.pdf"
    fallback_pdf.write_bytes(b"%PDF-1.4 from-docs")

    monkeypatch.setattr("core.bot_core.html_to_pdf", failing_html_to_pdf)
    monkeypatch.setattr("core.bot_core.CATALOG_PDF_PATH", fallback_pdf)
    monkeypatch.setattr("core.news.catalog_html.CATALOG_HTML_PATH", tmp_path / "catalog.html")

    outgoing = await make_bot_core(TreeNewsParser([])).handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="Справка", interface="vk")
    )

    assert outgoing.catalog_html is not None
    assert outgoing.catalog_pdf == b"%PDF-1.4 from-docs"


@pytest.mark.asyncio
async def test_help_without_api_tree_uses_saved_docs_catalog(monkeypatch, tmp_path):
    html_path = tmp_path / "garant-sfery-i-filtry.html"
    pdf_path = tmp_path / "garant-sfery-i-filtry.pdf"
    html_path.write_text("<html>сохранённый каталог сфер</html>", encoding="utf-8")
    pdf_path.write_bytes(b"%PDF-1.4 saved")
    monkeypatch.setattr("core.bot_core.CATALOG_HTML_PATH", html_path)
    monkeypatch.setattr("core.bot_core.CATALOG_PDF_PATH", pdf_path)

    outgoing = await make_bot_core(FakeNewsParser([])).handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="Справка", interface="vk")
    )

    assert "Список сфер недоступен" not in outgoing.text
    assert outgoing.catalog_html == "<html>сохранённый каталог сфер</html>"
    assert outgoing.catalog_pdf == b"%PDF-1.4 saved"


@pytest.mark.asyncio
async def test_help_without_api_or_files_says_catalog_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr("core.bot_core.CATALOG_HTML_PATH", tmp_path / "missing.html")
    monkeypatch.setattr("core.bot_core.CATALOG_PDF_PATH", tmp_path / "missing.pdf")

    outgoing = await make_bot_core(FakeNewsParser([])).handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="Справка", interface="vk")
    )

    assert "Список сфер недоступен" in outgoing.text
    assert outgoing.catalog_html is None
    assert outgoing.catalog_pdf is None


@pytest.mark.asyncio
async def test_custom_period_with_dates_goes_to_news_flow():
    news_parser = FakeNewsParser(
        [NewsItem(title="Новый закон", summary="Описание", published_at=date(2026, 8, 15))]
    )
    bot_core = make_bot_core(news_parser)

    incoming = IncomingMessage(peer_id="peer1", user_name=None, text="01.08.2026-06.09.2026", interface="vk")
    outgoing = await bot_core.handle_message(incoming)

    assert "Новый закон" in outgoing.text
    assert news_parser.received_query.date_from == date(2026, 8, 1)
    assert news_parser.received_query.date_to == date(2026, 9, 6)


@pytest.mark.asyncio
async def test_news_pagination_walks_pages_on_show_more():
    items = [NewsItem(title=f"Новость {i}", summary="текст") for i in range(19)]
    news_parser = FakeNewsParser(items)
    bot_core = make_bot_core(news_parser)

    first = await bot_core.handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="Что нового по охране?", interface="console")
    )
    assert "Новость 0" in first.text
    assert "Новость 9" in first.text
    assert "Новость 10" not in first.text
    assert "Показаны 1–10 из 19" in first.text

    second = await bot_core.handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="ещё", interface="console")
    )
    assert "Новость 10" in second.text
    assert "Новость 18" in second.text
    assert "Показаны все 19" in second.text
    assert news_parser.received_query is not None

    third = await bot_core.handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="ещё", interface="console")
    )
    assert third.text == SHOW_MORE_EXHAUSTED_TEXT


@pytest.mark.asyncio
async def test_show_more_without_prior_news_explains():
    bot_core = make_bot_core(FakeNewsParser([]))

    outgoing = await bot_core.handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="ещё", interface="console")
    )

    assert outgoing.text == SHOW_MORE_NO_RESULTS_TEXT


@pytest.mark.asyncio
async def test_fuzzy_news_phrase_goes_through_ai_classifier():
    class ClassifyAI:
        async def complete(self, messages, *, temperature=None, max_tokens=None):
            return '{"is_news": true, "topic": "general", "period_days": 30}'

    news_parser = FakeNewsParser([NewsItem(title="Нормативка", summary="описание")])
    bot_core = make_bot_core(news_parser, intent_router=IntentRouter(ai_client=ClassifyAI()))

    outgoing = await bot_core.handle_message(
        IncomingMessage(
            peer_id="peer1",
            user_name=None,
            text="подскажи, что поменялось в нормативке за последний месяц",
            interface="console",
        )
    )

    assert "Нормативка" in outgoing.text
    assert news_parser.received_query is not None
    assert news_parser.received_query.date_from == date.today() - timedelta(days=30)


@pytest.mark.asyncio
async def test_limits_request_formats_api_quota():
    class LimitsParser(FakeNewsParser):
        async def fetch_limits(self):
            return [
                {"title": "Информация о документе", "value": 280, "names": ["topic"]},
                {"title": "Экспорт", "value": 12, "names": ["topic/html"]},
            ]

    bot_core = make_bot_core(LimitsParser([]))
    outgoing = await bot_core.handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="остаток запросов", interface="vk")
    )

    assert "Лимиты ГАРАНТ на этот месяц" in outgoing.text
    assert "Информация о документе: 280" in outgoing.text
    assert "Экспорт: 12" in outgoing.text


@pytest.mark.asyncio
async def test_limits_request_without_api_parser_explains():
    bot_core = make_bot_core(FakeNewsParser([]))
    outgoing = await bot_core.handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="лимиты", interface="console")
    )

    assert outgoing.text == LIMITS_UNAVAILABLE_TEXT


@pytest.mark.asyncio
async def test_limits_request_failure_does_not_crash():
    class FailingLimitsParser(FakeNewsParser):
        async def fetch_limits(self):
            raise RuntimeError("сеть")

    bot_core = make_bot_core(FailingLimitsParser([]))
    outgoing = await bot_core.handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="лимиты", interface="vk")
    )

    assert outgoing.text == LIMITS_FAILED_TEXT
