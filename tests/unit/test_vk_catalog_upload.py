import json
from types import SimpleNamespace

import pytest

from interfaces.vk import vk_interface
from interfaces.vk.vk_interface import (
    CATALOG_DOC_TITLE,
    VKInterface,
    catalog_digest,
    catalog_doc_url_from_items,
    catalog_file_token,
    load_catalog_doc_cache,
    parse_docs_upload_payload,
    save_catalog_doc_cache,
)


def _iface(tmp_path) -> VKInterface:
    iface = VKInterface.__new__(VKInterface)
    iface._catalog_cache = None
    iface._catalog_cache_path = tmp_path / "catalog_doc.json"
    return iface


class _Msg:
    peer_id = 6559252
    ctx_api = SimpleNamespace()


def test_parse_docs_upload_payload_empty_and_html():
    assert parse_docs_upload_payload("") is None
    assert parse_docs_upload_payload("<html>oops</html>") is None
    assert catalog_file_token(parse_docs_upload_payload('{"file":"tok"}')) == "tok"
    assert catalog_file_token(parse_docs_upload_payload('{"error":"no_free_space"}')) is None


def test_catalog_digest_prefers_html_over_pdf_bytes():
    assert catalog_digest("<html>same</html>", b"pdf-a") == catalog_digest(
        "<html>same</html>", b"pdf-b"
    )
    assert catalog_digest("<html>a</html>") != catalog_digest("<html>b</html>")


def test_catalog_doc_url_from_items_matches_title():
    items = [
        {"title": "Другое", "owner_id": 1, "id": 1},
        {"title": CATALOG_DOC_TITLE, "owner_id": 6559252, "id": 710572897},
    ]
    assert (
        catalog_doc_url_from_items(items, CATALOG_DOC_TITLE)
        == "https://vk.com/doc6559252_710572897"
    )
    assert catalog_doc_url_from_items(items, "нет такого") is None


def test_catalog_doc_cache_roundtrip(tmp_path):
    path = tmp_path / "catalog_doc.json"
    save_catalog_doc_cache(path, "abc", "https://vk.com/doc1_2")
    assert load_catalog_doc_cache(path) == ("abc", "https://vk.com/doc1_2")
    path.write_text("not-json", encoding="utf-8")
    assert load_catalog_doc_cache(path) is None


@pytest.mark.asyncio
async def test_upload_catalog_retries_empty_json_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr(vk_interface, "CATALOG_UPLOAD_RETRY_DELAY_S", 0)
    iface = _iface(tmp_path)
    attempts = {"n": 0}

    async def uncached(message, html, pdf_bytes):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise json.JSONDecodeError("Expecting value", "", 0)
        return "https://vk.com/doc6559252_1"

    iface._upload_catalog_doc_uncached = uncached  # type: ignore[method-assign]
    url = await iface._upload_catalog_doc(_Msg(), html="<html>каталог</html>", pdf_bytes=b"%PDF")
    assert url == "https://vk.com/doc6559252_1"
    assert attempts["n"] == 2
    assert load_catalog_doc_cache(iface._catalog_cache_path)[1] == url


@pytest.mark.asyncio
async def test_upload_catalog_cache_ignores_pdf_byte_differences(tmp_path, monkeypatch):
    monkeypatch.setattr(vk_interface, "CATALOG_UPLOAD_RETRY_DELAY_S", 0)
    iface = _iface(tmp_path)
    calls = {"n": 0}

    async def uncached(message, html, pdf_bytes):
        calls["n"] += 1
        return "https://vk.com/doc1_2"

    iface._upload_catalog_doc_uncached = uncached  # type: ignore[method-assign]
    html = "<html>стабильный каталог</html>"
    first = await iface._upload_catalog_doc(_Msg(), html=html, pdf_bytes=b"pdf-a")
    second = await iface._upload_catalog_doc(_Msg(), html=html, pdf_bytes=b"pdf-b")
    assert first == second == "https://vk.com/doc1_2"
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_upload_catalog_reuses_existing_doc_after_no_free_space(tmp_path, monkeypatch):
    monkeypatch.setattr(vk_interface, "CATALOG_UPLOAD_RETRY_DELAY_S", 0)
    monkeypatch.setattr(vk_interface, "CATALOG_UPLOAD_ATTEMPTS", 2)
    iface = _iface(tmp_path)

    async def uncached(message, html, pdf_bytes):
        raise RuntimeError("no_free_space/var/www/pi")

    async def existing(api):
        return "https://vk.com/doc6559252_710572897"

    iface._upload_catalog_doc_uncached = uncached  # type: ignore[method-assign]
    iface._find_existing_catalog_doc = existing  # type: ignore[method-assign]
    url = await iface._upload_catalog_doc(_Msg(), html="<html>x</html>", pdf_bytes=b"%PDF")
    assert url == "https://vk.com/doc6559252_710572897"
