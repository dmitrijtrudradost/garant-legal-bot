"""VKInterface — тонкий адаптер vkbottle поверх BotCore.

Никакой бизнес-логики здесь: получение имени пользователя (специфично для VK),
клавиатура-подсказка для новостей ГАРАНТ и пересылка текста в BotCore.handle_message.
Сами тексты кнопок распознаются той же логикой `IntentRouter`, что и обычный
текст — кнопка ничем не отличается от того, если бы пользователь напечатал
её текст руками (см. core/intent_router.py и тесты на эти же лейблы).
Каталог сфер печатается в PDF (VK не принимает HTML) и уходит вложением
документа `doc{owner}_{id}`. Адрес `https://vk.com/doc…` в текст не пишется:
на смартфоне такая ссылка открывает внешнее PDF-приложение и зацикливает
возврат в VK. Первая загрузка на upload-сервер VK иногда отвечает пустым
телом (JSONDecodeError) или `no_free_space` — повторяем попытку и
переиспользуем уже сохранённый документ, чтобы «Справка» не уходила без каталога.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Awaitable, Callable

import aiohttp
from vkbottle import BaseMiddleware, Keyboard, KeyboardButtonColor, Text, VKAPIError
from vkbottle.bot import Bot, Message

from core.bot_core import BotCore
from core.intent_router import SHOW_MORE_BUTTON_LABEL
from core.models import IncomingMessage
from core.news.catalog_html import html_to_pdf
from interfaces.base import BaseInterface

logger = logging.getLogger(__name__)

HELP_BUTTON_LABEL = "Справка"
CATALOG_DOC_TITLE = "Сферы и фильтры ГАРАНТ ПРАЙМ"
CATALOG_DOC_FILENAME = "garant-sfery-i-filtry.pdf"
CATALOG_DOC_CACHE_PATH = Path(__file__).resolve().parents[2] / ".vkbottle" / "catalog_doc.json"
CATALOG_UPLOAD_ATTEMPTS = 3
CATALOG_UPLOAD_RETRY_DELAY_S = 0.6
ATTACHMENT_FAILED_TEXT = "Не удалось прикрепить файл."
_UPLOAD_TIMEOUT = aiohttp.ClientTimeout(total=30)


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


async def _send_with_keyboard_fallback(
    send: Callable[..., Awaitable[object]],
    text: str,
    attachment: str | None = None,
) -> None:
    """Отправляет текст с клавиатурой; если у сообщества не включены "Возможности ботов"
    (VK API отвечает ошибкой 912 "This is a chat bot feature, change this status in
    settings"), клавиатура молча отбрасывается VK вместе со всем сообщением — без
    этой подстраховки пользователь не получил бы вообще никакого ответа. Включается
    в настройках сообщества: Управление сообществом → Сообщения → "Возможности ботов".
    """
    extra: dict[str, str] = {}
    if attachment:
        extra["attachment"] = attachment
    try:
        await send(text, keyboard=NEWS_KEYBOARD, **extra)
    except VKAPIError as exc:
        logger.error(
            "VKInterface: не удалось отправить клавиатуру (%s) — включите 'Возможности ботов' "
            "в настройках сообщества (Управление → Сообщения). Отправляю ответ без клавиатуры.",
            exc,
        )
        await send(text, **extra)


class CatalogUploadError(Exception):
    """Сбой загрузки PDF на upload-сервер VK; обычно имеет смысл повторить."""


def catalog_digest(html: str, pdf_bytes: bytes | None = None) -> str:
    """Ключ кэша по HTML: байты PDF от Chromium каждый раз чуть разные."""
    source = html.encode("utf-8") if (html or "").strip() else (pdf_bytes or b"")
    return hashlib.sha256(source).hexdigest()


def parse_docs_upload_payload(body: str) -> dict | None:
    """JSON с upload-сервера VK. Пустое тело и HTML дают None, не исключение."""
    text = (body or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def catalog_file_token(payload: dict | None) -> str | None:
    if not payload:
        return None
    token = payload.get("file")
    if isinstance(token, str) and token.strip():
        return token.strip()
    return None


def vk_doc_attachment(url: str | None) -> str | None:
    """https://vk.com/doc{owner}_{id} → вложение сообщения doc{owner}_{id}."""
    if not url or not url.startswith("https://vk.com/doc"):
        return None
    return url.removeprefix("https://vk.com/")


def append_doc_attachment(
    text: str, attachment: str | None, url: str | None
) -> tuple[str, str | None]:
    """Добавляет документ к сообщению. Адрес vk.com в текст не попадает."""
    doc = vk_doc_attachment(url)
    if not doc:
        return f"{text}\n\n{ATTACHMENT_FAILED_TEXT}", attachment
    if attachment:
        return text, f"{attachment},{doc}"
    return text, doc


def doc_content_type(filename: str) -> str:
    lowered = filename.lower()
    if lowered.endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if lowered.endswith(".rtf"):
        return "application/rtf"
    if lowered.endswith(".pdf"):
        return "application/pdf"
    if lowered.endswith(".json"):
        return "application/json"
    return "application/octet-stream"


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


def catalog_doc_url_from_items(items: object, title: str) -> str | None:
    """Ищет уже загруженный каталог по заголовку (docs.search / docs.get)."""
    if not items:
        return None
    wanted = title.casefold()
    for item in items:
        if isinstance(item, dict):
            item_title = str(item.get("title") or "")
        else:
            item_title = str(getattr(item, "title", "") or "")
        if item_title.casefold() != wanted:
            continue
        url = catalog_doc_url_from_save(item)
        if url:
            return url
    return None


def load_catalog_doc_cache(path: Path) -> tuple[str, str] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    digest, url = data.get("digest"), data.get("url")
    if isinstance(digest, str) and isinstance(url, str) and url.startswith("https://vk.com/doc"):
        return digest, url
    return None


def save_catalog_doc_cache(path: Path, digest: str, url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"digest": digest, "url": url}, ensure_ascii=False),
        encoding="utf-8",
    )


