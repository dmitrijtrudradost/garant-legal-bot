"""Датаклассы ядра — общие структуры данных, не зависящие от транспорта."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class IncomingMessage:
    """Входящее сообщение от любого интерфейса (VK, консоль, ...)."""

    peer_id: str
    user_name: str | None
    text: str
    interface: str  # "vk" | "console" | будущее


@dataclass
class OutgoingMessage:
    """Ответ ядра, который интерфейс должен показать пользователю."""

    text: str


@dataclass
class DialogueEntry:
    """Одна запись в истории диалога (совместима по смыслу с сообщением ProxyAPI)."""

    role: str  # "system" | "user" | "assistant"
    content: str

    def to_api_message(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class NewsItem:
    """Одна новость/документ из ГАРАНТ ПРАЙМ в унифицированном виде."""

    title: str
    summary: str
    published_at: date | None = None
    url: str | None = None


@dataclass
class NewsQuery:
    """Параметры запроса новостей ГАРАНТ ПРАЙМ.

    Семантика полей соответствует фильтрам сайта demo.garant.ru (см. ТЗ,
    раздел 3.2): дата документа, вид информации, орган, тип, тема, территория.
    """

    date_from: date
    date_to: date
    info_type: list[str] | None = None
    authority: list[str] | None = None
    doc_type: list[str] | None = None
    topic: list[str] | None = None
    territory: str | None = None
    keywords: str | None = None
