"""VKInterface — тонкий адаптер vkbottle поверх BotCore.

Никакой бизнес-логики здесь: получение имени пользователя (специфично для VK),
клавиатура-подсказка для новостей ГАРАНТ и пересылка текста в BotCore.handle_message.
Сами тексты кнопок распознаются той же логикой `IntentRouter`, что и обычный
текст — кнопка ничем не отличается от того, если бы пользователь напечатал
её текст руками (см. core/intent_router.py и тесты на эти же лейблы).
"""

from __future__ import annotations

import logging
from typing import Awaitable, Callable

from vkbottle import BaseMiddleware, Keyboard, KeyboardButtonColor, Text, VKAPIError
from vkbottle.bot import Bot, Message

from core.bot_core import BotCore
from core.intent_router import SHOW_MORE_BUTTON_LABEL
from core.models import IncomingMessage
from interfaces.base import BaseInterface

logger = logging.getLogger(__name__)


def _build_news_keyboard() -> str:
    """Постоянная клавиатура-подсказка для новостей ГАРАНТ ПРАЙМ.

    Прикрепляется к каждому ответу бота ("кнопки всегда под рукой"), чтобы
    не нужно было помнить точные триггерные фразы — но обычный текстовый
    диалог по-прежнему работает как раньше, кнопки лишь ускоряют частый сценарий.

    По одной кнопке на строку — на маленьком экране смартфона VK сжимает
    несколько кнопок в ряд и обрезает длинный текст (было видно как
    "Охрана — неде..."); один full-width текст на строку читается целиком.
    Пресеты — только за месяц (самый частый период); недельный/квартальный
    период и произвольные даты — через кнопку "Свой период" текстом.
    «Показать ещё» листает уже полученный список, без нового запроса к ГАРАНТ.
    """
    keyboard = Keyboard(one_time=False, inline=False)

    keyboard.add(Text("🛡 Охрана — месяц"), color=KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("📋 Главные новости — месяц"), color=KeyboardButtonColor.SECONDARY)
    keyboard.row()
    keyboard.add(Text("📅 Свой период"), color=KeyboardButtonColor.SECONDARY)
    keyboard.row()
    keyboard.add(Text(SHOW_MORE_BUTTON_LABEL), color=KeyboardButtonColor.SECONDARY)

    return keyboard.get_json()


NEWS_KEYBOARD = _build_news_keyboard()


async def _send_with_keyboard_fallback(send: Callable[..., Awaitable[object]], text: str) -> None:
    """Отправляет текст с клавиатурой; если у сообщества не включены "Возможности ботов"
    (VK API отвечает ошибкой 912 "This is a chat bot feature, change this status in
    settings"), клавиатура молча отбрасывается VK вместе со всем сообщением — без
    этой подстраховки пользователь не получил бы вообще никакого ответа. Включается
    в настройках сообщества: Управление сообществом → Сообщения → "Возможности ботов".
    """
    try:
        await send(text, keyboard=NEWS_KEYBOARD)
    except VKAPIError as exc:
        logger.error(
            "VKInterface: не удалось отправить клавиатуру (%s) — включите 'Возможности ботов' "
            "в настройках сообщества (Управление → Сообщения). Отправляю ответ без клавиатуры.",
            exc,
        )
        await send(text)


class VKInterface(BaseInterface):
    def __init__(self, bot_core: BotCore, vk_token: str) -> None:
        super().__init__(bot_core)
        self._bot = Bot(token=vk_token)
        self._register_handlers()

    def _register_handlers(self) -> None:
        bot_core = self._bot_core

        class GreetingMiddleware(BaseMiddleware[Message]):
            async def pre(self) -> None:
                peer_id = str(self.event.peer_id)
                if bot_core.is_new_dialogue(peer_id):
                    try:
                        users = await self.event.ctx_api.users.get(self.event.from_id)
                        user_name = users[0].first_name if users else None
                    except Exception as exc:  # noqa: BLE001 - имя не критично для работы бота
                        logger.error("VKInterface: не удалось получить имя пользователя: %s", exc)
                        user_name = None
                    await _send_with_keyboard_fallback(self.event.answer, bot_core.greeting_for(user_name))

        self._bot.labeler.message_view.register_middleware(GreetingMiddleware)

        @self._bot.on.message()
        async def message_handler(message: Message) -> None:
            incoming = IncomingMessage(
                peer_id=str(message.peer_id),
                user_name=None,
                text=message.text,
                interface="vk",
            )
            outgoing = await self._bot_core.handle_message(incoming)
            await _send_with_keyboard_fallback(message.answer, outgoing.text)

    def run(self) -> None:
        self._bot.run()