class VKInterface(BaseInterface):
    _catalog_cache_path = CATALOG_DOC_CACHE_PATH
    _catalog_cache: tuple[str, str] | None = None

    def __init__(self, bot_core: BotCore, vk_token: str) -> None:
        super().__init__(bot_core)
        self._bot = Bot(token=vk_token)
        self._catalog_cache_path = CATALOG_DOC_CACHE_PATH
        self._catalog_cache = load_catalog_doc_cache(self._catalog_cache_path)
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
            attachment = None
            catalog_bytes = outgoing.catalog_pdf
            if catalog_bytes or outgoing.catalog_html:
                url = await self._upload_catalog_doc(
                    message, html=outgoing.catalog_html or "", pdf_bytes=catalog_bytes
                )
                text, attachment = append_doc_attachment(text, attachment, url)
            if outgoing.attachment:
                filename, payload = outgoing.attachment
                url = await self._upload_user_doc(message, filename, payload)
                text, attachment = append_doc_attachment(text, attachment, url)
            await _send_with_keyboard_fallback(message.answer, text, attachment=attachment)

    def _remember_catalog_url(self, digest: str, url: str) -> None:
        self._catalog_cache = (digest, url)
        try:
            save_catalog_doc_cache(self._catalog_cache_path, digest, url)
        except OSError as exc:
            logger.error("VKInterface: не удалось сохранить кэш ссылки на каталог: %s", exc)

    async def _upload_catalog_doc(
        self, message: Message, html: str, pdf_bytes: bytes | None = None
    ) -> str | None:
        digest = catalog_digest(html, pdf_bytes)
        if self._catalog_cache and self._catalog_cache[0] == digest:
            return self._catalog_cache[1]

        last_error: Exception | None = None
        for attempt in range(1, CATALOG_UPLOAD_ATTEMPTS + 1):
            try:
                url = await self._upload_catalog_doc_uncached(message, html, pdf_bytes)
            except Exception as exc:  # noqa: BLE001 - повторяем, справка не должна падать
                last_error = exc
                logger.warning(
                    "VKInterface: загрузка PDF-каталога, попытка %s/%s: %s",
                    attempt,
                    CATALOG_UPLOAD_ATTEMPTS,
                    exc,
                )
                url = None
            if url:
                self._remember_catalog_url(digest, url)
                return url
            if attempt < CATALOG_UPLOAD_ATTEMPTS:
                await asyncio.sleep(CATALOG_UPLOAD_RETRY_DELAY_S)

        existing = await self._find_existing_catalog_doc(message.ctx_api)
        if existing:
            logger.info("VKInterface: повторно использую уже загруженный каталог %s", existing)
            self._remember_catalog_url(digest, existing)
            return existing

        logger.error(
            "VKInterface: не удалось загрузить PDF-каталог в документы VK: %s",
            last_error,
        )
        return None

    async def _find_existing_catalog_doc(self, api) -> str | None:
        try:
            result = await api.docs.search(q=CATALOG_DOC_TITLE, search_own=1, count=20)
        except Exception as exc:  # noqa: BLE001 - запасной путь, не роняем справку
            logger.info("VKInterface: docs.search каталога не удался: %s", exc)
            return None
        items = getattr(result, "items", None)
        if items is None and isinstance(result, dict):
            items = result.get("items")
        return catalog_doc_url_from_items(items, CATALOG_DOC_TITLE)

    async def _upload_catalog_doc_uncached(
        self, message: Message, html: str, pdf_bytes: bytes | None
    ) -> str:
        payload_pdf = pdf_bytes or await html_to_pdf(html)
        return await self._post_doc(
            message,
            payload_pdf,
            filename=CATALOG_DOC_FILENAME,
            content_type="application/pdf",
            title=CATALOG_DOC_TITLE,
        )

    async def _upload_user_doc(self, message: Message, filename: str, payload: bytes) -> str | None:
        """Документ пользователю: тот же upload, что у PDF-каталога, с повтором."""
        title = Path(filename).stem
        last_error: Exception | None = None
        for attempt in range(1, CATALOG_UPLOAD_ATTEMPTS + 1):
            try:
                return await self._post_doc(
                    message,
                    payload,
                    filename=filename,
                    content_type=doc_content_type(filename),
                    title=title,
                )
            except Exception as exc:  # noqa: BLE001 - повтор, вложение не должно ронять ответ
                last_error = exc
                logger.warning(
                    "VKInterface: загрузка файла %s, попытка %s/%s: %s",
                    filename,
                    attempt,
                    CATALOG_UPLOAD_ATTEMPTS,
                    exc,
                )
            if attempt < CATALOG_UPLOAD_ATTEMPTS:
                await asyncio.sleep(CATALOG_UPLOAD_RETRY_DELAY_S)
        logger.error("VKInterface: не удалось прикрепить файл %s: %s", filename, last_error)
        return None

    async def _post_doc(
        self,
        message: Message,
        payload: bytes,
        *,
        filename: str,
        content_type: str,
        title: str,
    ) -> str:
        api = message.ctx_api
        server = await api.docs.get_messages_upload_server(peer_id=message.peer_id, type="doc")
        upload_url = getattr(server, "upload_url", None)
        if not upload_url and isinstance(server, dict):
            upload_url = server.get("upload_url")
        if not upload_url:
            raise CatalogUploadError("docs.getMessagesUploadServer не вернул upload_url")

        form = aiohttp.FormData()
        form.add_field("file", payload, filename=filename, content_type=content_type)
        async with aiohttp.ClientSession(timeout=_UPLOAD_TIMEOUT) as session:
            async with session.post(upload_url, data=form) as response:
                raw = await response.text()
                status = response.status

        uploaded = parse_docs_upload_payload(raw)
        file_token = catalog_file_token(uploaded)
        if not file_token:
            snippet = (raw or "")[:200]
            error = uploaded.get("error") if uploaded else None
            raise CatalogUploadError(f"upload HTTP {status}, error={error!r}, body={snippet!r}")

        saved = await api.docs.save(file=file_token, title=title)
        url = catalog_doc_url_from_save(saved)
        if not url:
            raise CatalogUploadError(f"docs.save не вернул id документа: {saved!r}")
        return url

    def run(self) -> None:
        self._bot.run()
