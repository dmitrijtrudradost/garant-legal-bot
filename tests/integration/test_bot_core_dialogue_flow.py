import pytest

from core.bot_core import BotCore
from core.dialogue_service import DialogueService
from core.history import InMemoryDialogueHistory
from core.intent_router import IntentRouter
from core.models import IncomingMessage
from core.news.formatter import NewsFormatter
from core.news.results_cache import InMemoryNewsResultsCache


class FakeAIClient:
    async def complete(self, messages):
        return "Здравствуйте, чем могу помочь?"


class FakeNewsParser:
    async def fetch(self, query):
        return []


@pytest.mark.asyncio
async def test_regular_message_goes_through_dialogue_service():
    bot_core = BotCore(
        dialogue_service=DialogueService(InMemoryDialogueHistory(), FakeAIClient()),
        intent_router=IntentRouter(),
        news_parser=FakeNewsParser(),
        news_formatter=NewsFormatter(),
        results_cache=InMemoryNewsResultsCache(),
    )

    incoming = IncomingMessage(peer_id="peer1", user_name="Иван", text="Привет, как дела?", interface="console")
    outgoing = await bot_core.handle_message(incoming)

    assert outgoing.text == "Здравствуйте, чем могу помочь?"


def test_greeting_uses_user_name_or_fallback():
    bot_core = BotCore(
        dialogue_service=DialogueService(InMemoryDialogueHistory(), FakeAIClient()),
        intent_router=IntentRouter(),
        news_parser=FakeNewsParser(),
        news_formatter=NewsFormatter(),
        results_cache=InMemoryNewsResultsCache(),
    )

    assert "Иван" in bot_core.greeting_for("Иван")
    assert "пользователь" in bot_core.greeting_for(None)
