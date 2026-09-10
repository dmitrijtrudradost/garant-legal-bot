from datetime import date

from core.models import NewsItem
from core.news.results_cache import InMemoryNewsResultsCache


def _items(count: int) -> list[NewsItem]:
    return [NewsItem(title=f"Новость {i}", summary="текст", published_at=date(2026, 1, 1)) for i in range(count)]


def test_next_page_returns_none_when_nothing_stored():
    cache = InMemoryNewsResultsCache()
    assert cache.next_page("peer1", 10) is None
    assert cache.snapshot("peer1") is None


def test_store_resets_cursor_and_serves_pages():
    cache = InMemoryNewsResultsCache()
    cache.store("peer1", _items(25))

    assert cache.snapshot("peer1") == (0, 25)
    first = cache.next_page("peer1", 10)
    assert [item.title for item in first] == [f"Новость {i}" for i in range(10)]
    assert cache.snapshot("peer1") == (10, 25)

    second = cache.next_page("peer1", 10)
    assert [item.title for item in second] == [f"Новость {i}" for i in range(10, 20)]

    third = cache.next_page("peer1", 10)
    assert [item.title for item in third] == [f"Новость {i}" for i in range(20, 25)]

    assert cache.next_page("peer1", 10) == []
    assert cache.snapshot("peer1") == (25, 25)


def test_store_replaces_previous_results_for_same_peer():
    cache = InMemoryNewsResultsCache()
    cache.store("peer1", _items(15))
    cache.next_page("peer1", 10)
    cache.store("peer1", _items(3))

    assert cache.snapshot("peer1") == (0, 3)
    page = cache.next_page("peer1", 10)
    assert len(page) == 3


def test_peers_are_isolated():
    cache = InMemoryNewsResultsCache()
    cache.store("peer1", _items(2))
    cache.store("peer2", _items(4))

    assert cache.snapshot("peer1") == (0, 2)
    assert cache.snapshot("peer2") == (0, 4)


def test_empty_store_yields_empty_pages():
    cache = InMemoryNewsResultsCache()
    cache.store("peer1", [])
    assert cache.snapshot("peer1") == (0, 0)
    assert cache.next_page("peer1", 10) == []
