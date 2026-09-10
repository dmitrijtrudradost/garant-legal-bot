"""Кэш полного списка новостей для постраничной выдачи «ещё».

По образцу `core/history.py`: абстракция + in-memory реализация, чтобы позже
можно было заменить хранилище без изменений в `BotCore`. Ключ — `peer_id`,
как у истории диалога: у каждого чата свой курсор и свой список.

`store()` запоминает полный ответ `NewsParser.fetch` и сбрасывает курсор.
`next_page()` отдаёт следующий срез и сдвигает курсор — повторного обращения
к Гаранту нет (важно и для чанков API, и для кулдауна browser-режима).
Кэш живёт в памяти процесса и теряется при перезапуске — то же ограничение,
что у `InMemoryDialogueHistory`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from core.models import NewsItem


class NewsResultsCache(ABC):
    """Контракт хранилища страниц новостей для одного peer_id."""

    @abstractmethod
    def store(self, peer_id: str, items: list[NewsItem]) -> None:
        """Сохранить полный список и сбросить курсор на начало."""

    @abstractmethod
    def next_page(self, peer_id: str, page_size: int) -> list[NewsItem] | None:
        """Следующая страница. None — для peer_id ещё не было запроса;
        пустой список — все уже показаны."""

    @abstractmethod
    def snapshot(self, peer_id: str) -> tuple[int, int] | None:
        """(уже_показано, всего) до сдвига курсора. None — запроса не было."""


@dataclass
class _CacheEntry:
    items: list[NewsItem]
    shown: int = 0


class InMemoryNewsResultsCache(NewsResultsCache):
    """Хранит списки новостей в оперативной памяти процесса."""

    def __init__(self) -> None:
        self._store: dict[str, _CacheEntry] = {}

    def store(self, peer_id: str, items: list[NewsItem]) -> None:
        self._store[peer_id] = _CacheEntry(items=list(items), shown=0)

    def next_page(self, peer_id: str, page_size: int) -> list[NewsItem] | None:
        entry = self._store.get(peer_id)
        if entry is None:
            return None
        page = entry.items[entry.shown : entry.shown + page_size]
        entry.shown += len(page)
        return page

    def snapshot(self, peer_id: str) -> tuple[int, int] | None:
        entry = self._store.get(peer_id)
        if entry is None:
            return None
        return entry.shown, len(entry.items)
