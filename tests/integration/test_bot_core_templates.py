"""BotCore: список шаблонов, пагинация «ещё» и один документ с вложением."""

from pathlib import Path

import json
import pytest

from core.bot_core import TEMPLATES_UNAVAILABLE_TEXT, BotCore
from core.dialogue_service import DialogueService
from core.history import InMemoryDialogueHistory
from core.intent_router import IntentRouter
from core.models import IncomingMessage, NewsItem
from core.news.formatter import NewsFormatter
from core.news.results_cache import InMemoryNewsResultsCache
from exports.garant_templates.catalog import TemplateRef
from exports.garant_templates.exporter import ExportResult, ExportSummary
from tests.integration.test_bot_core_news_flow import FakeAIClient, FakeNewsParser, make_bot_core


class FakeExporter:
    def __init__(self, tmp_path: Path, count: int = 12):
        self.refs = [TemplateRef(topic=index, title=f"Договор {index}") for index in range(1, count + 1)]
        self.exported: list[int] = []
        self._dir = tmp_path

    async def list_templates(self, catalog_topic: int = 5703683):
        return self.refs

    async def export(self, refs, *, overwrite: bool = False, limit: int | None = None):
        ref = refs[0]
        self.exported.append(ref.topic)
        path = self._dir / f"{ref.topic}_dogovor.docx"
        path.write_bytes(b"PK-docx")
        result = ExportResult(ref.topic, ref.title, "ok", path, "")
        return ExportSummary(1, 0, 0, False, "Скачано: 1, пропущено: 0, ошибок: 0.", [result])


def _core(exporter) -> BotCore:
    return BotCore(
        dialogue_service=DialogueService(InMemoryDialogueHistory(), FakeAIClient()),
        intent_router=IntentRouter(),
        news_parser=FakeNewsParser([]),
        news_formatter=NewsFormatter(),
        results_cache=InMemoryNewsResultsCache(),
        template_exporter=exporter,
    )


@pytest.mark.asyncio
async def test_templates_list_pages_with_show_more(tmp_path):
    bot_core = _core(FakeExporter(tmp_path))

    first = await bot_core.handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="шаблоны договоров", interface="console")
    )
    assert "1. Договор 1" in first.text
    assert "10. Договор 10" in first.text
    assert "11. Договор 11" not in first.text
    assert "\n\nПоказаны 1–10 из 12." in first.text
    assert "➡️ «ещё» — следующая страница" in first.text
    assert "💾 «сохранить» — весь список в файл." in first.text

    second = await bot_core.handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="ещё", interface="console")
    )
    assert "11. Договор 11" in second.text
    assert "12. Договор 12" in second.text
    assert "Показаны все 12." in second.text
    assert "Напишите «шаблон N» или часть названия." in second.text


@pytest.mark.asyncio
async def test_template_one_returns_attachment(tmp_path):
    exporter = FakeExporter(tmp_path, count=3)
    bot_core = _core(exporter)

    outgoing = await bot_core.handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="шаблон 1", interface="vk")
    )

    assert outgoing.attachment is not None
    filename, payload = outgoing.attachment
    assert filename.endswith(".docx")
    assert payload == b"PK-docx"
    assert "Договор 1" in outgoing.text
    assert exporter.exported == [1]
    assert "Файл:" in outgoing.text


@pytest.mark.asyncio
async def test_templates_without_api_exporter():
    bot_core = make_bot_core(FakeNewsParser([]))
    outgoing = await bot_core.handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="шаблоны договоров", interface="console")
    )
    assert outgoing.text == TEMPLATES_UNAVAILABLE_TEXT


@pytest.mark.asyncio
async def test_show_more_returns_to_news_after_news_request(tmp_path):
    class NewsThenTemplates(FakeNewsParser):
        async def fetch(self, query):
            self.received_query = query
            return [NewsItem(title="Новость закона", summary="текст")]

    exporter = FakeExporter(tmp_path, count=12)
    bot_core = BotCore(
        dialogue_service=DialogueService(InMemoryDialogueHistory(), FakeAIClient()),
        intent_router=IntentRouter(),
        news_parser=NewsThenTemplates([]),
        news_formatter=NewsFormatter(),
        results_cache=InMemoryNewsResultsCache(),
        template_exporter=exporter,
    )
    await bot_core.handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="шаблоны договоров", interface="console")
    )
    news = await bot_core.handle_message(
        IncomingMessage(
            peer_id="peer1",
            user_name=None,
            text="Предоставь мне изменения в законодательстве",
            interface="console",
        )
    )
    assert "Новость закона" in news.text
    more = await bot_core.handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="ещё", interface="console")
    )
    assert "Договор 11" not in more.text


@pytest.mark.asyncio
async def test_save_command_writes_template_list_with_links(tmp_path):
    exporter = FakeExporter(tmp_path, count=2)
    exporter.out_dir = tmp_path
    bot_core = _core(exporter)

    outgoing = await bot_core.handle_message(
        IncomingMessage(peer_id="peer1", user_name=None, text="сохранить", interface="console")
    )

    saved = tmp_path / "templates.json"
    assert saved.is_file()
    assert str(saved) in outgoing.text
    assert outgoing.attachment is not None
    filename, payload_bytes = outgoing.attachment
    assert filename == "шаблоны-договоров.json"
    assert payload_bytes == saved.read_bytes()
    assert "💾 Список сохранён" in outgoing.text
    assert "Документов: 2" in outgoing.text
    payload = json.loads(saved.read_text(encoding="utf-8"))
    assert payload["documents"][0]["title"] == "Договор 1"
    assert payload["documents"][0]["url"].endswith("/document/1/entry/0")
    assert payload["documents"][1]["number"] == 2
