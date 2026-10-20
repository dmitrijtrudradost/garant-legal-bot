"""Тесты GarantApiParser — без реальных сетевых обращений.

aiohttp.ClientSession подменяется лёгкой фейковой реализацией (тот же приём,
что и в tests/unit/test_ai_client.py — aioresponses/httpx намеренно не
используются, см. докстроку того файла), расширенной под GET+POST и
последовательность из нескольких HTTP-вызовов за один fetch().
"""

import json
import logging
from datetime import date, timedelta

import pytest

from core.garant import api_client as api_client_module
from core.models import NewsQuery
from core.news import parser_api as parser_api_module
from core.news.parser_api import (
    MAX_CHUNK_DAYS,
    MAX_CHUNKS_PER_FETCH,
    MAX_LOOKBACK_DAYS,
    GarantApiError,
    GarantApiParser,
)


class FakeResponse:
    def __init__(self, status: int, payload: dict | list | None = None, text: str = ""):
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
    """Одна aiohttp.ClientSession — отдаёт следующий ответ из очереди по порядку вызовов."""

    def __init__(self, responses: list[FakeResponse], calls: list[dict]):
        self._responses = responses
        self._calls = calls

    def get(self, url, **kwargs):
        return self._next("GET", url, kwargs)

    def post(self, url, **kwargs):
        return self._next("POST", url, kwargs)

    def _next(self, method: str, url: str, kwargs: dict) -> FakeResponse:
        self._calls.append({"method": method, "url": url, **kwargs})
        return self._responses.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def patch_session(monkeypatch, responses: list[FakeResponse]) -> list[dict]:
    calls: list[dict] = []
    queue = list(responses)
    monkeypatch.setattr(api_client_module.aiohttp, "ClientSession", lambda: FakeSession(queue, calls))
    return calls


