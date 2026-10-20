"""Шаблоны договоров: разбор каталога, экспорт и конвертация RTF без сети."""

import json
from pathlib import Path

import pytest

from core.garant.api_client import GarantApiError
from exports.garant_templates import catalog as catalog_module
from exports.garant_templates import converter as converter_module
from exports.garant_templates import exporter as exporter_module
from exports.garant_templates.catalog import parse_template_links, safe_filename
from exports.garant_templates.converter import RtfToDocxConverter
from exports.garant_templates.exporter import GarantTemplateExporter


@pytest.fixture
def catalog_items():
    payload = json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures" / "garant_api_templates_catalog_html.json").read_text(
            encoding="utf-8"
        )
    )
    return payload["items"]


def test_parse_template_links_unique_without_catalog(catalog_items):
    refs = parse_template_links(catalog_items)

    assert [(ref.topic, ref.title) for ref in refs] == [
        (10164072, "Договор аренды"),
        (55748742, "Договор подряда"),
        (1969937, "Договор поставки"),
    ]


def test_safe_filename_strips_forbidden_characters_and_truncates():
    name = safe_filename(10, 'Договор <аренды>: "офис"/склад?', ".docx")
    assert name.startswith("10_")
    assert all(char not in name for char in '<>:"/\\|?*')
    assert name.endswith(".docx")

    long_name = safe_filename(10, "я" * 200, ".docx")
    stem = long_name[: -len(".docx")]
    assert len(stem) <= 120


class FakeClient:
    def __init__(self):
        self.topics: dict[int, dict] = {}
        self.downloads: dict[int, bytes] = {}
        self.errors: dict[str, Exception] = {}
        self.calls: list[str] = []

    async def get_json(self, path: str, *, scope: str = "document"):
        self.calls.append(path)
        if path in self.errors:
            raise self.errors[path]
        topic = int(path.rstrip("/").split("/")[-1])
        return self.topics[topic]

    async def get_bytes(self, path: str, *, scope: str = "document"):
        self.calls.append(path)
        if path in self.errors:
            raise self.errors[path]
        topic = int(path.rstrip("/").split("/")[-2])
        return self.downloads[topic]


class FakeConverter:
    async def convert(self, rtf_path: Path) -> Path:
        docx = rtf_path.with_suffix(".docx")
        docx.write_bytes(b"PK" + rtf_path.read_bytes())
        rtf_path.unlink()
        return docx


def _ref(topic: int, title: str):
    return catalog_module.TemplateRef(topic=topic, title=title)


@pytest.fixture
def no_export_sleep(monkeypatch):
    async def _sleep(*args, **kwargs):
        return None

    monkeypatch.setattr(exporter_module.asyncio, "sleep", _sleep)


@pytest.mark.asyncio
async def test_export_writes_docx_and_manifest(tmp_path, no_export_sleep):
    client = FakeClient()
    client.topics[101] = {"access": "ACCESS_IS_FREE", "last_modified": "01.10.2026"}
    client.downloads[101] = b"{\\rtf1 hello}"
    exporter = GarantTemplateExporter(client, tmp_path, FakeConverter())

    summary = await exporter.export([_ref(101, "Аренда")])

    assert summary.downloaded == 1
    assert summary.results[0].path is not None
    assert summary.results[0].path.suffix == ".docx"
    assert summary.results[0].path.read_bytes().startswith(b"PK")
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["templates"]["101"]["status"] == "ok"
    assert manifest["templates"]["101"]["last_modified"] == "01.10.2026"


@pytest.mark.asyncio
async def test_export_skips_forbidden_and_stops_on_quota(tmp_path, no_export_sleep):
    client = FakeClient()
    client.errors["/v2/topic/1"] = GarantApiError("Нет доступа по лицензии.", status=403)
    client.errors["/v2/topic/2"] = GarantApiError("Квота исчерпана.", status=423)
    client.topics[3] = {"access": "ACCESS_IS_FREE", "last_modified": "01.10.2026"}
    client.downloads[3] = b"{\\rtf1 later}"
    exporter = GarantTemplateExporter(client, tmp_path, FakeConverter())

    summary = await exporter.export([_ref(1, "Платный"), _ref(2, "Дальше"), _ref(3, "После квоты")])

    assert summary.stopped is True
    assert summary.skipped == 1
    assert [result.topic for result in summary.results] == [1]
    assert "/v2/topic/3/download" not in client.calls
    assert "квота" in summary.message.lower() or "Квота" in summary.message


@pytest.mark.asyncio
async def test_export_skips_existing_file_with_same_modified(tmp_path, no_export_sleep):
    client = FakeClient()
    client.topics[101] = {"access": "ACCESS_IS_FREE", "last_modified": "01.10.2026"}
    client.downloads[101] = b"{\\rtf1 hello}"
    exporter = GarantTemplateExporter(client, tmp_path, FakeConverter())
    await exporter.export([_ref(101, "Аренда")])
    calls_after_first = len(client.calls)

    again = GarantTemplateExporter(client, tmp_path, FakeConverter())
    summary = await again.export([_ref(101, "Аренда")])

    assert summary.skipped == 1
    assert summary.downloaded == 0
    assert summary.results[0].path is not None
    assert not any(call.endswith("/download") for call in client.calls[calls_after_first:])


@pytest.mark.asyncio
async def test_export_skips_paid_access_without_download(tmp_path, no_export_sleep):
    client = FakeClient()
    client.topics[7] = {"access": "ACCESS_BY_MONEY", "last_modified": "01.10.2026"}
    client.downloads[7] = b"{\\rtf1 secret}"
    exporter = GarantTemplateExporter(client, tmp_path, FakeConverter())

    summary = await exporter.export([_ref(7, "Платный")])

    assert summary.skipped == 1
    assert not any(call.endswith("/download") for call in client.calls)
    assert "лиценз" in summary.results[0].message.lower()


@pytest.mark.asyncio
async def test_converter_without_soffice_keeps_rtf(tmp_path, monkeypatch):
    monkeypatch.setattr(RtfToDocxConverter, "resolve_soffice", lambda self: None)
    rtf = tmp_path / "doc.rtf"
    rtf.write_bytes(b"{\\rtf1}")

    delivered = await RtfToDocxConverter().convert(rtf)

    assert delivered == rtf
    assert rtf.is_file()


@pytest.mark.asyncio
async def test_converter_calls_soffice_and_drops_rtf(tmp_path, monkeypatch):
    rtf = tmp_path / "doc.rtf"
    rtf.write_bytes(b"{\\rtf1}")

    class FakeProc:
        returncode = 0

        async def communicate(self):
            rtf.with_suffix(".docx").write_bytes(b"PK")
            return b"", b""

    async def fake_exec(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(RtfToDocxConverter, "resolve_soffice", lambda self: "soffice")
    monkeypatch.setattr(converter_module.asyncio, "create_subprocess_exec", fake_exec)

    delivered = await RtfToDocxConverter().convert(rtf)

    assert delivered.suffix == ".docx"
    assert delivered.read_bytes() == b"PK"
    assert not rtf.exists()
