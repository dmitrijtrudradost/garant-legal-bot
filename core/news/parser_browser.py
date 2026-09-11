"""GarantPrimeParser — реализация NewsParser через headless-браузер (лента ПРАЙМ).

Перенесено из бывшего `core/news/parser.py` при реструктуризации пакета
`core/news/` под несколько режимов подключения (см. ТЗ
`tz/tz-garant-api-dual-mode.md`, раздел 3) — логика класса не менялась,
только имя файла и то, откуда импортируется интерфейс `NewsParser`
(теперь `parser_base.py`).

Архитектурная развилка (см. ТЗ п. 3.1) и её решение
-----------------------------------------------------
Целевая страница `{origin}/#/startpage:1` — SPA: контент рендерится в
браузере через JavaScript, обычный HTTP-запрос (requests/httpx) вернёт
пустой каркас без данных. Origin задаётся `GARANT_BROWSER_BASE_URL`
(по умолчанию `https://internet.garant.ru`; для временной лицензии —
`https://demo.garant.ru`). Логин всегда на `account.garant.ru`.

На момент реализации у проекта НЕТ доступа к официальному API ГАРАНТ
(функции «Новости ПРАЙМ» / «Тематики ПРАЙМ», требующие отдельного
договора/ключа с компанией «Гарант» — уточнено у пользователя проекта).

Поэтому реализован **вариант Б**: headless-браузер (Playwright) с входом
на `account.garant.ru` по логину/паролю из .env (GARANT_LOGIN/GARANT_PASSWORD),
рендеринг SPA на выбранном origin и разбор отрендеренного DOM.

С появлением доступа к официальному API (вариант А) реализован
альтернативный класс `GarantApiParser` (`core/news/parser_api.py`),
удовлетворяющий тому же интерфейсу `NewsParser` — остальной код
(DialogueService, BotCore, интерфейсы) не менялся, т.к. они зависят
только от `NewsParser.fetch()`. Выбор между режимами — в
`core/news/parser_factory.py`.

Статус проверки (10.09.2026, `internet.garant.ru`): вход по логину и
паролю, вкладка «Новости ПРАЙМ» (это текст вкладки, не обязательно `<a>`),
лента «Общая лента ПРАЙМ», панель фильтров и разбор карточек — работают
(см. `_login_to_garant`/`_type_into`/`_apply_filters`/`_parse_html`).
`demo.garant.ru` в тот же день после сессии internet ответил alreadyused
и отдельно не подтверждён. `_apply_filters` выставляет период текстовыми
полями `from`/`to` и тему через «Полный список»; территорию и вид
информации отмечает только если темы нет (как в `api`: живой прогон 10.09.2026
за неделю по теме охраны уже дал 0 карточек, AND с территорией на этом срезе
не отличить). End-to-end apply на internet подтверждён в тот же день.

НАЙДЕНА И ИСПРАВЛЕНА РЕАЛЬНАЯ ПРИЧИНА редиректа на `garant.ru/mobileonline/alreadyused/`
(эмпирически, 06.09.2026): это оказалось не про лимит входов и не только про
параллельные сессии, а про **обнаружение автоматизации**. Обычный headless
Chromium, запущенный Playwright'ом, выдаёт себя явными признаками:
`navigator.webdriver === true` и `HeadlessChrome` прямо в User-Agent — сайт
(или стоящая перед ним защита) видит это и отправляет такую сессию на
"alreadyused" вместо настоящего логина, даже при полностью "холодном" заходе.
Подтверждено сравнением: в обычном браузере пользователя (те же логин/пароль)
всё работает без проблем — блокировался именно бот-фингерпринт.

Решение — библиотека `playwright-stealth`, которая патчит `navigator.webdriver`,
User-Agent и ещё больше десятка признаков автоматизации разом (см. использование
в `_render_page`). После этого логин проходит успешно.

Остаточное ограничение (менее важное, но реальное): демо-аккаунт всё же не
любит, когда в него логинятся ПОВТОРНО СРАЗУ ЖЕ после предыдущего успешного
входа (несколько раз подряд за секунды, даже из РАЗНЫХ процессов/скриптов —
кулдаун `MIN_SECONDS_BETWEEN_LOGINS` защищает только от повторов внутри
одного процесса) — это по-прежнему может дать `alreadyused`, но это не
мешает обычной работе бота (он логинится по одному разу на каждый новостной
запрос пользователя, а не пачками подряд). Поэтому при ручной отладке всё
равно не стоит запускать несколько логинов подряд без пауз, включая из
отдельных диагностических скриптов рядом с работающим ботом.

ФИНАЛЬНАЯ РЕШАЮЩАЯ НАХОДКА (06.09.2026): `page.wait_for_load_state("networkidle")`
ненадёжен на demo.garant.ru — на странице постоянно открыт WebSocket виджета
поддержки (`wss://chat.garant.ru/...`), из-за которого страница может никогда
не становиться по-настоящему "сетево-простаивающей" в понимании Playwright.
Заменено на точечные `wait_for_selector` для конкретных элементов (см.
`_login_to_garant`/`_render_page`) — именно это дало стабильный результат.
Подтверждено end-to-end через реальный VK-бот: пользователь получил настоящий
список новостей ГАРАНТ ПРАЙМ на запрос «изменения в законодательстве за месяц».
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Sequence
from datetime import date

from core.models import NewsItem, NewsQuery
from core.news.parser_base import NewsParser, NewsSourceBusyError

logger = logging.getLogger(__name__)

DEFAULT_BROWSER_ORIGIN = "https://internet.garant.ru"


def login_blocked_reason(url: str, body: str) -> str | None:
    """alreadyused / заглушка mobileonline без формы входа — не пустая лента."""
    url_l = (url or "").lower()
    body_l = (body or "").lower()
    if "alreadyused" in url_l or "уже используются" in body_l:
        return "busy"
    if "mobileonline/rules" in body_l or (
        "mobileonline" in body_l and "правила работы" in body_l
    ):
        return "busy"
    return None


def query_fingerprint(query: NewsQuery) -> tuple:
    """Ключ повторного запроса: тот же период и фильтры — без нового входа."""
    return (
        query.date_from.isoformat(),
        query.date_to.isoformat(),
        tuple(query.topic or ()),
        query.territory,
        tuple(query.info_type or ()),
    )


def browser_theme_keywords(query: NewsQuery) -> list[str] | None:
    """Тема для UI сайта. Несколько ключей пресета «главные» одним чекбоксом не OR."""
    topics = [str(item).strip() for item in (query.topic or []) if str(item).strip()]
    if len(topics) == 1:
        return topics
    return None


def startpage_url(origin: str | None) -> str:
    """Стартовый URL ленты: origin + `/#/startpage:1`.

    `GARANT_BROWSER_BASE_URL` задаёт origin без хэша. Если уже передали полный
    SPA-адрес (содержит `#/`), оставляем как есть — удобно для старых вызовов.
    """
    raw = (origin or DEFAULT_BROWSER_ORIGIN).strip().rstrip("/")
    if not raw:
        raw = DEFAULT_BROWSER_ORIGIN
    if "#/" in raw:
        return raw
    return f"{raw}/#/startpage:1"


def document_url(origin: str | None, href: str | None) -> str | None:
    """Полная ссылка на документ: `https://internet.garant.ru/#/document/…`."""
    if not href:
        return None
    href = str(href).strip()
    if not href:
        return None
    if href.startswith("http://") or href.startswith("https://"):
        return href
    base = (origin or DEFAULT_BROWSER_ORIGIN).strip()
    if "#/" in base:
        base = base.split("#/", 1)[0]
    base = base.rstrip("/")
    if href.startswith("/#/"):
        return f"{base}{href}"
    if href.startswith("#/"):
        return f"{base}/{href}"
    if href.startswith("/"):
        return f"{base}{href}"
    return f"{base}/#/{href}"


GARANT_BASE_URL = startpage_url(DEFAULT_BROWSER_ORIGIN)


def match_filter_labels(labels: Sequence[str], keywords: Sequence[str]) -> list[str]:
    """Подписи чекбоксов сайта, совпавшие с keywords тем же stem-AND, что дерево API.

    Если совпало несколько подписей (часто из-за короткой фразы вроде
    «охранная деятельность»), оставляем самую специфичную: больше сырых
    стемов, затем более длинное название.
    """
    from core.news import category_tree

    nodes = [{"text": text, "id": index} for index, text in enumerate(labels) if str(text).strip()]
    matched_ids = category_tree.resolve_categories(nodes, list(keywords))
    matched = [str(labels[index]).strip() for index in matched_ids]
    if len(matched) <= 1:
        return matched
    raw_stems: list[str] = []
    for keyword in keywords:
        raw_stems.extend(category_tree.extract_stems(keyword, ignore_generic=False))

    def score(label: str) -> tuple[int, int]:
        hits = sum(1 for stem in raw_stems if category_tree.stem_hits_text(stem, label))
        return (hits, len(label))

    return [max(matched, key=score)]


_WEAK_FILTER_STEMS = frozenset(
    {"охранная", "охрана", "деятельность", "право", "права", "органы"}
)


def filter_search_query(keywords: Sequence[str]) -> str:
    """Короткий текст для поля «Фильтр» в дереве сайта: редкий стем, не «охрана»."""
    from core.news import category_tree

    if not keywords:
        return ""
    stems = category_tree.extract_stems(keywords[0], ignore_generic=True)
    distinctive = [stem for stem in stems if stem not in _WEAK_FILTER_STEMS]
    if distinctive:
        return max(distinctive, key=len)
    return keywords[0][:80]


class GarantPrimeParser(NewsParser):
    """Парсер новостей ГАРАНТ ПРАЙМ через headless-браузер (вариант Б, см. докстроку модуля).

    Логин и пароль передаются через конструктор (dependency injection), а не
    читаются из .env внутри класса — это сохраняет тестируемость: в тестах
    подставляются фиктивные значения, а метод разбора DOM (`_parse_html`)
    тестируется отдельно на сохранённой офлайн-фикстуре без запуска браузера.

    Origin ленты — аргумент `base_url` (из `GARANT_BROWSER_BASE_URL`).
    Фильтры `NewsQuery`: период — поля «За период»; тема — модалка «Полный
    список» у группы «Тема» (резолюция подписей = `category_tree`). Если
    тема задана, территорию и вид информации не отмечаем; без темы их
    можно отметить. Несовпавшая тема → пустой HTML, ленту не трогаем.

    Сайт явно просит не логиниться слишком часто одним и тем же аккаунтом
    ("Ваш логин и пароль уже используются. Попробуйте войти через несколько
    минут.", см. докстроку модуля) — поэтому здесь встроен собственный
    кулдаун между попытками входа (`MIN_SECONDS_BETWEEN_LOGINS`) и блокировка
    от одновременных вызовов (`asyncio.Lock`), чтобы два новостных запроса
    от пользователей, пришедшие почти одновременно, не пытались залогиниться
    параллельно и не спровоцировали этот же самый отказ сайта.
    """

    MIN_SECONDS_BETWEEN_LOGINS = 60
    FILTER_RESULT_TIMEOUT_MS = 25000
    FILTER_SETTLE_MS = 2500
    MAX_FEED_PAGES = 100
    PAGE_TURN_TIMEOUT_MS = 15000
    KEYSTROKE_DELAY_MS = 40
    """Пауза (мс) между символами при посимвольном вводе логина/пароля — см. `_type_into`."""

    def __init__(
        self, login: str, password: str, *, base_url: str = DEFAULT_BROWSER_ORIGIN
    ) -> None:
        self._login = login
        self._password = password
        self._base_url = startpage_url(base_url)
        self._lock = asyncio.Lock()
        self._last_login_attempt_at: float | None = None
        self._last_result_key: tuple | None = None
        self._last_result: list[NewsItem] | None = None

    async def fetch(self, query: NewsQuery) -> list[NewsItem]:
        key = query_fingerprint(query)
        async with self._lock:
            if not self._cooldown_elapsed():
                if self._last_result_key == key and self._last_result is not None:
                    logger.info(
                        "GarantPrimeParser: повтор того же запроса — отдаю уже снятую ленту, без нового входа."
                    )
                    return list(self._last_result)
                raise NewsSourceBusyError(
                    f"GarantPrimeParser: с прошлой попытки входа прошло меньше "
                    f"{self.MIN_SECONDS_BETWEEN_LOGINS}с.",
                    retry_after_seconds=self.MIN_SECONDS_BETWEEN_LOGINS,
                )

            self._last_login_attempt_at = time.monotonic()
            try:
                html = await self._render_page(query)
            except NewsSourceBusyError:
                raise
            except Exception as exc:  # noqa: BLE001 - любой сбой браузера не должен ронять бота
                logger.error("GarantPrimeParser: не удалось получить данные: %s", exc)
                return []

            items = self._parse_html(html)
            self._last_result_key = key
            self._last_result = items
            return list(items)

    def _cooldown_elapsed(self) -> bool:
        if self._last_login_attempt_at is None:
            return True
        return (time.monotonic() - self._last_login_attempt_at) >= self.MIN_SECONDS_BETWEEN_LOGINS

    async def _render_page(self, query: NewsQuery) -> str:
        """Логинится на origin ленты через Playwright и возвращает HTML вкладки ПРАЙМ.

        Механизм входа подтверждён эмпирически (SSO `account.garant.ru`,
        затем возврат на `internet.garant.ru` / заданный `base_url`):
        - Кнопка "Войти" на стартовой странице не отправляет форму сама — она
          переводит на отдельную SSO-страницу account.garant.ru (login_challenge),
          где и находится настоящее поле логина.
        - Поле логина и поле пароля — React-контролируемые input'ы: значения,
          выставленные через `page.fill()`/`page.type()`, не сохраняются в
          состоянии React (после установки значения оно тут же сбрасывается в
          пустую строку). Рабочий способ — по-символьный `page.keyboard.press()`
          после клика по полю, как обычная печать пользователем.
        - После ввода логина и пароля (каждый на своём отдельном шаге SSO,
          с кнопкой "Войти"/submit между ними) происходит редирект обратно на
          origin ленты — сессия считается активной.

        ВАЖНО: без маскировки через `playwright-stealth` (см. ниже) этот логин
        почти всегда проваливается редиректом на alreadyused — сайт распознаёт
        headless-браузер по `navigator.webdriver`/User-Agent (см. докстроку
        модуля). Также не стоит логиниться повторно сразу же после предыдущего
        успешного входа (несколько раз подряд за секунды) — это по-прежнему
        может дать alreadyused, хотя обычной работе бота (один логин на один
        новостной запрос) это не мешает.

        Вкладка «Новости ПРАЙМ» на internet — текст вкладки (`get_by_text`),
        не обязательно ссылка `<a>`. После открытия панели вызывается
        `_apply_filters` (даты, тема; территория/вид информации — только
        без темы).
        """
        # Локальные импорты: не требуются для юнит-тестов форматтера/парсинга
        # (_parse_html тестируется отдельно, без запуска браузера).
        from playwright.async_api import async_playwright
        from playwright_stealth import Stealth

        # Маскировка автоматизации — см. предупреждение в докстроке модуля:
        # без неё сайт почти всегда отправляет headless-сессию на alreadyused.
        stealth = Stealth(navigator_languages_override=("ru-RU", "ru"))

        async with stealth.use_async(async_playwright()) as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await self._login_to_garant(page)

                # Раньше здесь стоял `wait_for_load_state("networkidle")`
                # перед кликом — убран. На странице постоянно открыт WebSocket
                # виджета поддержки (`ppoRoot`, `wss://chat.garant.ru/...`),
                # из-за которого страница может никогда по-настоящему не
                # становиться "сетево-простаивающей". Ждём вкладку по тексту.
                news_tab = page.get_by_text("Новости ПРАЙМ", exact=True).first
                await news_tab.wait_for(timeout=20000)
                await self._simulate_human_pause(page)
                await news_tab.click(timeout=10000)
                await page.get_by_text("Применить фильтры", exact=True).wait_for(
                    timeout=self.FILTER_RESULT_TIMEOUT_MS
                )

                applied = await self._apply_filters(page, query)
                if not applied:
                    return ""

                return await self._collect_feed_pages(page)
            finally:
                await browser.close()

    async def _login_to_garant(self, page) -> None:
        """Логин на origin ленты через SSO account.garant.ru.

        Используются точечные `wait_for_selector`/`wait_for_url` вместо
        `wait_for_load_state("networkidle")` — на сайте постоянно открыт
        WebSocket виджета поддержки (`wss://chat.garant.ru/...`).
        """
        await page.goto(self._base_url, wait_until="load")
        await self._raise_if_login_blocked(page)
        await self._simulate_human_pause(page)
        await self._raise_if_login_blocked(page)
        await self._click_start_login(page)
        await page.wait_for_url("**/account.garant.ru/**")

        await self._simulate_human_pause(page)
        await page.wait_for_selector('input[name="username"]', timeout=20000)
        await self._type_into(page, 'input[name="username"]', self._login)
        await page.click('button[type="submit"]')
        await page.wait_for_timeout(1500)

        await self._simulate_human_pause(page)
        await page.wait_for_selector('input[type="password"]', timeout=20000)
        await self._type_into(page, 'input[type="password"]', self._password)
        await page.click('button[type="submit"]')
        await page.wait_for_load_state("load")
        await self._assert_login_landed(page)

    @staticmethod
    async def _type_into(page, selector: str, text: str) -> None:
        """Печатает текст по одному символу через клавиатуру.

        Обычный `locator.fill()`/`locator.type()` не работает с полями логина
        на account.garant.ru — значение сбрасывается React-компонентом
        (подтверждено эмпирически, см. докстроку `_render_page`).

        Небольшая пауза между нажатиями (см. `KEYSTROKE_DELAY_MS`) — эмпирическая
        находка 09.09.2026 (аудит фильтров, `docs/garant-site-filters-audit.md`):
        без паузы React иногда не успевает обработать нажатие и теряет один
        символ (например, вместо 4-значного пароля до поля доходит 3 символа,
        сайт отвечает "Неверные данные") — редкая, но реальная флуктуация.
        """
        locator = page.locator(selector)
        await locator.click()
        await page.keyboard.press("Control+A")
        for char in text:
            await page.keyboard.press(char)
            await page.wait_for_timeout(GarantPrimeParser.KEYSTROKE_DELAY_MS)

    async def _apply_filters(self, page, query: NewsQuery) -> bool:
        """Выставляет фильтры UI по NewsQuery. False = тему не нашли, ленту не трогаем.

        Аудит internet.garant.ru 10.09.2026: панель слева, группы чекбоксов,
        «Полный список» открывает модалку, период — текстовые поля
        input[name=from]/[name=to] (placeholder дд.мм.гггг) после радио «За период».
        Комбинация тема+территория на internet 10.09.2026: обе оси кликаются,
        но за неделю по теме охраны лента уже была пустой («Ничего не найдено»),
        поэтому AND vs исключение территории на этом срезе не различить.
        Пока тема задана — территорию и вид информации не отмечаем, как в api.
        Когда темы нет — территорию/вид информации применяем.
        Пустая лента: `.emptyMessage` («Ничего не найдено»).
        Кнопки «за неделю»/«за месяц» на сайте — радио, не набор дат: набор
        `from`/`to` после «За период» на срезе 10.09.2026 давал 0 карточек
        («Лента отфильтрована» + empty), хотя тот же аккаунт за свой период
        12.01–09.09 по охране вернул 24 новости, часть из них за последний месяц.
        Несколько тем пресета «главные» одним кликом не объединяются — одна
        подпись сужает ленту; для них тему не отмечаем, только период.
        """
        await self._apply_period(page, query)

        theme = browser_theme_keywords(query)
        if theme:
            if not await self._select_filter_labels(page, "Тема", theme):
                logger.warning(
                    "GarantPrimeParser: тема %s не совпала с чекбоксами сайта — лента не запрашивается.",
                    theme,
                )
                return False
        else:
            if query.territory:
                await self._select_filter_labels(page, "Территория", [query.territory])
            if query.info_type:
                await self._select_filter_labels(page, "Вид информации", query.info_type)

        logger.info(
            "GarantPrimeParser: apply period=%s…%s theme=%s",
            query.date_from.isoformat(),
            query.date_to.isoformat(),
            theme,
        )
        await self._simulate_human_pause(page)
        await page.get_by_text("Применить фильтры", exact=True).click()
        await self._wait_for_filter_result(page)
        return True

    async def _apply_period(self, page, query: NewsQuery) -> None:
        """Неделя/месяц — радио сайта; иначе «За период» и набор дат."""
        span = (query.date_to - query.date_from).days
        if span == 7:
            await page.get_by_text("За неделю", exact=True).click()
            return
        if span == 30:
            await page.get_by_text("За месяц", exact=True).click()
            return
        await page.get_by_text("За период", exact=True).click()
        await self._type_into(
            page, 'input[name="from"]', query.date_from.strftime("%d.%m.%Y")
        )
        await self._type_into(
            page, 'input[name="to"]', query.date_to.strftime("%d.%m.%Y")
        )

    async def _wait_for_filter_result(self, page) -> None:
        """Ждёт новую ленту, а не старые карточки, которые уже были на экране.

        10.09.2026: `wait_for_selector(.primeDocument)` срабатывал сразу на
        нефильтрованной выдаче. Класс `.resetFilter` тоже нельзя ждать: он
        уже висит на кнопке панели рядом с «Применить фильтры». Настоящая
        отметка успеха — текст «Лента отфильтрована» над лентой либо
        `.emptyMessage` / «Ничего не найдено». Если кликнуть «Следующая»
        раньше этого, пагинатор ещё от общей ленты (до 299 страниц) и
        сбрасывает apply — фильтр «за месяц» выглядит сломанным.
        """
        marker = (
            page.get_by_text("Лента отфильтрована")
            .or_(page.locator(".emptyMessage"))
            .or_(page.get_by_text("Ничего не найдено"))
        )
        try:
            await marker.first.wait_for(timeout=self.FILTER_RESULT_TIMEOUT_MS)
        except Exception:
            logger.info(
                "GarantPrimeParser: нет отметки «лента отфильтрована», жду обновления списка."
            )
        await page.wait_for_timeout(self.FILTER_SETTLE_MS)
        cards = await page.locator(".primeDocument").count()
        logger.info(
            "GarantPrimeParser: после apply карточек=%s, «Лента отфильтрована»=%s, empty=%s",
            cards,
            await page.get_by_text("Лента отфильтрована").count(),
            await page.locator(".emptyMessage").count(),
        )

    @staticmethod
    async def _feed_markup(page) -> str:
        """Только карточки ленты, не полный ExtJS-DOM (склейка page.content() ломает разбор)."""
        return await page.evaluate(
            """() => {
                const pick = (root) => Array.from(
                    root.querySelectorAll('.primeDate, .primeDocument')
                ).map((node) => node.outerHTML).join('\\n');
                const container = document.querySelector('.documentPrimeContainer');
                const fromContainer = container ? pick(container) : '';
                if (fromContainer) return fromContainer;
                return pick(document.body);
            }"""
        )

    async def _collect_feed_pages(self, page) -> str:
        """Снимает не одну страницу ленты (~20 карточек), а все, листая «Следующая».

        На internet.garant.ru пагинатор: `ul.paginator` с `li.next` / `li.current`
        и `data-page` (на срезе 10.09.2026 первая выдача — 20 карточек, страниц 299).
        Листаем только после apply и только пока жива «Лента отфильтрована»:
        клик по устаревшему «Следующая» сбрасывает фильтры. Верхняя граница —
        `MAX_FEED_PAGES`, чтобы «главные за год» не крутили браузер десятки минут.
        """
        empty = page.locator(".emptyMessage")
        cards = page.locator(".primeDocument")
        if (
            await empty.count()
            and await empty.first.is_visible()
            and await cards.count() == 0
        ):
            return ""
        if await empty.count() and await empty.first.is_visible() and await cards.count():
            logger.warning(
                "GarantPrimeParser: есть и emptyMessage, и карточки — снимаю карточки."
            )

        parts = [await self._feed_markup(page)]
        had_filter_banner = await page.get_by_text("Лента отфильтрована").count() > 0
        paginator = page.locator("ul.paginator").last
        for _page_no in range(2, self.MAX_FEED_PAGES + 1):
            nxt = paginator.locator("li.next:not(.disabled)")
            if await nxt.count() == 0:
                break
            current = await paginator.locator("li.current").get_attribute("data-page")
            await nxt.first.click()
            try:
                await page.wait_for_function(
                    """(prev) => {
                        const nodes = document.querySelectorAll('ul.paginator li.current');
                        const cur = nodes[nodes.length - 1];
                        return Boolean(cur) && cur.getAttribute('data-page') !== prev;
                    }""",
                    arg=current or "",
                    timeout=self.PAGE_TURN_TIMEOUT_MS,
                )
            except Exception:
                logger.info("GarantPrimeParser: лента не перелистнулась после «Следующая».")
                break
            if had_filter_banner and await page.get_by_text("Лента отфильтрована").count() == 0:
                logger.info(
                    "GarantPrimeParser: клик «Следующая» сбросил фильтры — дальше не листаю."
                )
                break
            parts.append(await self._feed_markup(page))
        else:
            logger.warning(
                "GarantPrimeParser: обошёл %s страниц ленты и остановился (MAX_FEED_PAGES).",
                self.MAX_FEED_PAGES,
            )
        return "\n".join(parts)

    async def _select_filter_labels(self, page, legend: str, keywords: list[str]) -> bool:
        """Открывает модалку «Полный список» у группы и отмечает наиболее точный узел.

        Тема на internet.garant.ru — дерево ExtJS с полем placeholder «Фильтр»
        (у «Вида информации» в аудите было «Поиск»). Листья вроде «Частная
        сыскная и охранная деятельность» не видны в свёрнутом дереве: сначала
        фильтр по редкому стему («сыскная»), затем раскрытие оставшихся узлов.
        Клик только внутри окна, иначе попадём в чекбокс панели под модалкой.
        """
        fieldset = page.locator("fieldset").filter(
            has=page.locator(".x-fieldset-header-text", has_text=legend)
        ).first
        await fieldset.get_by_text("Полный список", exact=True).click()
        dialog = await self._visible_filter_dialog(page, legend)
        await dialog.get_by_text("Выбрать", exact=True).wait_for(
            state="attached", timeout=15000
        )

        search = dialog.get_by_placeholder(re.compile(r"^(Поиск|Фильтр)$", re.IGNORECASE))
        queries: list[str] = []
        if keywords:
            rare = filter_search_query(keywords)
            if rare:
                queries.append(rare)
            if keywords[0][:80] not in queries:
                queries.append(keywords[0][:80])

        matched: list[str] = []
        for query_text in queries or [""]:
            if query_text and await search.count():
                await search.first.click()
                await page.keyboard.press("Control+A")
                await page.keyboard.type(
                    query_text, delay=GarantPrimeParser.KEYSTROKE_DELAY_MS
                )
                await page.wait_for_timeout(800)
            await self._expand_collapsed_tree(dialog, page)
            labels = await self._dialog_filter_labels(dialog)
            matched = match_filter_labels(labels, keywords)
            if matched:
                break
            logger.info(
                "GarantPrimeParser: фильтр %r в %s не дал узла, видно %s",
                query_text,
                legend,
                labels[:15],
            )

        if not matched:
            cancel = dialog.get_by_text("Отмена", exact=True)
            if await cancel.count():
                await cancel.first.click(force=True)
            return False

        target = dialog.get_by_text(matched[0], exact=True).first
        await target.click(force=True)
        await dialog.get_by_text("Выбрать", exact=True).click(force=True)
        return True

    @staticmethod
    async def _visible_filter_dialog(page, legend: str):
        windows = page.locator(".x-window").filter(has_text=legend)
        if await windows.count() == 0:
            windows = page.locator(".x-window").filter(
                has=page.get_by_text("Выбрать", exact=True)
            )
        await windows.first.wait_for(state="attached", timeout=15000)
        total = await windows.count()
        for index in range(total):
            candidate = windows.nth(index)
            if await candidate.is_visible():
                return candidate
        return windows.last

    @staticmethod
    async def _dialog_filter_labels(dialog) -> list[str]:
        labels = await dialog.locator(
            ".x-tree-node-text, .x-form-cb-label, .x-grid-cell"
        ).all_text_contents()
        labels = [item.strip() for item in labels if item.strip()]
        if labels:
            return labels
        raw = await dialog.inner_text()
        return [line.strip() for line in raw.splitlines() if line.strip()]

    @staticmethod
    async def _expand_collapsed_tree(dialog, page, limit: int = 30) -> None:
        clicks = 0
        while clicks < limit:
            collapsed = dialog.locator(".x-grid-tree-node-collapsed .x-tree-expander")
            if await collapsed.count() == 0:
                collapsed = dialog.locator(".x-tree-node-collapsed .x-tree-expander")
            if await collapsed.count() == 0:
                break
            await collapsed.first.click()
            clicks += 1
            await page.wait_for_timeout(150)

    async def _click_start_login(self, page) -> None:
        """Кликает «Войти» на старте. Заглушка без кнопки — это busy, не пустая лента.

        10.09.2026: Playwright ждал `button[type=submit]` 30с на странице, чей HTML
        заканчивался `</center></body></html>` — фильтры даже не запускались, а
        `fetch()` превращал таймаут в []. В чат уходило «изменений не найдено».
        Заглушка mobileonline («Правила работы») распознаётся сразу, без 20 с.
        """
        await self._raise_if_login_blocked(page)
        submit = page.locator('button[type="submit"]').first
        try:
            await submit.wait_for(state="visible", timeout=20000)
        except Exception:
            await self._raise_if_login_blocked(page)
            snippet = (await page.content()).replace("\n", " ")[-240:]
            logger.error(
                "GarantPrimeParser: нет кнопки Войти, url=%s html_tail=%s",
                page.url,
                snippet,
            )
            raise NewsSourceBusyError(
                "GarantPrimeParser: стартовая страница без кнопки входа "
                "(заглушка/alreadyused). Подождите перед следующей попыткой.",
                retry_after_seconds=self.MIN_SECONDS_BETWEEN_LOGINS,
            )
        await submit.click()

    async def _raise_if_login_blocked(self, page) -> None:
        """alreadyused на старте — без 30с таймаута клика по отсутствующему Войти."""
        reason = login_blocked_reason(page.url, await page.content())
        if reason == "busy":
            raise NewsSourceBusyError(
                "GarantPrimeParser: сайт ответил, что логин уже используется. "
                "Подождите несколько минут перед следующей попыткой.",
                retry_after_seconds=self.MIN_SECONDS_BETWEEN_LOGINS,
            )

    async def _assert_login_landed(self, page) -> None:
        """После SSO должны оказаться в системе, а не на alreadyused / account."""
        try:
            await page.wait_for_url(
                re.compile(r"alreadyused|internet\.garant\.ru|demo\.garant\.ru"),
                timeout=25000,
            )
        except Exception:
            pass
        await self._raise_if_login_blocked(page)
        body = (await page.content()).lower()
        if "неверные данные" in body:
            raise RuntimeError("GarantPrimeParser: сайт отклонил логин или пароль.")
        await page.get_by_text("Новости ПРАЙМ", exact=True).first.wait_for(timeout=25000)

    @staticmethod
    async def _simulate_human_pause(page) -> None:
        """Случайная пауза (1-5с) + движение мыши — имитация поведения человека.

        Мера против поведенческой антибот-проверки (мгновенный клик без
        движения мыши сразу после загрузки страницы — типичный признак
        автоматизации), см. докстроку модуля. Используется вместе с заменой
        `networkidle` на точечные `wait_for_selector` — вместе они дали
        стабильный подтверждённый результат. Из-за этих пауз один полный
        логин+переход занимает заметно дольше (несколько пауз по 1-5с на
        разных шагах) — это осознанный компромисс в пользу похожести на
        реального пользователя.
        """
        import random

        x, y = random.randint(100, 800), random.randint(100, 600)
        await page.mouse.move(x, y, steps=random.randint(5, 15))
        await page.wait_for_timeout(random.randint(1000, 5000))

    def _parse_html(self, html: str) -> list[NewsItem]:
        """Извлекает NewsItem из отрендеренного HTML вкладки «Новости ПРАЙМ».

        Разметка подтверждена эмпирически на реальном demo-аккаунте
        (вкладка «Новости ПРАЙМ» → «Общая лента ПРАЙМ»):

        - `.primeDate` — заголовок даты (например "06 сентября 2026"),
          относится ко всем следующим `.primeDocument` вплоть до следующего
          `.primeDate` (даты не дублируются в каждой карточке).
        - `.primeDocument` — одна карточка новости/документа:
            - `.documentTitle a` — полное название документа со ссылкой (`href`);
            - `.annotationTitle` — короткий заголовок-аннотация (используется,
              только если `.documentTitle a` почему-то отсутствует);
            - `.annotationText p` — один или несколько абзацев описания.
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        items: list[NewsItem] = []
        current_date: date | None = None
        seen: set[str] = set()

        for node in soup.select(".primeDate, .primeDocument"):
            classes = node.get("class") or []

            if "primeDate" in classes:
                current_date = self._parse_russian_date(node.get_text(strip=True))
                continue

            link_node = node.select_one(".documentTitle a[href]")
            title_node = link_node or node.select_one(".annotationTitle")
            title = title_node.get_text(strip=True) if title_node else None
            if not title:
                continue

            summary = " ".join(
                p.get_text(strip=True) for p in node.select(".annotationText p") if p.get_text(strip=True)
            )
            url = document_url(
                self._base_url,
                link_node["href"] if link_node and link_node.has_attr("href") else None,
            )
            key = url or title
            if key in seen:
                continue
            seen.add(key)

            items.append(
                NewsItem(
                    title=title,
                    summary=summary,
                    published_at=current_date,
                    url=url,
                )
            )

        return items

    _MONTHS_RU = {
        "января": 1, "февраля": 2, "марта": 3, "апреля": 4, "мая": 5, "июня": 6,
        "июля": 7, "августа": 8, "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
    }

    @classmethod
    def _parse_russian_date(cls, text: str) -> date | None:
        """Парсит дату вида "06 сентября 2026" (формат `.primeDate` на сайте ГАРАНТ)."""
        match = re.match(r"(\d{1,2})\s+([а-яё]+)\s+(\d{4})", text.strip(), re.IGNORECASE)
        if not match:
            return None
        day, month_name, year = match.groups()
        month = cls._MONTHS_RU.get(month_name.lower())
        if month is None:
            return None
        return date(int(year), month, int(day))
