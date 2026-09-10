"""VKInterface — тонкий адаптер vkbottle поверх BotCore.

Никакой бизнес-логики здесь: получение имени пользователя (специфично для VK),
клавиатура-подсказка для новостей ГАРАНТ и пересылка текста в BotCore.handle_message.
Сами тексты кнопок распознаются той же логикой `IntentRouter`, что и обычный
текст — кнопка ничем не отличается от того, если бы пользователь напечатал
её текст руками (см. core/intent_router.py и тесты на эти же лейблы).
Каталог сфер печатается в PDF (VK не принимает HTML) и загружается как
документ сообщества — в текст справки добавляется ссылка `https://vk.com/doc…`.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Awaitable, Callable

import aiohttp
from vkbottle import BaseMiddleware, Keyboard, KeyboardButtonColor, Text, VKAPIError
from vkbottle.bot import Bot, Message

from core.bot_core import BotCore
from core.intent_router import HELP_CATALOG_LINK_PREFIX, SHOW_MORE_BUTTON_LABEL
from core.models import IncomingMessage
from core.news.catalog_html import html_to_pdf
from interfaces.base import BaseInterface

logger = logging.getLogger(__name__)

HELP_BUTTON_LABEL = "Справка"
CATALOG_DOC_TITLE = "Сферы и фильтры ГАРАНТ ПРАЙМ"
CATALOG_DOC_FILENAME = "garant-sfery-i-filtry.pdf"


def _build_news_keyboard() -> str:
    """Постоянная клавиатура-подсказка для новостей ГАРАНТ ПРАЙМ.

    Прикрепляется к каждому ответу бота ("кнопки всегда под рукой"), чтобы
    не нужно было помнить точные триггерные фразы — но обычный текстовый
    диалог по-прежнему работает как раньше, кнопки лишь ускоряют частый сценарий.

    По одной кнопке на строку — на маленьком экране смартфона VK сжимает
    несколько кнопок в ряд и обрезает длинный текст (было видно как
    "Охрана — неде..."); один full-width текст на строку читается целиком.
    Пресеты — только за месяц (самый частый период); свой период, сферы
    и фильтры — в справке. «Показать ещё» листает уже полученный список,
    без нового запроса к ГАРАНТ.
    """
    keyboard = Keyboard(one_time=False, inline=False)

    keyboard.add(Text("🛡 Охрана — месяц"), color=KeyboardButtonColor.PRIMARY)
    keyboard.row()
    keyboard.add(Text("📋 Главные новости — месяц"), color=KeyboardButtonColor.SECONDARY)
    keyboard.row()
    keyboard.add(Text(SHOW_MORE_BUTTON_LABEL), color=KeyboardButtonColor.SECONDARY)
    keyboard.row()
    keyboard.add(Text(HELP_BUTTON_LABEL), color=KeyboardButtonColor.SECONDARY)

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


def catalog_doc_url_from_save(saved: object) -> str | None:
    """Собирает https://vk.com/doc{owner_id}_{id} из ответа docs.save (модель или dict)."""
    doc = getattr(saved, "doc", None)
    if doc is None and isinstance(saved, (list, tuple)) and saved:
        doc = saved[0]
    if doc is None:
        doc = saved
    if isinstance(doc, dict):
        owner_id, doc_id = doc.get("owner_id"), doc.get("id")
    else:
        owner_id = getattr(doc, "owner_id", None)
        doc_id = getattr(doc, "id", None)
        if owner_id is None and hasattr(doc, "doc"):
            inner = doc.doc
            owner_id = getattr(inner, "owner_id", None)
            doc_id = getattr(inner, "id", None)
    if owner_id is None or doc_id is None:
        return None
    return f"https://vk.com/doc{owner_id}_{doc_id}"


class VKInterface(BaseInterface):
    def __init__(self, bot_core: BotCore, vk_token: str) -> None:
        super().__init__(bot_core)
        self._bot = Bot(token=vk_token)
        self._catalog_cache: tuple[str, str] | None = None
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
            text = outgoing.text
            catalog_bytes = outgoing.catalog_pdf
            if catalog_bytes or outgoing.catalog_html:
                url = await self._upload_catalog_doc(
                    message, html=outgoing.catalog_html or "", pdf_bytes=catalog_bytes
                )
                if url:
                    text = f"{text}\n\n{HELP_CATALOG_LINK_PREFIX}{url}"
            await _send_with_keyboard_fallback(message.answer, text)

    async def _upload_catalog_doc(
        self, message: Message, html: str, pdf_bytes: bytes | None = None
    ) -> str | None:
        digest_src = pdf_bytes if pdf_bytes else html.encode("utf-8")
        digest = hashlib.sha256(digest_src).hexdigest()
        if self._catalog_cache and self._catalog_cache[0] == digest:
            return self._catalog_cache[1]

        try:
            url = await self._upload_catalog_doc_uncached(message, html, pdf_bytes)
        except Exception as exc:  # noqa: BLE001 - справка без ссылки, бот не падает
            logger.error("VKInterface: не удалось загрузить PDF-каталог в документы VK: %s", exc)
            return None

        if url:
            self._catalog_cache = (digest, url)
        return url

    async def _upload_catalog_doc_uncached(
        self, message: Message, html: str, pdf_bytes: bytes | None
    ) -> str | None:
        api = message.ctx_api
        server = await api.docs.get_messages_upload_server(peer_id=message.peer_id, type="doc")
        upload_url = getattr(server, "upload_url", None)
        if not upload_url and isinstance(server, dict):
            upload_url = server.get("upload_url")
        if not upload_url:
            logger.error("VKInterface: docs.getMessagesUploadServer не вернул upload_url")
            return None

        payload_pdf = pdf_bytes or await html_to_pdf(html)
        form = aiohttp.FormData()
        form.add_field(
            "file",
            payload_pdf,
            filename=CATALOG_DOC_FILENAME,
            content_type="application/pdf",
        )
        async with aiohttp.ClientSession() as session:
            async with session.post(upload_url, data=form) as response:
                payload = await response.json(content_type=None)

        file_token = payload.get("file") if isinstance(payload, dict) else None
        if not file_token:
            logger.error("VKInterface: загрузка документа VK не вернула file: %s", payload)
            return None

        saved = await api.docs.save(file=file_token, title=CATALOG_DOC_TITLE)
        return catalog_doc_url_from_save(saved)

    def run(self) -> None:
        self._bot.run()
