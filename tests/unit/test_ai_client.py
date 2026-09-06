"""Тесты AIClient — без реальных сетевых обращений.

aiohttp.ClientSession подменяется лёгкой фейковой реализацией вместо
aioresponses (несовместима с текущей версией aiohttp) — этого достаточно,
т.к. AIClient использует только session.post(...).__aenter__/status/json/text.
"""

import json

import pytest

from core import ai_client as ai_client_module
from core.ai_client import AIClient, AIClientError


class FakeResponse:
    def __init__(self, status: int, payload: dict | None = None, text: str = ""):
        self.status = status
        self._payload = payload
        self._text = text

    async def json(self):
        return self._payload

    async def text(self):
        return self._text or json.dumps(self._payload or {})

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class FakeSession:
    def __init__(self, response: FakeResponse):
        self._response = response

    def post(self, *args, **kwargs):
        return self._response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def patch_session(monkeypatch, response: FakeResponse) -> None:
    monkeypatch.setattr(ai_client_module.aiohttp, "ClientSession", lambda: FakeSession(response))


@pytest.mark.asyncio
async def test_complete_returns_assistant_text(monkeypatch, proxyapi_sample_response):
    patch_session(monkeypatch, FakeResponse(200, payload=proxyapi_sample_response))
    client = AIClient(api_key="test-key")

    reply = await client.complete([{"role": "user", "content": "Привет"}])

    assert reply == "Привет! Чем могу помочь?"


@pytest.mark.asyncio
async def test_complete_raises_on_auth_error(monkeypatch):
    patch_session(monkeypatch, FakeResponse(401, text="unauthorized"))
    client = AIClient(api_key="bad-key")

    with pytest.raises(AIClientError) as exc_info:
        await client.complete([{"role": "user", "content": "Привет"}])

    assert "ключ" in exc_info.value.user_message.lower()


@pytest.mark.asyncio
async def test_complete_raises_on_rate_limit(monkeypatch):
    patch_session(monkeypatch, FakeResponse(429, text="too many requests"))
    client = AIClient(api_key="test-key")

    with pytest.raises(AIClientError) as exc_info:
        await client.complete([{"role": "user", "content": "Привет"}])

    assert "минуту" in exc_info.value.user_message.lower()


@pytest.mark.asyncio
async def test_complete_raises_on_generic_error(monkeypatch):
    patch_session(monkeypatch, FakeResponse(500, text="server error"))
    client = AIClient(api_key="test-key")

    with pytest.raises(AIClientError):
        await client.complete([{"role": "user", "content": "Привет"}])
