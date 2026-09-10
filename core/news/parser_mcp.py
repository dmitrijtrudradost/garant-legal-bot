"""GarantMcpParser — архитектурная заготовка под режим MCP (mcp.garant.ru).

**Не реализовано в этой итерации** — только каркас класса, удовлетворяющий
интерфейсу `NewsParser`, чтобы `GARANT_MODE=mcp` было допустимым (но пока
нерабочим) значением (см. ТЗ `tz/tz-garant-api-dual-mode.md`, раздел 6).

Что известно про `mcp.garant.ru` (сверено с
https://www.garant.ru/mobileonline/api/documentation/, секция «MCP API»):
сервис реализует MCP-обёртку над теми же REST-эндпоинтами `api.garant.ru`
("mcp.garant.ru является оборачиванием существующего API, а не отдельным
сервисом"), с теми же новостными инструментами:

- `garant_prime_categories` → `GET /v2/prime`
- `garant_prime_news` → `POST /v2/prime/create-news`

и той же авторизацией — Bearer-токен API в заголовке `Authorization`,
тот же, что уже используется в `GarantApiParser` (`GARANT_TOKEN`).

Будущая реализация должна расширить именно этот файл (добавить MCP-клиента,
логику `fetch()`), не трогая `parser_base.py`/`parser_browser.py`/
`parser_api.py` и не меняя остальной код ядра — ровно так, как задумано
архитектурой интерфейса `NewsParser`.
"""

from __future__ import annotations

from core.models import NewsItem, NewsQuery
from core.news.parser_base import NewsParser


class GarantMcpParser(NewsParser):
    """Заглушка режима MCP — см. докстроку модуля и ТЗ раздел 6."""

    async def fetch(self, query: NewsQuery) -> list[NewsItem]:
        raise NotImplementedError(
            "Режим GARANT_MODE=mcp ещё не реализован — см. "
            "tz/tz-garant-api-dual-mode.md, раздел 6, и "
            "https://www.garant.ru/mobileonline/api/documentation/, секция «MCP API»."
        )
