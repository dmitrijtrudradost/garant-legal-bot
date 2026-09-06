"""NewsFormatter — превращает список NewsItem в текст для отправки пользователю."""

from __future__ import annotations

from core.models import NewsItem

MAX_ITEMS_IN_REPLY = 10
EMPTY_RESULT_MESSAGE = "За указанный период изменений не найдено."


class NewsFormatter:
    def format(self, items: list[NewsItem]) -> str:
        if not items:
            return EMPTY_RESULT_MESSAGE

        shown = items[:MAX_ITEMS_IN_REPLY]
        blocks = [self._format_item(item) for item in shown]
        text = "\n\n".join(blocks)

        if len(items) > MAX_ITEMS_IN_REPLY:
            text += f"\n\n(показаны последние {MAX_ITEMS_IN_REPLY} из {len(items)})"

        return text

    @staticmethod
    def _format_item(item: NewsItem) -> str:
        lines = [item.title, item.summary]
        if item.published_at is not None:
            lines.append(item.published_at.strftime("%d.%m.%Y"))
        if item.url:
            lines.append(item.url)
        return "\n".join(lines)
