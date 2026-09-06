"""DialogueService — координирует историю диалога и AIClient."""

from __future__ import annotations

from core.ai_client import AIClient, AIClientError
from core.history import DialogueHistory
from core.models import DialogueEntry


class DialogueService:
    """Обычный AI-диалог: добавляет сообщение пользователя в историю,
    запрашивает ответ у AIClient, сохраняет ответ ассистента в историю.
    """

    def __init__(self, history: DialogueHistory, ai_client: AIClient) -> None:
        self._history = history
        self._ai_client = ai_client

    async def respond(self, peer_id: str, user_text: str) -> str:
        self._history.add(peer_id, DialogueEntry(role="user", content=user_text))
        messages = [entry.to_api_message() for entry in self._history.get(peer_id)]

        try:
            reply = await self._ai_client.complete(messages)
        except AIClientError as exc:
            return exc.user_message

        self._history.add(peer_id, DialogueEntry(role="assistant", content=reply))
        return reply

    def ensure_started(self, peer_id: str) -> bool:
        """Инициализировать историю для peer_id, если её ещё нет.

        Возвращает True, если это первое обращение (история только что создана) —
        используется интерфейсами для отправки приветствия.
        """
        is_new = not self._history.exists(peer_id)
        self._history.get(peer_id)
        return is_new