def _make_query(
    date_from: date,
    date_to: date,
    topic: list[str] | None = None,
    *,
    territory: str | None = None,
    info_type: list[str] | None = None,
    authority: list[str] | None = None,
    doc_type: list[str] | None = None,
    keywords: str | None = None,
) -> NewsQuery:
    return NewsQuery(
        date_from=date_from,
        date_to=date_to,
        topic=topic,
        territory=territory,
        info_type=info_type,
        authority=authority,
        doc_type=doc_type,
        keywords=keywords,
    )


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Паузы между чанками/повторами (429) не нужны в тестах — ускоряет прогон."""

    async def _sleep(*args, **kwargs):
        return None

    monkeypatch.setattr(parser_api_module.asyncio, "sleep", _sleep)
    monkeypatch.setattr(api_client_module.asyncio, "sleep", _sleep)


# -- fetch(): маппинг и чанкование ---------------------------------------------


@pytest.mark.asyncio
async def test_fetch_single_chunk_maps_response_to_news_items(
    monkeypatch, garant_api_categories_sample, garant_api_news_sample
):
    calls = patch_session(
        monkeypatch,
        [
            FakeResponse(200, payload=garant_api_categories_sample),
            FakeResponse(200, payload=garant_api_news_sample),
        ],
    )
    parser = GarantApiParser(token="test-token")
    query = _make_query(date(2026, 9, 1), date(2026, 9, 8))

    items = await parser.fetch(query)

    assert len(items) == 2
    first = items[0]
    assert "Росгвардии" in first.title
    assert first.url == "https://internet.garant.ru/#/document/414837873"
    assert first.published_at == date(2026, 9, 8)  # вариант 1 (п.4.4 ТЗ) — граница периода запроса

    assert [c["method"] for c in calls] == ["GET", "POST"]


@pytest.mark.asyncio
async def test_fetch_splits_period_over_10_days_into_chunks(monkeypatch, garant_api_categories_sample):
    empty_news = {"news": []}
    responses = [FakeResponse(200, payload=garant_api_categories_sample)] + [
        FakeResponse(200, payload=empty_news) for _ in range(3)
    ]
    calls = patch_session(monkeypatch, responses)
    parser = GarantApiParser(token="test-token")
    query = _make_query(date(2026, 8, 1), date(2026, 8, 25))  # 24 дня -> 3 чанка по MAX_CHUNK_DAYS

    await parser.fetch(query)

    post_calls = [c for c in calls if c["method"] == "POST"]
    assert len(post_calls) == 3
    assert post_calls[0]["json"]["fromDate"] == "2026-08-01"
    assert post_calls[0]["json"]["toDate"] == "2026-08-11"
    assert post_calls[1]["json"]["fromDate"] == "2026-08-12"
    assert post_calls[1]["json"]["toDate"] == "2026-08-22"
    assert post_calls[2]["json"]["fromDate"] == "2026-08-23"
    assert post_calls[2]["json"]["toDate"] == "2026-08-25"


@pytest.mark.asyncio
async def test_fetch_truncates_period_exceeding_max_chunks(monkeypatch, garant_api_categories_sample, caplog):
    date_from = date(2026, 1, 1)
    date_to = date_from + timedelta(days=MAX_CHUNK_DAYS * (MAX_CHUNKS_PER_FETCH + 5))
    empty_news = {"news": []}
    responses = [FakeResponse(200, payload=garant_api_categories_sample)] + [
        FakeResponse(200, payload=empty_news) for _ in range(MAX_CHUNKS_PER_FETCH)
    ]
    calls = patch_session(monkeypatch, responses)
    parser = GarantApiParser(token="test-token")
    query = _make_query(date_from, date_to)

    with caplog.at_level(logging.WARNING):
        await parser.fetch(query)

    post_calls = [c for c in calls if c["method"] == "POST"]
    assert len(post_calls) == MAX_CHUNKS_PER_FETCH
    assert post_calls[-1]["json"]["toDate"] == date_to.isoformat()  # последний чанк доходит до конца периода
    assert any("усечён" in record.message for record in caplog.records)


def test_six_month_period_fits_in_max_chunks():
    parser = GarantApiParser(token="test-token")
    date_to = date(2026, 9, 10)
    date_from = date_to - timedelta(days=180)
    chunks = parser._split_into_chunks(date_from, date_to)

    assert len(chunks) <= MAX_CHUNKS_PER_FETCH
    assert chunks[0][0] == date_from
    assert chunks[-1][1] == date_to


# -- Тема исключает территорию/вид информации (эмпирическое решение, 09.09.2026) -


@pytest.mark.asyncio
async def test_fetch_topic_takes_priority_over_territory(
    monkeypatch, garant_api_categories_branched_sample, garant_api_news_sample, caplog
):
    """Тема и территория заданы одновременно — используется ТОЛЬКО тема,
    один HTTP-вызов, территория не попадает в запрос (см. докстроку
    GarantApiParser, п.2: ни объединение, ни пересечение этой пары осей не
    дают надёжного результата — реальный инцидент 09.09.2026)."""
    calls = patch_session(
        monkeypatch,
        [
            FakeResponse(200, payload=garant_api_categories_branched_sample),
            FakeResponse(200, payload=garant_api_news_sample),
        ],
    )
    parser = GarantApiParser(token="test-token")
    query = _make_query(date(2026, 9, 1), date(2026, 9, 8), topic=["Охранная деятельность"], territory="Москва")

    with caplog.at_level(logging.INFO):
        items = await parser.fetch(query)

    post_calls = [c for c in calls if c["method"] == "POST"]
    assert len(post_calls) == 1  # ровно один вызов — территория не участвует
    assert post_calls[0]["json"]["categories"] == [101]  # только topic ("Сфера интересов")
    assert len(items) == 2


@pytest.mark.asyncio
async def test_fetch_uses_territory_only_when_topic_absent(monkeypatch, garant_api_categories_branched_sample):
    empty_news = {"news": []}
    calls = patch_session(
        monkeypatch,
        [FakeResponse(200, payload=garant_api_categories_branched_sample), FakeResponse(200, payload=empty_news)],
    )
    parser = GarantApiParser(token="test-token")
    query = _make_query(date(2026, 9, 1), date(2026, 9, 8), territory="Москва")  # topic не задан

    await parser.fetch(query)

    post_calls = [c for c in calls if c["method"] == "POST"]
    assert len(post_calls) == 1
    assert post_calls[0]["json"]["categories"] == [142]  # "Вид информации" — territory ("Москва")


# -- Ограничение глубины периода (не старше 1 года) ------------------------------


@pytest.mark.asyncio
async def test_fetch_year_lookback_truncates_date_from(monkeypatch, garant_api_categories_sample, caplog):
    date_to = date.today() - timedelta(days=360)  # в пределах года — не усекается
    date_from = date.today() - timedelta(days=370)  # старше года — усекается до границы; итоговая ширина 5 дней
    empty_news = {"news": []}
    calls = patch_session(
        monkeypatch,
        [FakeResponse(200, payload=garant_api_categories_sample), FakeResponse(200, payload=empty_news)],
    )
    parser = GarantApiParser(token="test-token")
    query = _make_query(date_from, date_to)

    with caplog.at_level(logging.WARNING):
        await parser.fetch(query)

    post_calls = [c for c in calls if c["method"] == "POST"]
    assert len(post_calls) == 1
    expected_from = date.today() - timedelta(days=MAX_LOOKBACK_DAYS)
    assert post_calls[0]["json"]["fromDate"] == expected_from.isoformat()  # усечено до годовой границы
    assert any("год" in record.message for record in caplog.records)  # отдельное сообщение от усечения по чанкам


@pytest.mark.asyncio
async def test_fetch_entire_period_older_than_year_returns_empty_without_api_call(monkeypatch):
    calls = patch_session(monkeypatch, [])  # ни одного ответа в очереди — HTTP не должен вызываться вовсе
    parser = GarantApiParser(token="test-token")
    date_to = date.today() - timedelta(days=380)
    date_from = date_to - timedelta(days=5)
    query = _make_query(date_from, date_to)

    items = await parser.fetch(query)

    assert items == []
    assert calls == []


# -- Неподдерживаемые поля (authority/doc_type/keywords) -------------------------


@pytest.mark.asyncio
async def test_fetch_logs_single_warning_for_unsupported_fields(
    monkeypatch, garant_api_categories_sample, garant_api_news_sample, caplog
):
    patch_session(
        monkeypatch,
        [
            FakeResponse(200, payload=garant_api_categories_sample),
            FakeResponse(200, payload=garant_api_news_sample),
        ],
    )
    parser = GarantApiParser(token="test-token")
    query = _make_query(
        date(2026, 9, 1),
        date(2026, 9, 5),
        authority=["МВД России"],
        doc_type=["Указ"],
        keywords="текст",
    )

    with caplog.at_level(logging.WARNING):
        items = await parser.fetch(query)

    assert len(items) == 2  # работает как обычно, будто этих полей не было
    unsupported_warnings = [r for r in caplog.records if "не поддерживаются" in r.message]
    assert len(unsupported_warnings) == 1  # одно предупреждение на все три поля, не три отдельных
    assert "authority" in unsupported_warnings[0].message
    assert "doc_type" in unsupported_warnings[0].message
    assert "keywords" in unsupported_warnings[0].message


# -- Резолв категорий -----------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_category_ids_matches_topic_by_stem(monkeypatch, garant_api_categories_sample):
    patch_session(monkeypatch, [FakeResponse(200, payload=garant_api_categories_sample)])
    parser = GarantApiParser(token="test-token")

    ids = await parser._resolve_category_ids(["Охранная деятельность"])

    assert ids == [101]


@pytest.mark.asyncio
async def test_resolve_category_ids_unmatched_topic_returns_empty(
    monkeypatch, garant_api_categories_sample, caplog
):
    patch_session(monkeypatch, [FakeResponse(200, payload=garant_api_categories_sample)])
    parser = GarantApiParser(token="test-token")

    with caplog.at_level(logging.WARNING):
        ids = await parser._resolve_category_ids(["Экология и природопользование"])

    assert ids == []
    assert any("не совпала" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_fetch_unmatched_topic_skips_create_news(
    monkeypatch, garant_api_categories_branched_sample, caplog
):
    calls = patch_session(monkeypatch, [FakeResponse(200, payload=garant_api_categories_branched_sample)])
    parser = GarantApiParser(token="test-token")
    query = _make_query(date(2026, 9, 1), date(2026, 9, 5), topic=["астрология"])

    with caplog.at_level(logging.WARNING):
        items = await parser.fetch(query)

    assert items == []
    assert [c["method"] for c in calls] == ["GET"]
    assert any("ленте не выполняется" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_category_tree_is_cached_after_first_call(monkeypatch, garant_api_categories_sample):
    calls = patch_session(
        monkeypatch,
        [
            FakeResponse(200, payload=garant_api_categories_sample),
            FakeResponse(200, payload=garant_api_categories_sample),
        ],
    )
    parser = GarantApiParser(token="test-token")

    await parser._ensure_category_tree()
    await parser._ensure_category_tree()
    assert len([c for c in calls if c["method"] == "GET"]) == 1

    await parser.refresh_category_tree()
    assert len([c for c in calls if c["method"] == "GET"]) == 2


# -- Обработка ошибок и лимитов ---------------------------------------------------


@pytest.mark.parametrize("status", [400, 401, 403, 423])
@pytest.mark.asyncio
async def test_fetch_raises_on_error_codes(monkeypatch, garant_api_categories_sample, caplog, status):
    patch_session(
        monkeypatch,
        [
            FakeResponse(200, payload=garant_api_categories_sample),
            FakeResponse(status, text="ошибка сервера"),
        ],
    )
    parser = GarantApiParser(token="super-secret-token")
    query = _make_query(date(2026, 9, 1), date(2026, 9, 5))

    with caplog.at_level(logging.ERROR):
        with pytest.raises(GarantApiError) as exc_info:
            await parser.fetch(query)

    assert exc_info.value.user_message
    assert "super-secret-token" not in caplog.text  # токен никогда не попадает в лог


@pytest.mark.asyncio
async def test_fetch_handles_404_with_category_fallback(
    monkeypatch, garant_api_categories_sample, garant_api_news_sample, caplog
):
    responses = [
        FakeResponse(200, payload=garant_api_categories_sample),  # GET /v2/prime (резолв категорий)
        FakeResponse(404, text="категория не найдена"),  # первый POST — 404
        FakeResponse(200, payload=garant_api_news_sample),  # повтор POST с корневыми категориями — успех
    ]
    calls = patch_session(monkeypatch, responses)
    parser = GarantApiParser(token="test-token")
    query = _make_query(date(2026, 9, 1), date(2026, 9, 5), topic=["Охранная деятельность"])

    with caplog.at_level(logging.WARNING):
        items = await parser.fetch(query)

    assert len(items) == 2  # не фатально — второй POST с fallback-категориями удался
    post_calls = [c for c in calls if c["method"] == "POST"]
    assert len(post_calls) == 2
    assert post_calls[0]["json"]["categories"] == [101]
    assert post_calls[1]["json"]["categories"] == [101, 102, 103, 201, 202]


@pytest.mark.asyncio
async def test_fetch_retries_once_on_429_then_succeeds(
    monkeypatch, garant_api_categories_sample, garant_api_news_sample
):
    responses = [
        FakeResponse(200, payload=garant_api_categories_sample),
        FakeResponse(429, text="too many requests"),
        FakeResponse(200, payload=garant_api_news_sample),
    ]
    calls = patch_session(monkeypatch, responses)
    parser = GarantApiParser(token="test-token")
    query = _make_query(date(2026, 9, 1), date(2026, 9, 5))

    items = await parser.fetch(query)

    assert len(items) == 2
    assert len([c for c in calls if c["method"] == "POST"]) == 2  # один повтор


@pytest.mark.asyncio
async def test_fetch_raises_after_429_retry_also_fails(monkeypatch, garant_api_categories_sample):
    responses = [
        FakeResponse(200, payload=garant_api_categories_sample),
        FakeResponse(429, text="too many requests"),
        FakeResponse(429, text="still too many requests"),
    ]
    calls = patch_session(monkeypatch, responses)
    parser = GarantApiParser(token="test-token")
    query = _make_query(date(2026, 9, 1), date(2026, 9, 5))

    with pytest.raises(GarantApiError):
        await parser.fetch(query)

    assert len([c for c in calls if c["method"] == "POST"]) == 2  # ровно одна повторная попытка, не бесконечный ретрай


# -- Вариант 2 (точная дата, п. 4.4 ТЗ) — выключен по умолчанию --------------------


@pytest.mark.asyncio
async def test_fetch_exact_date_flag_off_by_default(
    monkeypatch, garant_api_categories_sample, garant_api_news_sample
):
    calls = patch_session(
        monkeypatch,
        [
            FakeResponse(200, payload=garant_api_categories_sample),
            FakeResponse(200, payload=garant_api_news_sample),
        ],
    )
    parser = GarantApiParser(token="test-token")  # fetch_exact_dates не передан -> False
    query = _make_query(date(2026, 9, 1), date(2026, 9, 5))

    await parser.fetch(query)

    assert not any("/v2/topic/" in c["url"] for c in calls)


@pytest.mark.asyncio
async def test_fetch_exact_date_parses_topic_response(monkeypatch):
    patch_session(monkeypatch, [FakeResponse(200, payload={"date": "2026-09-05T00:00:00"})])
    parser = GarantApiParser(token="test-token", fetch_exact_dates=True)

    result = await parser._fetch_exact_date(414837873)

    assert result == date(2026, 9, 5)


@pytest.mark.asyncio
async def test_fetch_exact_date_returns_none_on_malformed_response(monkeypatch):
    patch_session(monkeypatch, [FakeResponse(200, payload={"date": "not-a-date"})])
    parser = GarantApiParser(token="test-token", fetch_exact_dates=True)

    result = await parser._fetch_exact_date(1)

    assert result is None


@pytest.mark.asyncio
async def test_fetch_limits_returns_remaining_calls(monkeypatch):
    payload = [
        {"title": "Информация о документе", "value": 300, "names": ["topic"]},
        {"title": "Экспорт", "value": 30, "names": ["topic/html"]},
    ]
    calls = patch_session(monkeypatch, [FakeResponse(200, payload=payload)])
    parser = GarantApiParser(token="test-token")

    result = await parser.fetch_limits()

    assert result == payload
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"].endswith("/v2/limits")
    assert "Bearer test-token" in calls[0]["headers"]["Authorization"]
