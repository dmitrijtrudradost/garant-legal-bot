"""BotCore — единственная точка входа в бизнес-логику ядра.

Используется всеми интерфейсами (VK, консоль, будущие) одинаково:
интерфейс собирает IncomingMessage → BotCore.handle_message → OutgoingMessage.
"""

from __future__ import annotations

import logging

from core.dialogue_service import DialogueService
from core.intent_router import (
    HELP_CATALOG_UNAVAILABLE,
    HELP_TEXT,
    IntentRouter,
)
from core.models import IncomingMessage, OutgoingMessage
from core.news.catalog_html import (
    CATALOG_HTML_PATH,
    CATALOG_PDF_PATH,
    html_to_pdf,
    render_catalog_html,
    save_catalog_html,
    save_catalog_pdf,
)
from core.news.formatter import MAX_ITEMS_IN_REPLY, NewsFormatter
from core.news.parser_base import NewsParser, NewsSourceBusyError
from core.news.results_cache import NewsResultsCache

logger = logging.getLogger(__name__)

GREETING_TEMPLATE = "Привет, {name}! Я AI-бот. Задайте мне вопрос!"
SHOW_MORE_NO_RESULTS_TEXT = "Сначала задайте новостной запрос — тогда будет что листать."
SHOW_MORE_EXHAUSTED_TEXT = "Это были все найденные новости."


def _ru_unit(count: int, one: str, few: str, many: str) -> str:
    last_two = abs(count) % 100
    if 11 <= last_two <= 14:
        return many
    last = last_two % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def format_wait_duration(seconds: int) -> str:
    """Человекочитаемое ожидание из `MIN_SECONDS_BETWEEN_LOGINS` (60 → «1 минуту»)."""
    wait = max(int(seconds), 1)
    if wait % 60 == 0:
        minutes = wait // 60
        return f"{minutes} {_ru_unit(minutes, 'минуту', 'минуты', 'минут')}"
    return f"{wait} {_ru_unit(wait, 'секунду', 'секунды', 'секунд')}"


def news_source_busy_text(seconds: int) -> str:
    return (
        "Сайт ГАРАНТ сейчас не пускает повторный вход. "
        f"Подождите {format_wait_duration(seconds)} и повторите запрос."
    )


class BotCore:
    def __init__(
        self,
        dialogue_service: DialogueService,
        intent_router: IntentRouter,
        news_parser: NewsParser,
        news_formatter: NewsFormatter,
        results_cache: NewsResultsCache,
    ) -> None:
        self._dialogue_service = dialogue_service
        self._intent_router = intent_router
        self._news_parser = news_parser
        self._news_formatter = news_formatter
        self._results_cache = results_cache

    def greeting_for(self, user_name: str | None) -> str:
        return GREETING_TEMPLATE.format(name=user_name or "пользователь")

    def is_new_dialogue(self, peer_id: str) -> bool:
        """Нужно ли отправить приветствие перед ответом (первое обращение этого peer_id)."""
        return self._dialogue_service.ensure_started(peer_id)

    async def handle_message(self, message: IncomingMessage) -> OutgoingMessage:
        if IntentRouter.is_help_request(message.text):
            return await self._help_message()

        if IntentRouter.is_show_more_request(message.text):
            return self._page_from_cache(message.peer_id)

        news_query = self._intent_router.route(message.text)
        if news_query is None:
            news_query = await self._intent_router.classify_via_ai(message.text)

        if news_query is not None:
            try:
                items = await self._news_parser.fetch(news_query)
            except NewsSourceBusyError as exc:
                seconds = exc.retry_after_seconds
                if seconds is None:
                    seconds = getattr(self._news_parser, "MIN_SECONDS_BETWEEN_LOGINS", 60)
                return OutgoingMessage(text=news_source_busy_text(seconds))
            except Exception as exc:  # noqa: BLE001 - сбой источника не должен ронять бота
                logger.error("BotCore: ошибка получения новостей: %s", exc)
                return OutgoingMessage(
                    text="Извините, сейчас не удалось получить новости. Попробуйте позже."
                )
            if not items:
                return OutgoingMessage(text=self._news_formatter.format([]))
            self._results_cache.store(message.peer_id, items)
            return self._page_from_cache(message.peer_id)

        reply_text = await self._dialogue_service.respond(message.peer_id, message.text)
        return OutgoingMessage(text=reply_text)

    def _page_from_cache(self, peer_id: str) -> OutgoingMessage:
        snapshot = self._results_cache.snapshot(peer_id)
        if snapshot is None:
            return OutgoingMessage(text=SHOW_MORE_NO_RESULTS_TEXT)

        shown_before, total = snapshot
        page = self._results_cache.next_page(peer_id, MAX_ITEMS_IN_REPLY)
        if not page:
            return OutgoingMessage(text=SHOW_MORE_EXHAUSTED_TEXT)

        return OutgoingMessage(
            text=self._news_formatter.format_page(page, shown_before=shown_before, total=total)
        )

    async def _help_message(self) -> OutgoingMessage:
        categories = None
        getter = getattr(self._news_parser, "get_category_tree", None)
        if callable(getter):
            try:
                categories = await getter()
            except Exception as exc:  # noqa: BLE001 - справка не должна ронять бота
                logger.error("BotCore: не удалось получить дерево категорий для справки: %s", exc)

        if not categories:
            return await self._help_from_saved_catalog()

        html = render_catalog_html(categories)
        try:
            save_catalog_html(html)
        except OSError as exc:
            logger.error("BotCore: не удалось сохранить HTML-каталог в docs/: %s", exc)

        pdf_bytes = None
        try:
            pdf_bytes = await html_to_pdf(html)
            save_catalog_pdf(pdf_bytes)
        except Exception as exc:  # noqa: BLE001 - справка без свежего PDF не должна ронять бота
            logger.error("BotCore: не удалось сгенерировать PDF-каталог: %s", exc)
            pdf_bytes = _read_existing_catalog_pdf()

        return OutgoingMessage(text=HELP_TEXT, catalog_html=html, catalog_pdf=pdf_bytes)

    async def _help_from_saved_catalog(self) -> OutgoingMessage:
        """Каталог без API: уже лежащие HTML/PDF в docs/ (режим browser)."""
        html = _read_existing_catalog_html()
        pdf_bytes = _read_existing_catalog_pdf()
        if html and not pdf_bytes:
            try:
                pdf_bytes = await html_to_pdf(html)
                save_catalog_pdf(pdf_bytes)
            except Exception as exc:  # noqa: BLE001 - без свежего PDF отдаём HTML
                logger.error("BotCore: не удалось напечатать сохранённый каталог в PDF: %s", exc)
        if html or pdf_bytes:
            return OutgoingMessage(text=HELP_TEXT, catalog_html=html, catalog_pdf=pdf_bytes)
        return OutgoingMessage(text=f"{HELP_TEXT}\n\n{HELP_CATALOG_UNAVAILABLE}")


def _read_existing_catalog_html() -> str | None:
    try:
        if CATALOG_HTML_PATH.is_file():
            return CATALOG_HTML_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        logger.error("BotCore: не удалось прочитать HTML-каталог из docs/: %s", exc)
    return None


def _read_existing_catalog_pdf() -> bytes | None:
    try:
        if CATALOG_PDF_PATH.is_file():
            return CATALOG_PDF_PATH.read_bytes()
    except OSError as exc:
        logger.error("BotCore: не удалось прочитать PDF-каталог из docs/: %s", exc)
    return None
