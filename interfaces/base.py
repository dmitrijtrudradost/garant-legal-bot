"""BaseInterface — общий контракт для любого транспортного адаптера поверх BotCore.

Каждый интерфейс обязан: получить событие своего транспорта → собрать
IncomingMessage → вызвать BotCore.handle_message → отправить
OutgoingMessage.text обратно пользователю. Интерфейс не должен содержать
бизнес-логику (что делать с текстом) — только транспорт.

Как добавить новый интерфейс — см. interfaces/_future/README.md.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.bot_core import BotCore


class BaseInterface(ABC):
    def __init__(self, bot_core: BotCore) -> None:
        self._bot_core = bot_core

    @abstractmethod
    def run(self) -> None:
        """Запустить интерфейс (может быть блокирующим — polling, REPL и т.п.)."""
