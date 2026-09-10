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
    catalog_html: str | None = None
    """Самодостаточный HTML-каталог сфер и фильтров. Интерфейс сам решает,
    как его доставить (ссылка vk.com/doc, file:// в консоли). None — каталога нет."""
    catalog_pdf: bytes | None = None
    """PDF того же каталога для загрузки в VK и сохранения в docs/."""


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

    `date_from`/`date_to`, `topic`, `territory`, `info_type` резолвятся и
    применяются `GarantApiParser` через единый branch-aware механизм поиска
    по дереву категорий ГАРАНТ (`core/news/category_tree.py`) — `topic` ищется
    в ветке «Сфера интересов», `territory`/`info_type` — в ветке «Вид
    информации» (см. ТЗ tz-garant-news-filtering.md, разделы 1-3.3, и
    докстроку `GarantApiParser`). `GarantPrimeParser` (режим `browser`) эти
    поля пока не применяет вообще (см. TODO в `parser_browser.py`).

    `authority`/`doc_type`/`keywords` — НЕ применяются ни одним из текущих
    парсеров (см. пояснения у каждого поля ниже); поля оставлены в
    датаклассе как задел под будущий метод «Поиск» (`POST /v2/search`),
    вне рамок текущей итерации.
    """

    date_from: date
    date_to: date
    info_type: list[str] | None = None
    """Вид информации (например, "Федеральное законодательство") — узел
    верхнего уровня ветки "Вид информации" дерева категорий. Применяется."""
    authority: list[str] | None = None
    """Орган, принявший документ. НЕ применяется текущими парсерами — метод
    "Лента Прайм" не поддерживает этот фильтр напрямую (реальный механизм —
    оператор Adopted(...) метода "Поиск", вне рамок текущей итерации), см.
    tz-garant-news-filtering.md, раздел 1."""
    doc_type: list[str] | None = None
    """Тип документа. НЕ применяется текущими парсерами — та же причина, что
    и у authority (оператор Type(...) метода "Поиск"), см.
    tz-garant-news-filtering.md, раздел 1."""
    topic: list[str] | None = None
    """Тема/сфера интересов (например, "Частная сыскная и охранная
    деятельность") — узел ветки "Сфера интересов" дерева категорий.
    Применяется; резолюция допускает произвольный текст, не только готовые
    пресеты (см. core/news/presets.py:preset_custom_topic)."""
    territory: str | None = None
    """Территория (например, "Москва") — вложенный узел ветки "Вид
    информации" (например, дочерний у "Региональное законодательство").
    Применяется; при отсутствии совпадения в дереве НЕ расширяется до всех
    категорий (в отличие от topic) — просто не участвует в фильтре."""
    keywords: str | None = None
    """Текстовый поиск. НЕ применяется текущими парсерами — "Лента Прайм" не
    имеет текстового поиска вообще; единственный подтверждённый механизм —
    параметр text метода "Поиск" (вне рамок текущей итерации), см.
    tz-garant-news-filtering.md, раздел 1."""
