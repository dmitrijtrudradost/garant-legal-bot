"""parser_factory — единственное место в проекте, где решается режим новостного модуля.

См. ТЗ `tz/tz-garant-api-dual-mode.md`, раздел 5. `get_news_parser()`
вызывается из точки сборки зависимостей в `main.py` (там же, где раньше
напрямую создавался `GarantPrimeParser`) — `BotCore`/`DialogueService`/
интерфейсы не меняются, они как принимали объект `NewsParser`, так и
принимают, независимо от того, какой конкретный класс за ним стоит.

Режимы (`GARANT_MODE` в `.env`):

- `browser` — `GarantPrimeParser` (нужны `GARANT_LOGIN`+`GARANT_PASSWORD`);
- `api` — `GarantApiParser` (нужен `GARANT_TOKEN`);
- `mcp` — зарезервировано на будущее (см. `parser_mcp.py`), сейчас не работает.

Если `GARANT_MODE` не задан — автоопределение по приоритету (п. 5.2 ТЗ):
1. задан `GARANT_TOKEN` → `api`;
2. иначе заданы оба `GARANT_LOGIN`/`GARANT_PASSWORD` → `browser`;
3. иначе — новостной модуль недоступен (`NullNewsParser`, сохраняет
   сегодняшнее поведение "изменений не найдено").

Если режим задан явно, но данных для него нет (например, `GARANT_MODE=api`
без `GARANT_TOKEN`), либо указан `mcp` — это ошибка конфигурации.
`get_news_parser()` **бросает** `GarantModeConfigError` вместо тихого отката
на другой режим (пользователь явно указал режим — значит ожидает именно
его, а не что-то другое без предупреждения). Решение о том, что делать с
этой ошибкой на уровне процесса — за вызывающим кодом: `main.py` ловит её
один раз в точке сборки зависимостей, громко логирует (`logger.error`) и
подставляет `NullNewsParser`, чтобы сам процесс бота не падал и остальной
функционал (диалог, приветствие) продолжал работать — раскрытие причины
находится в логе, а не тихо проглатывается откатом на другой режим."""

from __future__ import annotations

import logging
import os

from core.models import NewsItem, NewsQuery
from core.news.parser_api import GarantApiParser
from core.news.parser_base import NewsParser
from core.news.parser_browser import DEFAULT_BROWSER_ORIGIN, GarantPrimeParser

logger = logging.getLogger(__name__)


class NullNewsParser(NewsParser):
    """Заглушка "источник не настроен" — сохраняет сегодняшнее поведение.

    `fetch()` всегда возвращает `[]`, что `NewsFormatter` превращает в
    "За указанный период изменений не найдено." Используется, когда ни
    `GARANT_TOKEN`, ни пара `GARANT_LOGIN`+`GARANT_PASSWORD` не заданы, а
    также как безопасный откат при ошибке конфигурации явного режима
    (см. докстроку модуля)."""

    async def fetch(self, query: NewsQuery) -> list[NewsItem]:
        return []


class GarantModeConfigError(Exception):
    """Явно указанный GARANT_MODE не может быть использован: нет нужных
    учётных данных, либо режим ещё не реализован (mcp), либо значение
    не распознано."""


def get_news_parser() -> NewsParser:
    """Собирает и возвращает NewsParser нужного режима — см. докстроку модуля."""
    mode = os.getenv("GARANT_MODE", "").strip().lower() or None
    token = os.getenv("GARANT_TOKEN", "").strip()
    login = os.getenv("GARANT_LOGIN", "").strip()
    password = os.getenv("GARANT_PASSWORD", "").strip()

    if mode == "browser":
        if not (login and password):
            raise GarantModeConfigError(
                "GARANT_MODE=browser указан явно, но GARANT_LOGIN/GARANT_PASSWORD не заданы в .env."
            )
        return _browser_parser(login, password)

    if mode == "api":
        if not token:
            raise GarantModeConfigError("GARANT_MODE=api указан явно, но GARANT_TOKEN не задан в .env.")
        return GarantApiParser(token=token)

    if mode == "mcp":
        raise GarantModeConfigError(
            "GARANT_MODE=mcp: режим ещё не реализован (см. tz/tz-garant-api-dual-mode.md, раздел 6)."
        )

    if mode is not None:
        raise GarantModeConfigError(f"GARANT_MODE={mode!r} — неизвестное значение (ожидается browser/api/mcp).")

    # Автоопределение (GARANT_MODE не задан) — приоритет из п. 5.2 ТЗ.
    if token:
        return GarantApiParser(token=token)
    if login and password:
        return _browser_parser(login, password)

    logger.warning("GARANT_MODE не задан и учётные данные ГАРАНТ отсутствуют — новостной модуль отключён.")
    return NullNewsParser()


def _browser_parser(login: str, password: str) -> GarantPrimeParser:
    origin = os.getenv("GARANT_BROWSER_BASE_URL", "").strip() or DEFAULT_BROWSER_ORIGIN
    return GarantPrimeParser(login=login, password=password, base_url=origin)
