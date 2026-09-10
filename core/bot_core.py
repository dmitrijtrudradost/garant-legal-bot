"""BotCore — единственная точка входа в бизнес-логику ядра.

Используется всеми интерфейсами (VK, консоль, будущие) одинаково:
интерфейс собирает IncomingMessage → BotCore.handle_message → OutgoingMessage.
"""

from __future__ import annotations

import logging

from core.dialogue_service import DialogueService
from core.intent_router import CUSTOM_PERIOD_HELP_TEXT, IntentRouter
from core.models import IncomingMessage, OutgoingMessage
from core.news.formatter import NewsFormatter
from core.news.parser_base import NewsParser

logger = logging.getLogger(__name__)

GREETING_TEMPLATE = "Привет, {name}! Я AI-бот. Задайте мне вопрос!"


class BotCore:
    def __init__(
        self,
        dialogue_service: DialogueService,
        intent_router: IntentRouter,
        news_parser: NewsParser,
        news_formatter: NewsFormatter,
    ) -> None:
        self._dialogue_service = dialogue_service
        self._intent_router = intent_router
        self._news_parser = news_parser
        self._news_formatter = news_formatter

    def greeting_for(self, user_name: str | None) -> str:
        return GREETING_TEMPLATE.format(name=user_name or "пользователь")

    def is_new_dialogue(self, peer_id: str) -> bool:
        """Нужно ли отправить приветствие перед ответом (первое обращение этого peer_id)."""
        return self._dialogue_service.ensure_started(peer_id)

    async def handle_message(self, message: IncomingMessage) -> OutgoingMessage:
        if IntentRouter.is_custom_period_help_request(message.text):
            return OutgoingMessage(text=CUSTOM_PERIOD_HELP_TEXT)

        news_query = self._intent_router.route(message.text)

        if news_query is not None:
            try:
                items = await self._news_parser.fetch(news_query)
            except Exception as exc:  # noqa: BLE001 - сбой источника не должен ронять бота
                logger.error("BotCore: ошибка получения новостей: %s", exc)
                return OutgoingMessage(
                    text="Извините, сейчас не удалось получить новости. Попробуйте позже."
                )
            return OutgoingMessage(text=self._news_formatter.format(items))

        reply_text = await self._dialogue_service.respond(message.peer_id, message.text)
        return OutgoingMessage(text=reply_text)
