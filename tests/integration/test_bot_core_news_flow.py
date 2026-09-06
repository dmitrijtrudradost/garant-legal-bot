from datetime import date

import pytest

from core.bot_core import BotCore
from core.dialogue_service import DialogueService
from core.history import InMemoryDialogueHistory
from core.intent_router import IntentRouter
from core.models import IncomingMessage, NewsItem
from core.news.formatter import NewsFormatter


class FakeAIClient:
    async def complete(self, messages):
        raise AssertionError("Новостной запрос не должен доходить до AIClient")


class FakeNewsParser:
    def __init__(self, items):
        self._items = items
        self.received_query = None

    async def fetch(self, query):
        self.received_query = query
        return self._items


def make_bot_core(news_parser):
    return BotCore(
        dialogue_service=DialogueService(InMemoryDialogueHistory(), FakeAIClient()),
        intent_router=IntentRouter(),
        news_parser=news_parser,
        news_formatter=NewsFormatter(),
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
async def test_custom_period_button_without_dates_returns_help_instead_of_news_or_dialogue():
    news_parser = FakeNewsParser([])  # не должен быть вызван вовсе
    bot_core = make_bot_core(news_parser)

    incoming = IncomingMessage(peer_id="peer1", user_name=None, text="📅 Свой период", interface="vk")
    outgoing = await bot_core.handle_message(incoming)

    assert "ДД.ММ.ГГГГ-ДД.ММ.ГГГГ" in outgoing.text
    assert news_parser.received_query is None


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
