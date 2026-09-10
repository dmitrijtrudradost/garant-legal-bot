"""BotCore — единственная точка входа в бизнес-логику ядра.

Используется всеми интерфейсами (VK, консоль, будущие) одинаково:
интерфейс собирает IncomingMessage → BotCore.handle_message → OutgoingMessage.
"""

from __future__ import annotations

import logging

from core.dialogue_service import DialogueService
from core.intent_router import CUSTOM_PERIOD_HELP_TEXT, IntentRouter
from core.models import IncomingMessage, OutgoingMessage
from core.news.formatter import MAX_ITEMS_IN_REPLY, NewsFormatter
from core.news.parser_base import NewsParser
from core.news.results_cache import NewsResultsCache

logger = logging.getLogger(__name__)

GREETING_TEMPLATE = "Привет, {name}! Я AI-бот. Задайте мне вопрос!"
SHOW_MORE_NO_RESULTS_TEXT = "Сначала задайте новостной запрос — тогда будет что листать."
SHOW_MORE_EXHAUSTED_TEXT = "Это были все найденные новости."


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
        if IntentRouter.is_custom_period_help_request(message.text):
            return OutgoingMessage(text=CUSTOM_PERIOD_HELP_TEXT)

        if IntentRouter.is_show_more_request(message.text):
            return self._page_from_cache(message.peer_id)

        news_query = self._intent_router.route(message.text)
        if news_query is None:
            news_query = await self._intent_router.classify_via_ai(message.text)

        if news_query is not None:
            try:
                items = await self._news_parser.fetch(news_query)
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
