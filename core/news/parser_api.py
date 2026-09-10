"""GarantApiParser — реализация NewsParser через официальный REST API ГАРАНТ Коннект.

Второй (официальный) способ получения новостей ПРАЙМ — альтернатива
headless-браузеру (`parser_browser.py`, вариант Б). Выбор между режимами —
в `core/news/parser_factory.py` (см. ТЗ `tz/tz-garant-api-dual-mode.md`).

Спецификация сверена напрямую с https://www.garant.ru/mobileonline/api/documentation/
и **живым вызовом `GET /v2/prime` 09.09.2026** (см. ТЗ
`tz/tz-garant-news-filtering.md`, раздел 1.1 — обязательная разовая сверка
перед реализацией категорийных фильтров) — реальное дерево категорий
подтвердило структуру и точные названия веток, описанные ниже. Единственное,
что живой вызов подтвердить не смог: `POST /v2/search` (метод «Поиск») —
оба опробованных адреса (`/v2/search`, `/search`) вернули не-JSON-ошибку
(400 CherryPy/404 сайта) — метод «Поиск» и так вне рамок текущей итерации
(см. ТЗ раздел 4), поэтому это не блокирует реализацию, но означает, что
точный адрес/форма v2 этого метода для будущей итерации ещё не определены
и нуждаются в отдельном уточнении.

Решения по неоднозначностям ТЗ (задокументированы здесь, как и решение по
варианту Б задокументировано в `parser_browser.py`):

1. **Резолв тем/территории/вида информации в ID категорий (п. 4.3 ТЗ
   `tz-garant-api-dual-mode.md`, обобщено в п. 3.3 ТЗ `tz-garant-news-filtering.md`).**
   Дерево категорий (`GET /v2/prime`) организовано по двум осям верхнего
   уровня — **подтверждено живым вызовом 09.09.2026, названия точные**:
   `"Вид информации"` (федеральное/региональное законодательство, судебная
   практика; территория, например «г.Москва», лежит вложенно внутри узла
   «Региональное законодательство» этой же ветки — не отдельный параметр
   API) и `"Сфера интересов"` (предметные темы, например «Частная сыскная
   и охранная деятельность», «Налоги»). Резолюция вынесена в отдельный
   переиспользуемый модуль `core/news/category_tree.py` (branch-aware
   обход + сопоставление по основам слов, та же идиома, что в
   `IntentRouter`) — здесь она используется трижды: для `topic` (ветка
   «Сфера интересов»), `territory` и `info_type` (обе — ветка «Вид
   информации», результаты объединяются в один список ID, т.к. это одна
   и та же ось). Если тема не совпала ни с одним узлом — WARNING и fallback
   на корневые ID (только для `topic`: `categories` — обязательное и не
   может быть пустым, 400 на пустой список). `territory`/`info_type` при
   отсутствии совпадений НЕ расширяются до всех категорий — просто не
   участвуют в фильтре (иначе нераспознанный регион расширял бы выдачу
   вместо сужения — см. `_resolve_category_ids_for_query`).

2. **Тема исключает территорию/вид информации — эмпирическое решение,
   отменяющее первоначальный план ТЗ (п. 3.3.4 `tz-garant-news-filtering.md`).**
   Документация ГАРАНТа предупреждает: если в одном вызове `categories`
   смешаны ID из разных осей («Вид информации» + «Сфера интересов»),
   результат — пересечение (AND); для объединения (OR) нужно два отдельных
   вызова. **Первая версия этого класса (09.09.2026) делала именно так —
   объединяла результаты двух вызовов при одновременном использовании
   темы и территории.** Реальное тестирование в тот же день показало, что
   это неудачное решение на практике: ветка «Вид информации» (территория/
   вид информации) — по своей природе широкая (любой документ региона,
   независимо от темы), а «Сфера интересов» (тема) — узкая. При объединении
   широкая ветка растёт с увеличением периода запроса (за неделю — пара
   лишних документов, за месяц-два — уже десятки), и результат тонет в
   нерелевантном региональном шуме, хотя тема технически резолвится верно
   (баг выглядел как «фильтр не работает» — детская хирургия, выборы,
   антикоррупционные комиссии в ответе на запрос про частную охрану).
   Проверено и обратное — **пересечение (один вызов с обоими наборами ID)
   для той же пары тема+территория дало 0 новостей** даже за неделю: у
   ГАРАНТа федеральные по охранной деятельности документы почти никогда не
   помечены одновременно региональным тегом конкретного города. Ни
   объединение, ни пересечение не дают надёжного результата для этой пары
   осей. Итоговое решение: **если задана тема (`topic`) — территория/вид
   информации в API-запрос НЕ попадают вообще**, используется только тема
   (один вызов, как и было до появления этой развилки); территория/вид
   информации применяются как единственный фильтр только когда темы нет
   совсем. Это не полностью реализует "тема + регион" как пользователь мог
   бы ожидать буквально — компромисс осознанный и задокументирован именно
   потому, что оба альтернативных варианта (объединение, пересечение)
   эмпирически хуже (см. `_resolve_category_ids_for_query`).

3. **Дата новости (п. 4.4 ТЗ `tz-garant-api-dual-mode.md`).** Ответ
   `/v2/prime/create-news` не содержит даты ни у новости, ни у документа
   (подтверждено). `NewsFormatter` не меняется в этой итерации, поэтому
   вариант с текстом периода в форматтере не годится. Выбран **вариант 1**:
   `NewsItem.published_at` заполняется правой границей запрошенного периода
   (`query.date_to`, одна и та же для всех новостей одного вызова `fetch()`)
   — читается как "актуально на эту дату", не требует дополнительных
   запросов к API. **Вариант 2** (точная дата через `GET /v2/topic/$topic`
   на каждую новость) реализован как реально рабочий код (`_fetch_exact_date`),
   но включается явным флагом конструктора `fetch_exact_dates` (по умолчанию
   `False`) — выключен по умолчанию, т.к. кратно увеличивает число обращений
   к API и подпадает под отдельный, более строгий лимит (см. п.6 ниже). Не
   подключается через `BotCore` и не тестируется end-to-end в этой итерации.

4. **Два независимых правила глубины/ширины периода (пп. 4.5 `tz-garant-api-dual-mode.md`
   и 3.2 `tz-garant-news-filtering.md`).** ГАРАНТ ограничивает **ширину**
   одного вызова (`toDate - fromDate <= 10` дней, `MAX_CHUNK_DAYS`) И,
   отдельно, **глубину** периода (`fromDate` не может быть раньше, чем
   год назад от сегодня, `MAX_LOOKBACK_DAYS` — подтверждено разделом 1.5 ТЗ
   `tz-garant-news-filtering.md`, ранее в коде отсутствовало как отдельная
   проверка). `fetch()` сначала клэмпит `date_from` к годовой границе (если
   весь период старше года — не делает HTTP-вызовов вообще, возвращает `[]`),
   затем разбивает оставшийся период на интервалы ≤10 дней; если интервалов
   больше `MAX_CHUNKS_PER_FETCH` — берутся последние (ближайшие к сегодня),
   с отдельным WARNING на каждое усечение (тексты различаются, чтобы не
   путать «слишком глубоко» и «слишком много интервалов»).

5. **`document.url` (относительный путь).** Полный адрес получается
   добавлением `https://internet.garant.ru`. В документации есть отдельный
   домен `ivo.garant.ru` для платных документов, определяемый по полю
   `access` в ответе — но в ответе `create-news` поля `access` нет, поэтому
   различить бесплатный/платный документ здесь невозможно, и код всегда
   использует `internet.garant.ru`. Ограничение осознанное, не входит в эту
   итерацию.

6. **Обработка ошибок и лимитов (п. 4.6 `tz-garant-api-dual-mode.md`,
   уточнено разделом 1.5 `tz-garant-news-filtering.md`).** Ни при каком коде
   ошибки процесс бота не должен падать — тот же принцип, что уже применён
   в `AIClient` и `GarantPrimeParser`. Коды 400/401/403 означают "источник
   целиком недоступен для этого запроса" и пробрасываются как `GarantApiError`
   — она долетает до уже существующего `except Exception` в
   `BotCore.handle_message`. Код 404 означает "не та категория" — не
   фатально, один повтор с корневыми категориями. Код 423 (квота исчерпана)
   по уточнённым данным относится не к «Ленте Прайм», а к трём другим
   квотируемым методам — для `GET /v2/topic/$topic` (используется
   `fetch_exact_dates`) это отдельно подтверждённый лимит **300 запросов в
   календарный месяц**, поэтому 423 именно на этом пути получает отдельное,
   более информативное сообщение (см. `_raise_for_status`); общая обработка
   423 на прочих путях остаётся как защитный запасной случай, не как
   документированное поведение `create-news`/`prime`. Код 429 — пауза и одна
   повторная попытка, если и повтор упал — пробрасывается как `GarantApiError`.
   Токен никогда не попадает в лог.

7. **`authority`/`doc_type`/`keywords` не поддерживаются (п. 3.5 ТЗ
   `tz-garant-news-filtering.md`).** У «Ленты Прайм» нет реального параметра
   для органа/типа документа/текстового поиска — единственный подтверждённый
   механизм (операторы `Adopted(...)`/`Type(...)`/параметр `text` метода
   «Поиск») относится к другому, не реализованному в этой итерации методу.
   Если `NewsQuery` приходит с непустыми `authority`/`doc_type`/`keywords` —
   `fetch()` логирует одно WARNING (не по одному на поле) и продолжает как
   если бы их не было (см. `_warn_if_unsupported_fields_set`), не падает и
   не имитирует фильтрацию, которой на самом деле нет.
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from datetime import date, timedelta
from typing import NoReturn

import aiohttp
import certifi

from core.models import NewsItem, NewsQuery
from core.news import category_tree
from core.news.parser_base import NewsParser

logger = logging.getLogger(__name__)

_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

GARANT_API_BASE_URL = "https://api.garant.ru"
GARANT_API_CATEGORIES_PATH = "/v2/prime"
GARANT_API_NEWS_PATH = "/v2/prime/create-news"
GARANT_API_TOPIC_PATH = "/v2/topic"
DOCUMENT_URL_BASE = "https://internet.garant.ru"

MAX_CHUNK_DAYS = 10
"""Жёсткий лимит API: toDate - fromDate не должен превышать это число дней (иначе 400)."""

MAX_CHUNKS_PER_FETCH = 12
"""Верхний предел числа интервалов на один вызов fetch() (≈4 месяца по 10 дней).

