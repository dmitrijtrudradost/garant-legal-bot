"""Интеграционный тест: BotCore + реальный GarantApiParser, HTTP замокан на уровне aiohttp.ClientSession.

В отличие от tests/integration/test_bot_core_news_flow.py (там NewsParser —
полностью фейковый duck-typed класс), здесь проверяется реальная сборка
запроса и разбор ответа GarantApiParser в связке с остальным ядром
(IntentRouter -> NewsQuery -> GarantApiParser.fetch -> NewsFormatter.format).
"""

import json

import pytest

from core.bot_core import BotCore
from core.dialogue_service import DialogueService
from core.history import InMemoryDialogueHistory
from core.intent_router import IntentRouter
from core.models import IncomingMessage
from core.news import parser_api as parser_api_module
from core.news.formatter import NewsFormatter
from core.news.parser_api import GarantApiParser


class FakeAIClient:
    async def complete(self, messages):
        raise AssertionError("Новостной запрос не должен доходить до AIClient")


class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None, text: str = ""):
        self.status = status
        self._payload = payload
        self._text = text

    async def json(self):
        return self._payload

    async def text(self):
        return self._text or json.dumps(self._payload or {})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class FakeSession:
    def __init__(self, responses: list[FakeResponse]):
        self._responses = responses

    def get(self, url, **kwargs):
        return self._responses.pop(0)

    def post(self, url, **kwargs):
        return self._responses.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def make_bot_core(news_parser) -> BotCore:
    return BotCore(
        dialogue_service=DialogueService(InMemoryDialogueHistory(), FakeAIClient()),
        intent_router=IntentRouter(),
        news_parser=news_parser,
        news_formatter=NewsFormatter(),
    )


@pytest.mark.asyncio
async def test_news_request_goes_through_real_garant_api_parser(
    monkeypatch, garant_api_categories_sample, garant_api_news_sample
):
    responses = [
        FakeResponse(200, payload=garant_api_categories_sample),  # GET /v2/prime
        FakeResponse(200, payload=garant_api_news_sample),  # POST /v2/prime/create-news
    ]
    monkeypatch.setattr(parser_api_module.aiohttp, "ClientSession", lambda: FakeSession(responses))

    news_parser = GarantApiParser(token="test-token")
    bot_core = make_bot_core(news_parser)

    # "охран" -> PRESET_SECURITY_ORG (IntentRouter), период по умолчанию (7 дней) -> один чанк API-запроса.
    incoming = IncomingMessage(
        peer_id="peer1", user_name=None, text="Что нового по охране?", interface="console"
    )
    outgoing = await bot_core.handle_message(incoming)

    assert "Росгвардии" in outgoing.text
    assert "https://internet.garant.ru/#/document/414837873" in outgoing.text
