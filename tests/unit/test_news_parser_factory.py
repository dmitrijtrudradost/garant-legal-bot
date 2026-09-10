"""Тесты parser_factory.get_news_parser() — выбор режима новостного модуля."""

from datetime import date

import pytest

from core.models import NewsQuery
from core.news.parser_api import GarantApiParser
from core.news.parser_browser import GarantPrimeParser
from core.news.parser_factory import GarantModeConfigError, NullNewsParser, get_news_parser


def _clear_env(monkeypatch) -> None:
    for name in ("GARANT_MODE", "GARANT_TOKEN", "GARANT_LOGIN", "GARANT_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


# -- Явный режим ------------------------------------------------------------------


def test_explicit_mode_browser_creates_garant_prime_parser(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("GARANT_MODE", "browser")
    monkeypatch.setenv("GARANT_LOGIN", "login")
    monkeypatch.setenv("GARANT_PASSWORD", "password")

    parser = get_news_parser()

    assert isinstance(parser, GarantPrimeParser)


def test_explicit_mode_api_creates_garant_api_parser(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("GARANT_MODE", "api")
    monkeypatch.setenv("GARANT_TOKEN", "token")

    parser = get_news_parser()

    assert isinstance(parser, GarantApiParser)


def test_explicit_mode_mcp_raises_config_error(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("GARANT_MODE", "mcp")

    with pytest.raises(GarantModeConfigError, match="не реализован"):
        get_news_parser()


def test_explicit_mode_browser_without_credentials_raises(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("GARANT_MODE", "browser")

    with pytest.raises(GarantModeConfigError):
        get_news_parser()


def test_explicit_mode_api_without_token_raises(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("GARANT_MODE", "api")

    with pytest.raises(GarantModeConfigError):
        get_news_parser()


def test_unknown_mode_value_raises(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("GARANT_MODE", "bogus")

    with pytest.raises(GarantModeConfigError):
        get_news_parser()


# -- Автоопределение (GARANT_MODE не задан), приоритет из п. 5.2 ТЗ ---------------


def test_autodetect_prefers_api_when_token_set(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("GARANT_TOKEN", "token")
    monkeypatch.setenv("GARANT_LOGIN", "login")
    monkeypatch.setenv("GARANT_PASSWORD", "password")

    parser = get_news_parser()

    assert isinstance(parser, GarantApiParser)  # токен важнее логина/пароля


def test_autodetect_falls_back_to_browser_when_only_credentials_set(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("GARANT_LOGIN", "login")
    monkeypatch.setenv("GARANT_PASSWORD", "password")

    parser = get_news_parser()

    assert isinstance(parser, GarantPrimeParser)


@pytest.mark.asyncio
async def test_autodetect_returns_null_parser_when_nothing_configured(monkeypatch):
    _clear_env(monkeypatch)

    parser = get_news_parser()

    assert isinstance(parser, NullNewsParser)
    query = NewsQuery(date_from=date(2026, 1, 1), date_to=date(2026, 1, 31))
    assert await parser.fetch(query) == []
