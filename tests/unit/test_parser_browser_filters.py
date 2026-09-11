"""Офлайн-тесты резолюции фильтров browser-режима (без сайта ГАРАНТ)."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest

from core.models import NewsQuery
from core.news.parser_browser import (
    GarantPrimeParser,
    browser_theme_keywords,
    filter_search_query,
    match_filter_labels,
)
from core.news.presets import PRESET_ALL_MAIN

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "garant_browser_filters_panel.html"


@pytest.fixture
async def panel_page():
    os.environ.setdefault(
        "PLAYWRIGHT_BROWSERS_PATH",
        str(Path.home() / "AppData" / "Local" / "ms-playwright"),
    )
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.launch(headless=True)
    except Exception as exc:  # noqa: BLE001 — без Chromium эти тесты пропускаем
        await playwright.stop()
        pytest.skip(f"Chromium Playwright недоступен: {exc}")
    page = await browser.new_page()
    await page.goto(FIXTURE.resolve().as_uri())
    try:
        yield page
    finally:
        await browser.close()
        await playwright.stop()


def _parser(monkeypatch) -> GarantPrimeParser:
    monkeypatch.setattr(GarantPrimeParser, "KEYSTROKE_DELAY_MS", 0)
    monkeypatch.setattr(GarantPrimeParser, "FILTER_RESULT_TIMEOUT_MS", 400)
    monkeypatch.setattr(GarantPrimeParser, "FILTER_SETTLE_MS", 0)
    monkeypatch.setattr(GarantPrimeParser, "PAGE_TURN_TIMEOUT_MS", 2000)

    async def _noop(self, page) -> None:
        return None

    monkeypatch.setattr(GarantPrimeParser, "_simulate_human_pause", _noop)
    return GarantPrimeParser(login="fake", password="fake")



def test_match_security_topic_to_site_checkbox():
    labels = [
        "Налоги и сборы",
        "Частная сыскная и охранная деятельность",
        "Образование",
    ]
    matched = match_filter_labels(labels, ["охранная деятельность"])
    assert matched == ["Частная сыскная и охранная деятельность"]


def test_match_prefers_private_security_over_labor_protection():
    matched = match_filter_labels(
        ["Охрана труда", "Частная сыскная и охранная деятельность"],
        ["охранная деятельность"],
    )
    assert matched == ["Частная сыскная и охранная деятельность"]


def test_match_maps_api_security_name_to_site_wording():
    matched = match_filter_labels(
        ["Частная детективная и охранная деятельность", "Охрана труда"],
        ["Частная сыскная и охранная деятельность"],
    )
    assert matched == ["Частная детективная и охранная деятельность"]



def test_filter_search_query_prefers_rare_stem():
    query = filter_search_query(["Частная сыскная и охранная деятельность"])
    assert query in {"сыскная", "частная"}
    assert query != "охранная"


def test_match_education_inflection():
    matched = match_filter_labels(["Образование"], ["образования"])
    assert matched == ["Образование"]


def test_filters_fixture_has_period_inputs_and_apply():
    html = FIXTURE.read_text(encoding="utf-8")
    assert 'name="from"' in html
    assert 'name="to"' in html
    assert "Применить фильтры" in html
    assert "Частная сыскная и охранная деятельность" in html


def test_topic_excludes_territory_documented_in_helper():
    """Тема матчится отдельно от территории: разные списки подписей."""
    topics = match_filter_labels(
        ["Частная сыскная и охранная деятельность"], ["охрана"]
    )
    territories = match_filter_labels(["г.Москва"], ["охрана"])
    assert topics
    assert not territories


@pytest.mark.asyncio
async def test_apply_period_and_topic_on_local_html(panel_page, monkeypatch):
    parser = _parser(monkeypatch)
    query = NewsQuery(
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 10),
        topic=["охранная деятельность"],
        territory="г.Москва",
    )

    applied = await parser._apply_filters(panel_page, query)

    assert applied is True
    assert await panel_page.locator('input[name="from"]').input_value() == "01.09.2026"
    assert await panel_page.locator('input[name="to"]').input_value() == "10.09.2026"
    assert await panel_page.locator("#apply").get_attribute("data-clicked") == "1"
    assert await panel_page.locator('[data-axis="topic"]').get_attribute("data-clicked") == "1"
    assert await panel_page.locator('[data-axis="territory"]').get_attribute("data-clicked") == "0"
    assert await panel_page.get_by_text("Лента отфильтрована").count() == 1


@pytest.mark.asyncio
async def test_apply_month_clicks_site_radio_not_date_fields(panel_page, monkeypatch):
    parser = _parser(monkeypatch)
    query = NewsQuery(
        date_from=date(2026, 8, 11),
        date_to=date(2026, 9, 10),
        topic=["Частная сыскная и охранная деятельность"],
    )
    assert (query.date_to - query.date_from).days == 30

    applied = await parser._apply_filters(panel_page, query)

    assert applied is True
    assert await panel_page.locator("#radio-month").get_attribute("data-clicked") == "1"
    assert await panel_page.locator('input[name="from"]').input_value() == ""
    assert await panel_page.locator('[data-axis="topic"]').get_attribute("data-clicked") == "1"


@pytest.mark.asyncio
async def test_apply_all_main_month_skips_theme(panel_page, monkeypatch):
    parser = _parser(monkeypatch)
    query = PRESET_ALL_MAIN(date_from=date(2026, 8, 11), date_to=date(2026, 9, 10))
    assert browser_theme_keywords(query) is None

    applied = await parser._apply_filters(panel_page, query)

    assert applied is True
    assert await panel_page.locator("#radio-month").get_attribute("data-clicked") == "1"
    assert await panel_page.locator('[data-axis="topic"]').get_attribute("data-clicked") == "0"


@pytest.mark.asyncio
async def test_unknown_topic_does_not_apply_filters(panel_page, monkeypatch):
    parser = _parser(monkeypatch)
    query = NewsQuery(
        date_from=date(2026, 9, 1),
        date_to=date(2026, 9, 10),
        topic=["zxcvbnm"],
    )

    applied = await parser._apply_filters(panel_page, query)

    assert applied is False
    assert await panel_page.locator("#apply").get_attribute("data-clicked") is None


@pytest.mark.asyncio
async def test_empty_feed_after_apply_is_success(panel_page, monkeypatch):
    await panel_page.evaluate(
        """() => {
            document.querySelectorAll('.primeDate, .primeDocument').forEach((n) => n.remove());
            const empty = document.createElement('div');
            empty.className = 'emptyMessage';
            empty.textContent = 'Ничего не найдено.';
            document.body.appendChild(empty);
        }"""
    )
    parser = _parser(monkeypatch)
    query = NewsQuery(date_from=date(2026, 9, 1), date_to=date(2026, 9, 10))

    applied = await parser._apply_filters(panel_page, query)

    assert applied is True
    assert await panel_page.locator("#apply").get_attribute("data-clicked") == "1"


@pytest.mark.asyncio
async def test_collect_feed_pages_clicks_next(panel_page, monkeypatch):
    await panel_page.set_content(
        """
        <div class="primeDocument"><div class="documentTitle"><a href="/#/document/1">Первая</a></div></div>
        <ul class="paginator">
          <li class="next" data-page="2">Следующая</li>
          <li class="current first" data-page="1">1</li>
        </ul>
        <script>
        document.querySelector("li.next").addEventListener("click", function () {
          this.classList.add("disabled");
          document.querySelector("li.current").setAttribute("data-page", "2");
          document.querySelector(".primeDocument").remove();
          const card = document.createElement("div");
          card.className = "primeDocument";
          card.innerHTML = '<div class="documentTitle"><a href="/#/document/2">Вторая</a></div>';
          document.body.insertBefore(card, document.querySelector("ul.paginator"));
        });
        </script>
        """
    )
    parser = _parser(monkeypatch)
    html = await parser._collect_feed_pages(panel_page)
    assert "Первая" in html
    assert "Вторая" in html


@pytest.mark.asyncio
async def test_wait_for_filter_result_ignores_panel_reset_class(panel_page, monkeypatch):
    """Класс .resetFilter на панели есть до apply — это не «лента готова»."""
    parser = _parser(monkeypatch)
    await parser._wait_for_filter_result(panel_page)
    assert await panel_page.get_by_text("Лента отфильтрована").count() == 0
    assert await panel_page.locator("#panel-reset").count() == 1


@pytest.mark.asyncio
async def test_collect_feed_pages_stops_when_next_drops_filters(panel_page, monkeypatch):
    await panel_page.set_content(
        """
        <div>Лента отфильтрована</div>
        <div class="documentPrimeContainer">
          <div class="primeDocument"><div class="documentTitle"><a href="/#/document/1">Фильтр</a></div></div>
        </div>
        <ul class="paginator">
          <li class="next" data-page="2">Следующая</li>
          <li class="current" data-page="1">1</li>
        </ul>
        <script>
        document.querySelector("li.next").addEventListener("click", function () {
          document.body.innerHTML = '<div class="primeDocument"><div class="documentTitle"><a href="/#/document/2">Общая</a></div></div>';
        });
        </script>
        """
    )
    parser = _parser(monkeypatch)
    html = await parser._collect_feed_pages(panel_page)
    assert "Фильтр" in html
    assert "Общая" not in html


@pytest.mark.asyncio
async def test_empty_message_keeps_cards_if_both_present(panel_page, monkeypatch):
    await panel_page.set_content(
        """
        <div class="emptyMessage">Ничего не найдено.</div>
        <div class="primeDocument"><div class="documentTitle"><a href="/#/document/1">Живая</a></div></div>
        """
    )
    parser = _parser(monkeypatch)
    html = await parser._collect_feed_pages(panel_page)
    assert "Живая" in html


@pytest.mark.asyncio
async def test_empty_message_without_cards_is_empty_feed(panel_page, monkeypatch):
    await panel_page.set_content(
        """
        <div class="emptyMessage">Ничего не найдено.</div>
        """
    )
    parser = _parser(monkeypatch)
    html = await parser._collect_feed_pages(panel_page)
    assert html == ""
    assert parser._parse_html(html) == []
