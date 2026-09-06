"""История диалогов: абстракция + in-memory реализация.

`DialogueHistory` — интерфейс, чтобы позже можно было добавить
`PersistentDialogueHistory` (БД/файл) без изменения остального кода
(см. tz/tz-refactoring-core-interfaces-prime-news.md, п. 9).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import DialogueEntry

SYSTEM_PROMPT = "Ты полезный AI-ассистент. Отвечай на русском языке кратко и по существу."

# Сколько последних сообщений (кроме системного) хранить и отправлять модели.
# Простое ограничение по количеству сообщений — оговоренный в ТЗ MVP-подход
# вместо точного подсчёта токенов.
MAX_HISTORY_MESSAGES = 20


class DialogueHistory(ABC):
    """Контракт хранилища истории диалога для одного peer_id."""

    @abstractmethod
    def get(self, peer_id: str) -> list[DialogueEntry]:
        """Вернуть текущую историю (включая системное сообщение), создав её при первом обращении."""

    @abstractmethod
    def add(self, peer_id: str, entry: DialogueEntry) -> None:
        """Добавить сообщение в историю, обрезав её до лимита при необходимости."""

    @abstractmethod
    def exists(self, peer_id: str) -> bool:
        """Есть ли уже история для этого peer_id (используется для логики приветствия)."""


class InMemoryDialogueHistory(DialogueHistory):
    """Хранит историю в оперативной памяти процесса — как в исходном bot.py.

    Ограничение: не переживает перезапуск процесса (это осознанно оставлено
    как известное ограничение, см. README и ТЗ п.9).
    """

    def __init__(self, *, max_messages: int = MAX_HISTORY_MESSAGES) -> None:
        self._max_messages = max_messages
        self._store: dict[str, list[DialogueEntry]] = {}

    def exists(self, peer_id: str) -> bool:
        return peer_id in self._store

    def get(self, peer_id: str) -> list[DialogueEntry]:
        if peer_id not in self._store:
            self._store[peer_id] = [DialogueEntry(role="system", content=SYSTEM_PROMPT)]
        return self._store[peer_id]

    def add(self, peer_id: str, entry: DialogueEntry) -> None:
        history = self.get(peer_id)
        history.append(entry)
        self._trim(peer_id)

    def _trim(self, peer_id: str) -> None:
        history = self._store[peer_id]
        if len(history) <= self._max_messages + 1:  # +1 за системное сообщение
            return
        system_entry = history[0]
        tail = history[-self._max_messages :]
        self._store[peer_id] = [system_entry, *tail]
