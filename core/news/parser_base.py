"""NewsParser — контракт источника новостей, не зависящий от способа получения данных.

Вынесен в отдельный файл (см. ТЗ `tz/tz-garant-api-dual-mode.md`, раздел 3),
чтобы к нему можно было добавлять новые реализации (`parser_browser.py`,
`parser_api.py`, `parser_mcp.py`) без риска задеть уже рабочий код —
раньше интерфейс и единственная реализация (`GarantPrimeParser`) лежали
в одном файле `parser.py`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import NewsItem, NewsQuery


class NewsParser(ABC):
    """Контракт источника новостей — не зависит от способа получения данных."""

    @abstractmethod
    async def fetch(self, query: NewsQuery) -> list[NewsItem]:
        """Вернуть список новостей, подходящих под фильтры query."""

    async def get_category_tree(self) -> list[dict] | None:
        """Дерево категорий ГАРАНТ для справки. None, если источник его не отдаёт."""
        return None
