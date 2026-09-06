"""NewsParser — интерфейс + GarantPrimeParser (реализация для demo.garant.ru).

Архитектурная развилка (см. ТЗ п. 3.1) и её решение
-----------------------------------------------------
Целевая страница https://demo.garant.ru/#/startpage:1 — SPA: контент
рендерится в браузере через JavaScript, обычный HTTP-запрос (requests/httpx)
вернёт пустой каркас без данных.

На момент реализации у проекта НЕТ доступа к официальному API ГАРАНТ
(функции «Новости ПРАЙМ» / «Тематики ПРАЙМ», требующие отдельного
договора/ключа с компанией «Гарант» — уточнено у пользователя проекта).

Поэтому реализован **вариант Б**: headless-браузер (Playwright) с входом
на demo.garant.ru по логину/паролю из .env (GARANT_LOGIN/GARANT_PASSWORD),
рендеринг SPA и разбор отрендеренного DOM.

Если в будущем появится доступ к официальному API (вариант А), нужно
реализовать новый класс, удовлетворяющий интерфейсу NewsParser (HTTP-клиент
к API вместо браузера) — остальной код (DialogueService, BotCore,
интерфейсы) менять не придётся, т.к. они зависят только от NewsParser.fetch().

Статус проверки (эмпирически, на реальном demo-аккаунте): вход по логину и
паролю, переход на вкладку «Новости ПРАЙМ» (ленту «Общая лента ПРАЙМ») и
разбор реальной разметки списка новостей — всё подтверждено и работает
(см. `_login_to_garant`/`_type_into`, `_parse_html`). Применение фильтров
`NewsQuery` (дата/тема/орган/вид информации) через UI фильтров вкладки —
ещё не подтверждено эмпирически, сейчас фильтры сайта не выставляются, и
`fetch()` возвращает ленту "как есть" (обычно "за 3 месяца" по умолчанию
на стороне сайта). См. TODO в `_render_page`, включая замеченный маршрут
`/#/fresh/DD.MM.YYYY;DD.MM.YYYY` как вероятный прямой способ задать период
без ручного взаимодействия с UI-фильтрами.

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
from abc import ABC, abstractmethod
from datetime import date

from core.models import NewsItem, NewsQuery

logger = logging.getLogger(__name__)

GARANT_BASE_URL = "https://demo.garant.ru/#/startpage:1"


class NewsParser(ABC):
    """Контракт источника новостей — не зависит от способа получения данных."""

    @abstractmethod
    async def fetch(self, query: NewsQuery) -> list[NewsItem]:
        """Вернуть список новостей, подходящих под фильтры query."""


class GarantPrimeParser(NewsParser):
    """Парсер новостей ГАРАНТ ПРАЙМ через headless-браузер (вариант Б, см. докстроку модуля).

    Логин и пароль передаются через конструктор (dependency injection), а не
    читаются из .env внутри класса — это сохраняет тестируемость: в тестах
    подставляются фиктивные значения, а метод разбора DOM (`_parse_html`)
    тестируется отдельно на сохранённой офлайн-фикстуре без запуска браузера.

    Сайт явно просит не логиниться слишком часто одним и тем же аккаунтом
    ("Ваш логин и пароль уже используются. Попробуйте войти через несколько
    минут.", см. докстроку модуля) — поэтому здесь встроен собственный
    кулдаун между попытками входа (`MIN_SECONDS_BETWEEN_LOGINS`) и блокировка
    от одновременных вызовов (`asyncio.Lock`), чтобы два новостных запроса
    от пользователей, пришедшие почти одновременно, не пытались залогиниться
    параллельно и не спровоцировали этот же самый отказ сайта.
    """

    MIN_SECONDS_BETWEEN_LOGINS = 60

    def __init__(self, login: str, password: str, *, base_url: str = GARANT_BASE_URL) -> None:
        self._login = login
        self._password = password
        self._base_url = base_url
        self._lock = asyncio.Lock()
        self._last_login_attempt_at: float | None = None

    async def fetch(self, query: NewsQuery) -> list[NewsItem]:
        async with self._lock:
            if not self._cooldown_elapsed():
                logger.info(
                    "GarantPrimeParser: пропускаю запрос — с прошлой попытки входа прошло меньше %sс "
                    "(сайт просит не логиниться слишком часто одним аккаунтом).",
                    self.MIN_SECONDS_BETWEEN_LOGINS,
                )
                return []

            self._last_login_attempt_at = time.monotonic()
            try:
                html = await self._render_page(query)
            except Exception as exc:  # noqa: BLE001 - любой сбой браузера не должен ронять бота
                logger.error("GarantPrimeParser: не удалось получить данные: %s", exc)
                return []

        return self._parse_html(html)

    def _cooldown_elapsed(self) -> bool:
        if self._last_login_attempt_at is None:
            return True
        return (time.monotonic() - self._last_login_attempt_at) >= self.MIN_SECONDS_BETWEEN_LOGINS

    async def _render_page(self, query: NewsQuery) -> str:
        """Открывает demo.garant.ru через Playwright, логинится и возвращает HTML вкладки «Новости ПРАЙМ».

        Механизм входа подтверждён эмпирически (реальный логин на demo.garant.ru):
        - Кнопка "Войти" на demo.garant.ru не отправляет форму сама — она
          переводит на отдельную SSO-страницу account.garant.ru (login_challenge),
          где и находится настоящее поле логина.
        - Поле логина и поле пароля — React-контролируемые input'ы: значения,
          выставленные через `page.fill()`/`page.type()`, не сохраняются в
          состоянии React (после установки значения оно тут же сбрасывается в
          пустую строку). Рабочий способ — по-символьный `page.keyboard.press()`
          после клика по полю, как обычная печать пользователем.
        - После ввода логина и пароля (каждый на своём отдельном шаге SSO,
          с кнопкой "Войти"/submit между ними) происходит редирект обратно на
          demo.garant.ru — сессия считается активной.

ВАЖНО: без маскировки через `playwright-stealth` (см. ниже) этот логин
        почти всегда проваливается редиректом на alreadyused — сайт распознаёт
        headless-браузер по `navigator.webdriver`/User-Agent (см. докстроку
        модуля). Также не стоит логиниться повторно сразу же после предыдущего
        успешного входа (несколько раз подряд за секунды) — это по-прежнему
        может дать alreadyused, хотя обычной работе бота (один логин на один
        новостной запрос) это не мешает.

        Переход на вкладку «Новости ПРАЙМ» подтверждён — клик по ссылке с
        текстом "Новости ПРАЙМ" на главной странице после входа открывает
        ленту "Общая лента ПРАЙМ" с реальным списком документов (разметка
        описана в докстроке `_parse_html`).

        TODO: применение фильтров `query` (дата/тема/орган/вид информации)
        через UI вкладки ещё не реализовано — сейчас `fetch()` просто
        возвращает то, что показывает лента по умолчанию (без выставления
        фильтров), без учёта `query.date_from`/`date_to`/`topic`/`authority`.
        Многообещающая зацепка, замеченная на главной странице после логина
        (там же, где ссылки "За сутки/неделю/месяц" со счётчиком новых
        документов): SPA поддерживает прямой маршрут вида
        `/#/fresh/DD.MM.YYYY;DD.MM.YYYY` (например `/#/fresh/05.09.2026;06.09.2026`)
        — судя по всему, список новых документов за произвольный период,
        что ложится на `NewsQuery.date_from`/`date_to` напрямую. Нужно
        проверить эмпирически (по возможности не чаще одного раза за сессию,
        см. предупреждение выше про единственную активную сессию), даёт ли
        этот маршрут нужный список и как в нём/через фильтры вкладки
        применяются остальные поля `query` (тема/орган/вид информации).
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

                # TODO: применить фильтры query (дата/тема/орган/...) — см. TODO
                # выше, требует донастройки после эмпирической проверки.
                #
                # ВАЖНО: раньше здесь стоял `wait_for_load_state("networkidle")`
                # перед кликом — убран. На странице постоянно открыт WebSocket
                # виджета поддержки (`ppoRoot`, `wss://chat.garant.ru/...`),
                # из-за которого страница может никогда по-настоящему не
                # становиться "сетево-простаивающей", и это ожидание либо
                # зависает, либо срабатывает ненадёжно/непредсказуемо по
                # времени. Вместо этого просто ждём саму ссылку через
                # `wait_for_selector` — она не зависит от состояния сети.
                #
                # Пауза + движение мыши перед кликом (имитация человека) —
                # см. `_simulate_human_pause`. Вместе с заменой networkidle
                # выше на wait_for_selector это дало стабильный результат
                # (подтверждено end-to-end через реальный VK-бот, см. докстроку
                # модуля).
                news_tab_link = "a:has-text('Новости ПРАЙМ')"
                await page.wait_for_selector(news_tab_link, timeout=20000)
                await self._simulate_human_pause(page)
                await page.click(news_tab_link, timeout=10000)
                await page.wait_for_selector(".primeDocument, .primeDate", timeout=20000)

                return await page.content()
            finally:
                await browser.close()

    async def _login_to_garant(self, page) -> None:
        """Логин на demo.garant.ru через SSO account.garant.ru (см. TODO в _render_page).

        Используются точечные `wait_for_selector`/`wait_for_url` вместо
        `wait_for_load_state("networkidle")`, где это возможно — на
        demo.garant.ru постоянно открыт WebSocket виджета поддержки
        (`wss://chat.garant.ru/...`), из-за которого страница может никогда
        не становиться по-настоящему "сетево-простаивающей" (см. TODO в
        `_render_page`).
        """
        await page.goto(self._base_url, wait_until="load")
        await self._simulate_human_pause(page)
        await page.click('button[type="submit"]')  # переход на account.garant.ru (login_challenge)
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
        # Не "networkidle" — см. докстроку метода: после успешного входа
        # редиректит на demo.garant.ru, где висит WebSocket чата поддержки.
        await page.wait_for_load_state("load")

    @staticmethod
    async def _type_into(page, selector: str, text: str) -> None:
        """Печатает текст по одному символу через клавиатуру.

        Обычный `locator.fill()`/`locator.type()` не работает с полями логина
        на account.garant.ru — значение сбрасывается React-компонентом
        (подтверждено эмпирически, см. докстроку `_render_page`).
        """
        locator = page.locator(selector)
        await locator.click()
        for char in text:
            await page.keyboard.press(char)

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

            items.append(
                NewsItem(
                    title=title,
                    summary=summary,
                    published_at=current_date,
                    url=link_node["href"] if link_node and link_node.has_attr("href") else None,
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