Если запрошенный период после разбиения требует больше интервалов — берутся
только последние (ближайшие к сегодняшней дате) MAX_CHUNKS_PER_FETCH, период
считается усечённым, это логируется как WARNING (см. п.4 в докстроке модуля)."""

MAX_LOOKBACK_DAYS = 365
"""Жёсткий лимит API: fromDate не может быть раньше (сегодня − 365 дней) —
иначе 400. Независимое правило от MAX_CHUNK_DAYS (ширина одного вызова) и
MAX_CHUNKS_PER_FETCH (побочный эффект чанкования) — см. п.4 в докстроке модуля."""

RATE_LIMIT_RETRY_DELAY_SECONDS = 1.0
"""Пауза перед единственной повторной попыткой после 429. Консервативное
значение "на глаз" — документация не называет точную цифру лимита для
новостных эндпоинтов, подтверждено только "не более 20 запросов в секунду"
для API в целом."""

INTER_CHUNK_DELAY_SECONDS = 0.2
"""Пауза между последовательными запросами чанков при разбиении периода —
защита от провоцирования 429 самим чанкованием (п.4 в докстроке модуля)."""


class GarantApiError(Exception):
    """Ошибка обращения к API ГАРАНТ (сеть, авторизация, лимиты, прочее).

    `user_message` — текст, безопасный для показа пользователю бота
    (тот же принцип, что и в `AIClientError`, см. `core/ai_client.py`).
    """

    def __init__(self, user_message: str, *, technical_details: str = "") -> None:
        super().__init__(technical_details or user_message)
        self.user_message = user_message


class GarantApiNotFoundError(GarantApiError):
    """404 — конкретная категория (или документ) не найдена.

    Отдельный подкласс, чтобы `_fetch_chunk` мог отличить "эту категорию
    нужно заменить на fallback" от остальных ошибок, которые сразу
    пробрасываются наружу (см. п.6 в докстроке модуля)."""


class GarantApiParser(NewsParser):
    """Парсер новостей ГАРАНТ ПРАЙМ через официальный REST API (см. докстроку модуля)."""

    def __init__(
        self,
        token: str,
        base_url: str = GARANT_API_BASE_URL,
        *,
        fetch_exact_dates: bool = False,
    ) -> None:
        self._token = token
        self._base_url = base_url
        self._fetch_exact_dates = fetch_exact_dates
        self._category_tree: dict | None = None

    async def fetch(self, query: NewsQuery) -> list[NewsItem]:
        self._warn_if_unsupported_fields_set(query)

        date_from = self._apply_year_lookback_limit(query.date_from)
        if date_from > query.date_to:
            logger.warning(
                "GarantApiParser: весь запрошенный период (%s — %s) старше %s дней — "
                "новости за него недоступны по правилам API, HTTP-вызовы не выполняются.",
                query.date_from,
                query.date_to,
                MAX_LOOKBACK_DAYS,
            )
            return []

        category_ids = await self._resolve_category_ids_for_query(query)
        chunks = self._split_into_chunks(date_from, query.date_to)

        raw_news: list[dict] = []
        for index, (chunk_from, chunk_to) in enumerate(chunks):
            if index > 0:
                await asyncio.sleep(INTER_CHUNK_DELAY_SECONDS)
            raw_news.extend(await self._fetch_chunk(category_ids, chunk_from, chunk_to))

        # Дедуп по document.topic — защитная мера на случай, если соседние
        # чанки дат вернут один и тот же документ на границе периода.
        deduped: dict[object, dict] = {}
        order: list[object] = []
        for raw in raw_news:
            key = (raw.get("document") or {}).get("topic")
            key = key if key is not None else id(raw)
            if key not in deduped:
                deduped[key] = raw
                order.append(key)

        return [await self._map_news_item(deduped[key], query) for key in order]

    # -- Неподдерживаемые поля (п.7 докстроки модуля) --------------------

    @staticmethod
    def _warn_if_unsupported_fields_set(query: NewsQuery) -> None:
        unsupported = [
            name
            for name, value in (
                ("authority", query.authority),
                ("doc_type", query.doc_type),
                ("keywords", query.keywords),
            )
            if value
        ]
        if unsupported:
            logger.warning(
                "GarantApiParser: поля %s заданы в запросе, но не поддерживаются методом "
                "«Лента Прайм» — игнорируются (см. tz-garant-news-filtering.md, раздел 1).",
                unsupported,
            )

    # -- Категории ------------------------------------------------------

    async def _resolve_category_ids_for_query(self, query: NewsQuery) -> list[int]:
        """Резолвит итоговый список `categories` для запроса — тема исключает
        территорию/вид информации (п.2 докстроки модуля: эмпирически ни
        объединение, ни пересечение этих двух осей не дают надёжного
        результата — используется только тема, если она задана)."""
        tree = await self._ensure_category_tree()
        categories = tree.get("categories", [])

        if query.topic:
            if query.territory or query.info_type:
                logger.info(
                    "GarantApiParser: тема (%s) задана вместе с территорией/видом информации "
                    "(%r/%r) — используется только тема (см. докстроку модуля, п.2): совместное "
                    "использование этих осей эмпирически даёт бесполезный результат.",
                    query.topic,
                    query.territory,
                    query.info_type,
                )
            return self._resolve_topic_ids(categories, query.topic)

        territory_ids = category_tree.resolve_categories(
            categories,
            [query.territory] if query.territory else [],
            branch=category_tree.BRANCH_INFO_TYPE,
        )
        if query.territory and not territory_ids:
            logger.warning(
                "GarantApiParser: территория %r не совпала ни с одним узлом ветки %r — "
                "фильтр по территории не применяется (не расширяется на все категории).",
                query.territory,
                category_tree.BRANCH_INFO_TYPE,
            )
        info_type_ids = category_tree.resolve_categories(
            categories, query.info_type or [], branch=category_tree.BRANCH_INFO_TYPE
        )
        if query.info_type and not info_type_ids:
            logger.warning(
                "GarantApiParser: вид информации %r не совпал ни с одним узлом ветки %r — "
                "фильтр по виду информации не применяется.",
                query.info_type,
                category_tree.BRANCH_INFO_TYPE,
            )

        info_axis_ids = sorted(set(territory_ids) | set(info_type_ids))
        if info_axis_ids:
            return info_axis_ids

        # Ничего не задано/не резолвилось вообще ни по одному полю — самый
        # широкий фильтр (все корневые категории), т.к. categories не может
        # быть пустым списком в запросе к API.
        return [node["id"] for node in categories]

    async def _resolve_category_ids(self, topics: list[str] | None) -> list[int]:
        """Совместимость: тонкая обёртка над `_resolve_topic_ids` для прямых вызовов
        (используется существующими тестами и как публичный вход для темы)."""
        tree = await self._ensure_category_tree()
        return self._resolve_topic_ids(tree.get("categories", []), topics)

    @staticmethod
    def _resolve_topic_ids(categories: list[dict], topics: list[str] | None) -> list[int]:
        """Сопоставляет темы (`NewsQuery.topic`) с ID ветки «Сфера интересов» (п.1 докстроки модуля).

        В отличие от territory/info_type, у topic сохранён fallback на все
        корневые категории при отсутствии совпадений — историческое поведение
        (`categories` обязателен и не может быть пустым)."""
        root_ids = [node["id"] for node in categories]
        if not topics:
            return root_ids

        matched = category_tree.resolve_categories(categories, topics, branch=category_tree.BRANCH_INTEREST)
        if not matched:
            logger.warning(
                "GarantApiParser: ни одна тема (%s) не совпала с деревом категорий API — "
                "использую все корневые категории (%s) как максимально широкий fallback.",
                topics,
                root_ids,
            )
            return root_ids

        return matched

    async def _ensure_category_tree(self, *, force_refresh: bool = False) -> dict:
        if self._category_tree is None or force_refresh:
            self._category_tree = await self._call_api("GET", GARANT_API_CATEGORIES_PATH)
        return self._category_tree

    async def refresh_category_tree(self) -> dict:
        """Принудительно обновляет кэш дерева категорий (см. п.1 докстроки модуля)."""
        return await self._ensure_category_tree(force_refresh=True)

    # -- Ограничения периода ----------------------------------------------

    @staticmethod
    def _apply_year_lookback_limit(date_from: date) -> date:
        """Клэмпит date_from к (сегодня − MAX_LOOKBACK_DAYS), если нужно (п.4 докстроки модуля)."""
        earliest_allowed = date.today() - timedelta(days=MAX_LOOKBACK_DAYS)
        if date_from >= earliest_allowed:
            return date_from
        logger.warning(
            "GarantApiParser: запрошено с %s (глубже %s дней назад) — усечено до %s "
            "(правило ГАРАНТа: не старше 1 года от текущей даты, см. MAX_LOOKBACK_DAYS).",
            date_from,
            MAX_LOOKBACK_DAYS,
            earliest_allowed,
        )
        return earliest_allowed

    def _split_into_chunks(self, date_from: date, date_to: date) -> list[tuple[date, date]]:
        """Разбивает [date_from, date_to] на интервалы не длиннее MAX_CHUNK_DAYS дней (п.4 докстроки модуля)."""
        chunks: list[tuple[date, date]] = []
        current_from = date_from
        while current_from <= date_to:
            current_to = min(current_from + timedelta(days=MAX_CHUNK_DAYS), date_to)
            chunks.append((current_from, current_to))
            current_from = current_to + timedelta(days=1)

        if len(chunks) > MAX_CHUNKS_PER_FETCH:
            logger.warning(
                "GarantApiParser: период %s — %s требует %s интервалов (лимит %s) — "
                "период усечён до %s последних интервалов, ближайших к %s.",
                date_from,
                date_to,
                len(chunks),
                MAX_CHUNKS_PER_FETCH,
                MAX_CHUNKS_PER_FETCH,
                date_to,
            )
            chunks = chunks[-MAX_CHUNKS_PER_FETCH:]

        return chunks

    # -- HTTP ------------------------------------------------------------

    async def _fetch_chunk(
        self,
        category_ids: list[int],
        date_from: date,
        date_to: date,
        *,
        allow_category_fallback: bool = True,
    ) -> list[dict]:
        body = {
            "categories": category_ids,
            "fromDate": date_from.isoformat(),
            "toDate": date_to.isoformat(),
        }
        try:
            data = await self._call_api("POST", GARANT_API_NEWS_PATH, json_body=body)
        except GarantApiNotFoundError:
            if not allow_category_fallback:
                raise
            tree = await self._ensure_category_tree()
            root_ids = [node["id"] for node in tree.get("categories", [])]
            logger.warning(
                "GarantApiParser: категории %s не найдены (404) для периода %s — %s — "
                "повторяю запрос с корневыми категориями %s.",
                category_ids,
                date_from,
                date_to,
                root_ids,
            )
            return await self._fetch_chunk(root_ids, date_from, date_to, allow_category_fallback=False)

        return data.get("news", [])

    async def _call_api(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        _retry: bool = True,
    ) -> dict:
        """Общий HTTP-вызов к api.garant.ru — заголовки, SSL-контекст, разбор ошибок.

        Токен никогда не попадает в лог (см. п.6 докстроки модуля)."""
        url = f"{self._base_url}{path}"
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        if json_body is not None:
            headers["Content-type"] = "application/json"

        try:
            async with aiohttp.ClientSession() as session:
                request = (
                    session.post(url, json=json_body, headers=headers, ssl=_SSL_CONTEXT)
                    if method == "POST"
                    else session.get(url, headers=headers, ssl=_SSL_CONTEXT)
                )
                async with request as response:
                    if response.status == 200:
                        return await response.json()

                    if response.status == 429 and _retry:
                        logger.warning(
                            "GarantApiParser: 429 на %s — пауза %sс и одна повторная попытка.",
                            path,
                            RATE_LIMIT_RETRY_DELAY_SECONDS,
                        )
                        await asyncio.sleep(RATE_LIMIT_RETRY_DELAY_SECONDS)
                        return await self._call_api(method, path, json_body=json_body, _retry=False)

                    body = await response.text()
                    self._raise_for_status(response.status, path, body)

        except aiohttp.ClientError as exc:
            logger.error("GarantApiParser: сетевая ошибка при обращении к %s: %s", path, exc)
            raise GarantApiError(
                "Извините, не удалось связаться с источником новостей ГАРАНТ (проблема сети). Попробуйте позже.",
                technical_details=str(exc),
            ) from exc

    def _raise_for_status(self, status: int, path: str, body: str) -> NoReturn:
        safe_body = body[:500]  # тело запроса/ответа без токена — заголовки сюда не попадают

        if status == 400:
            logger.error("GarantApiParser: 400 Bad Request на %s: %s", path, safe_body)
            raise GarantApiError(
                "Извините, сейчас не удалось получить новости (некорректный запрос к источнику).",
                technical_details=safe_body,
            )
        if status == 401:
            logger.error("GarantApiParser: 401 Unauthorized на %s — требуется обновить GARANT_TOKEN.", path)
            raise GarantApiError(
                "Извините, источник новостей ГАРАНТ временно недоступен (проблема с доступом).",
                technical_details=safe_body,
            )
        if status == 403:
            logger.error("GarantApiParser: 403 Forbidden на %s: %s", path, safe_body)
            raise GarantApiError(
                "Извините, источник новостей ГАРАНТ недоступен (недостаточно прав/лицензии).",
                technical_details=safe_body,
            )
        if status == 404:
            logger.warning("GarantApiParser: 404 Not Found на %s: %s", path, safe_body)
            raise GarantApiNotFoundError(
                "Извините, сейчас не удалось получить новости по заданной категории.",
                technical_details=safe_body,
            )
        if status == 423:
            if path.startswith(GARANT_API_TOPIC_PATH):
                logger.error(
                    "GarantApiParser: 423 на %s — квота метода «Информация о документе» "
                    "(не более 300 запросов в календарный месяц) исчерпана: %s",
                    path,
                    safe_body,
                )
                raise GarantApiError(
                    "Извините, лимит уточнения точных дат новостей на этот месяц исчерпан "
                    "(не более 300 запросов в календарный месяц) — показаны даты по умолчанию.",
                    technical_details=safe_body,
                )
            logger.error("GarantApiParser: 423 на %s — месячная квота исчерпана: %s", path, safe_body)
            raise GarantApiError(
                "Извините, источник новостей ГАРАНТ временно недоступен "
                "(исчерпана квота запросов до конца месяца).",
                technical_details=safe_body,
            )
        if status == 429:
            # Сюда попадаем, только если повторная попытка в _call_api тоже вернула 429.
            logger.error("GarantApiParser: 429 на %s даже после повторной попытки.", path)
            raise GarantApiError(
                "Извините, источник новостей ГАРАНТ сейчас перегружен запросами. Попробуйте позже.",
                technical_details=safe_body,
            )

        logger.error("GarantApiParser: неожиданный статус %s на %s: %s", status, path, safe_body)
        raise GarantApiError(
            "Извините, сейчас не удалось получить новости. Попробуйте позже.",
            technical_details=safe_body,
        )

    # -- Маппинг в NewsItem ------------------------------------------------

    async def _map_news_item(self, raw: dict, query: NewsQuery) -> NewsItem:
        document = raw.get("document") or {}
        title = raw.get("name") or document.get("name") or ""
        summary = "\n".join(paragraph for paragraph in raw.get("paragraphs") or [] if paragraph)
        relative_url = document.get("url")
        url = f"{DOCUMENT_URL_BASE}{relative_url}" if relative_url else None

        published_at = query.date_to  # вариант 1 (п.3 докстроки модуля) — граница периода запроса
        if self._fetch_exact_dates:
            topic_id = document.get("topic")
            if topic_id is not None:
                exact_date = await self._fetch_exact_date(topic_id)
                if exact_date is not None:
                    published_at = exact_date

        return NewsItem(title=title, summary=summary, published_at=published_at, url=url)

    async def _fetch_exact_date(self, topic_id: int) -> date | None:
        """Точная дата документа через GET /v2/topic/{topic_id} — вариант 2 (п.3 докстроки модуля).

        Вызывается только при `fetch_exact_dates=True`. Любой сбой (сетевой,
        HTTP-ошибка, неожиданная форма ответа) не должен срывать весь fetch() —
        логируется и трактуется как "точная дата недоступна", вызывающий код
        (`_map_news_item`) в этом случае оставляет дату по варианту 1."""
        try:
            data = await self._call_api("GET", f"{GARANT_API_TOPIC_PATH}/{topic_id}")
        except GarantApiError as exc:
            logger.warning("GarantApiParser: не удалось получить точную дату для topic=%s: %s", topic_id, exc)
            return None

        raw_date = data.get("date")
        if not raw_date:
            return None
        try:
            return date.fromisoformat(str(raw_date)[:10])
        except ValueError:
            logger.warning(
                "GarantApiParser: неожиданный формат даты в ответе GET /v2/topic/%s: %r", topic_id, raw_date
            )
            return None
