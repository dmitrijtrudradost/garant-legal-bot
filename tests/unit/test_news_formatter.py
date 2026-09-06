from datetime import date

from core.models import NewsItem
from core.news.formatter import EMPTY_RESULT_MESSAGE, MAX_ITEMS_IN_REPLY, NewsFormatter

formatter = NewsFormatter()


def test_format_empty_list_returns_placeholder_message():
    assert formatter.format([]) == EMPTY_RESULT_MESSAGE


def test_format_single_item_contains_all_fields():
    item = NewsItem(
        title="Заголовок",
        summary="Описание новости",
        published_at=date(2026, 1, 1),
        url="https://example.com/doc",
    )
    text = formatter.format([item])

    assert "Заголовок" in text
    assert "Описание новости" in text
    assert "01.01.2026" in text
    assert "https://example.com/doc" in text


def test_format_limits_number_of_items_shown():
    items = [NewsItem(title=f"Новость {i}", summary="текст") for i in range(15)]
    text = formatter.format(items)

    assert f"показаны последние {MAX_ITEMS_IN_REPLY} из 15" in text
    assert "Новость 14" not in text  # за пределами лимита
    assert "Новость 0" in text
