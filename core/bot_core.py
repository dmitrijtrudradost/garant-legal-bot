"""BotCore — единственная точка входа в бизнес-логику ядра.

Используется всеми интерфейсами (VK, консоль, будущие) одинаково:
интерфейс собирает IncomingMessage → BotCore.handle_message → OutgoingMessage.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from core.dialogue_service import DialogueService
from core.intent_router import (
    HELP_CATALOG_UNAVAILABLE,
    HELP_TEXT,
    IntentRouter,
)
from core.models import IncomingMessage, OutgoingMessage
from exports.garant_templates.catalog import TemplateRef, template_page_url
from exports.garant_templates.exporter import ExportSummary, resolve_templates_dir
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
LIMITS_UNAVAILABLE_TEXT = "Лимиты доступны только в режиме api."
LIMITS_FAILED_TEXT = "Извините, сейчас не удалось получить лимиты. Попробуйте позже."
TEMPLATES_UNAVAILABLE_TEXT = "Шаблоны доступны только в режиме api."
TEMPLATES_FAILED_TEXT = "Извините, сейчас не удалось получить шаблоны договоров. Попробуйте позже."
TEMPLATES_NOT_FOUND_TEXT = "Шаблон не найден. Напишите «шаблоны договоров» и выберите номер из списка."
TEMPLATES_EMPTY_TEXT = "В каталоге шаблонов договоров ничего не найдено."
TEMPLATES_EXHAUSTED_TEXT = "Это были все шаблоны договоров."
TEMPLATES_SAVE_NAME = "templates.json"
TEMPLATES_SAVE_VK_NAME = "шаблоны-договоров.json"


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


def format_limits(items: list[dict]) -> str:
    """Список семейств методов и оставшихся вызовов из GET /v2/limits."""
    lines = ["Лимиты ГАРАНТ на этот месяц"]
    for item in items:
        title = item.get("title")
        value = item.get("value")
        if not isinstance(title, str) or not title.strip() or isinstance(value, bool) or not isinstance(value, int):
            continue
        lines.append(f"{title.strip()}: {value}")
    if len(lines) == 1:
        return LIMITS_FAILED_TEXT
    return "\n".join(lines)


class BotCore:
    def __init__(
        self,
        dialogue_service: DialogueService,
        intent_router: IntentRouter,
        news_parser: NewsParser,
        news_formatter: NewsFormatter,
        results_cache: NewsResultsCache,
        template_exporter=None,
    ) -> None:
        self._dialogue_service = dialogue_service
        self._intent_router = intent_router
        self._news_parser = news_parser
        self._news_formatter = news_formatter
        self._results_cache = results_cache
        self._template_exporter = template_exporter
        self._template_refs: dict[str, list[TemplateRef]] = {}
        self._template_shown: dict[str, int] = {}
        self._page_source: dict[str, str] = {}

    def greeting_for(self, user_name: str | None) -> str:
        return GREETING_TEMPLATE.format(name=user_name or "пользователь")

    def is_new_dialogue(self, peer_id: str) -> bool:
        """Нужно ли отправить приветствие перед ответом (первое обращение этого peer_id)."""
        return self._dialogue_service.ensure_started(peer_id)

    async def handle_message(self, message: IncomingMessage) -> OutgoingMessage:
        if IntentRouter.is_help_request(message.text):
            return await self._help_message()

        if IntentRouter.is_limits_request(message.text):
            return await self._limits_message()

        template_command = IntentRouter.template_command(message.text)
        if template_command is not None:
            kind, query = template_command
            if kind == "list":
                return await self._templates_list(message.peer_id)
            if kind == "save":
                return await self._save_templates_list(message.peer_id, message.interface)
            return await self._template_one(message.peer_id, query)

        if IntentRouter.is_show_more_request(message.text):
            if self._page_source.get(message.peer_id) == "templates":
                return self._templates_next_page(message.peer_id)
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
            self._page_source[message.peer_id] = "news"
            return self._page_from_cache(message.peer_id)

        reply_text = await self._dialogue_service.respond(message.peer_id, message.text)
        return OutgoingMessage(text=reply_text)

    async def _limits_message(self) -> OutgoingMessage:
        getter = getattr(self._news_parser, "fetch_limits", None)
        if not callable(getter):
            return OutgoingMessage(text=LIMITS_UNAVAILABLE_TEXT)
        try:
            items = await getter()
        except Exception as exc:  # noqa: BLE001 - сбой квоты не должен ронять бота
            logger.error("BotCore: не удалось получить лимиты ГАРАНТ: %s", exc)
            return OutgoingMessage(text=LIMITS_FAILED_TEXT)
        if not isinstance(items, list):
            return OutgoingMessage(text=LIMITS_FAILED_TEXT)
        return OutgoingMessage(text=format_limits(items))

    async def _templates_list(self, peer_id: str) -> OutgoingMessage:
        if self._template_exporter is None:
            return OutgoingMessage(text=TEMPLATES_UNAVAILABLE_TEXT)
        try:
            refs = await self._template_exporter.list_templates()
        except Exception as exc:  # noqa: BLE001 - сбой каталога не должен ронять бота
            logger.error("BotCore: не удалось получить каталог шаблонов: %s", exc)
            return OutgoingMessage(text=TEMPLATES_FAILED_TEXT)
        if not isinstance(refs, list):
            return OutgoingMessage(text=TEMPLATES_FAILED_TEXT)
        self._template_refs[peer_id] = refs
        self._template_shown[peer_id] = 0
        self._page_source[peer_id] = "templates"
        if not refs:
            return OutgoingMessage(text=TEMPLATES_EMPTY_TEXT)
        return self._templates_next_page(peer_id)

    def _templates_next_page(self, peer_id: str) -> OutgoingMessage:
        refs = self._template_refs.get(peer_id) or []
        shown = self._template_shown.get(peer_id, 0)
        if not refs or shown >= len(refs):
            return OutgoingMessage(text=TEMPLATES_EXHAUSTED_TEXT)
        page = refs[shown : shown + MAX_ITEMS_IN_REPLY]
        self._template_shown[peer_id] = shown + len(page)
        lines = ["Шаблоны договоров ГАРАНТ"]
        for offset, ref in enumerate(page, start=shown + 1):
            lines.append(f"{offset}. {ref.title}")
        end = shown + len(page)
        lines.append("")
        if end < len(refs):
            lines.append(f"Показаны {shown + 1}–{end} из {len(refs)}.")
            lines.append("➡️ «ещё» — следующая страница")
        else:
            lines.append(f"Показаны все {len(refs)}.")
            lines.append("Напишите «шаблон N» или часть названия.")
        lines.append("💾 «сохранить» — весь список в файл.")
        return OutgoingMessage(text="\n".join(lines))

    async def _save_templates_list(self, peer_id: str, interface: str = "vk") -> OutgoingMessage:
        if self._template_exporter is None:
            return OutgoingMessage(text=TEMPLATES_UNAVAILABLE_TEXT)
        refs = await self._ensure_template_refs(peer_id)
        if refs is None:
            return OutgoingMessage(text=TEMPLATES_FAILED_TEXT)
        if not refs:
            return OutgoingMessage(text=TEMPLATES_EMPTY_TEXT)
        out_dir = getattr(self._template_exporter, "out_dir", None)
        if not isinstance(out_dir, Path):
            out_dir = resolve_templates_dir()
        path = _write_templates_json(out_dir, refs)
        text = f"💾 Список сохранён\nДокументов: {len(refs)}"
        if interface == "console":
            text = f"{text}\n{path}"
        return OutgoingMessage(
            text=text,
            attachment=(TEMPLATES_SAVE_VK_NAME, path.read_bytes()),
        )

    async def _ensure_template_refs(self, peer_id: str) -> list[TemplateRef] | None:
        refs = self._template_refs.get(peer_id)
        if refs:
            return refs
        try:
            refs = await self._template_exporter.list_templates()
        except Exception as exc:  # noqa: BLE001
            logger.error("BotCore: не удалось получить каталог шаблонов: %s", exc)
            return None
        if not isinstance(refs, list):
            return None
        self._template_refs[peer_id] = refs
        return refs

    async def _template_one(self, peer_id: str, query: str) -> OutgoingMessage:
        if self._template_exporter is None:
            return OutgoingMessage(text=TEMPLATES_UNAVAILABLE_TEXT)
        refs = await self._ensure_template_refs(peer_id)
        if refs is None:
            return OutgoingMessage(text=TEMPLATES_FAILED_TEXT)
        picked = _pick_template(refs, query)
        if picked is None:
            return OutgoingMessage(text=TEMPLATES_NOT_FOUND_TEXT)
        if isinstance(picked, list):
            lines = ["Найдено несколько шаблонов. Уточните номер:"]
            for ref in picked[:MAX_ITEMS_IN_REPLY]:
                lines.append(f"{refs.index(ref) + 1}. {ref.title}")
            return OutgoingMessage(text="\n".join(lines))
        try:
            summary = await self._template_exporter.export([picked], overwrite=False, limit=1)
        except Exception as exc:  # noqa: BLE001
            logger.error("BotCore: не удалось выгрузить шаблон: %s", exc)
            return OutgoingMessage(text=TEMPLATES_FAILED_TEXT)
        return _outgoing_from_export(summary)

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


def _write_templates_json(out_dir: Path, refs: list[TemplateRef]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "documents": [
            {
                "number": index,
                "topic": ref.topic,
                "title": ref.title,
                "url": template_page_url(ref.topic),
            }
            for index, ref in enumerate(refs, start=1)
        ]
    }
    path = out_dir / TEMPLATES_SAVE_NAME
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _pick_template(refs: list[TemplateRef], query: str) -> TemplateRef | list[TemplateRef] | None:
    if query.isdigit():
        index = int(query)
        if 1 <= index <= len(refs):
            return refs[index - 1]
        return None
    needle = query.casefold()
    matches = [ref for ref in refs if needle in ref.title.casefold()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        return None
    return matches


def _outgoing_from_export(summary: ExportSummary) -> OutgoingMessage:
    if summary.stopped and not summary.results:
        return OutgoingMessage(text=summary.message)
    if not summary.results:
        return OutgoingMessage(text=TEMPLATES_FAILED_TEXT)
    result = summary.results[0]
    if result.path is None or not result.path.is_file():
        return OutgoingMessage(text=result.message or summary.message or TEMPLATES_FAILED_TEXT)
    lines = [result.title]
    if result.message:
        lines.append(result.message)
    lines.append(f"Файл: {result.path}")
    text = "\n".join(lines)
    if summary.stopped:
        text = f"{summary.message}\n\n{text}"
    return OutgoingMessage(text=text, attachment=(result.path.name, result.path.read_bytes()))
