"""NewsFormatter — превращает список NewsItem в текст для отправки пользователю."""

from __future__ import annotations

from core.models import NewsItem

MAX_ITEMS_IN_REPLY = 10
EMPTY_RESULT_MESSAGE = "За указанный период изменений не найдено."


class NewsFormatter:
    def format(self, items: list[NewsItem]) -> str:
        """Первая страница (или пустой ответ). Обрезка — `MAX_ITEMS_IN_REPLY`."""
        if not items:
            return EMPTY_RESULT_MESSAGE
        page = items[:MAX_ITEMS_IN_REPLY]
        return self.format_page(page, shown_before=0, total=len(items))

    def format_page(self, page: list[NewsItem], *, shown_before: int, total: int) -> str:
        """Собрать текст одной страницы с подсказкой «ещё», если хвост ещё есть."""
        if total == 0:
            return EMPTY_RESULT_MESSAGE

        blocks = [self._format_item(item) for item in page]
        text = "\n\n".join(blocks)
        shown_to = shown_before + len(page)

        if shown_to < total:
            text += (
                f"\n\nПоказаны {shown_before + 1}–{shown_to} из {total}. "
                "Напишите «ещё», чтобы увидеть следующие."
            )
        elif total > MAX_ITEMS_IN_REPLY:
            text += f"\n\nПоказаны все {total}."

        return text

    @staticmethod
    def _format_item(item: NewsItem) -> str:
        lines = [item.title, item.summary]
        if item.published_at is not None:
            lines.append(item.published_at.strftime("%d.%m.%Y"))
        if item.url:
            lines.append(item.url)
        return "\n".join(lines)
