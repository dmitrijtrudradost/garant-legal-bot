import pytest

from core.dialogue_service import DialogueService
from core.history import InMemoryDialogueHistory


class FakeAIClient:
    def __init__(self, reply: str = "ответ ИИ"):
        self.reply = reply
        self.received_messages: list[list[dict]] = []

    async def complete(self, messages):
        self.received_messages.append(messages)
        return self.reply


@pytest.mark.asyncio
async def test_respond_returns_ai_reply_and_updates_history():
    history = InMemoryDialogueHistory()
    ai_client = FakeAIClient(reply="Привет, чем помочь?")
    service = DialogueService(history, ai_client)

    reply = await service.respond("peer1", "Привет")

    assert reply == "Привет, чем помочь?"
    entries = history.get("peer1")
    assert entries[-2].role == "user"
    assert entries[-2].content == "Привет"
    assert entries[-1].role == "assistant"
    assert entries[-1].content == "Привет, чем помочь?"


def test_ensure_started_reports_first_call_only():
    history = InMemoryDialogueHistory()
    service = DialogueService(history, FakeAIClient())

    assert service.ensure_started("peer1") is True
    assert service.ensure_started("peer1") is False
