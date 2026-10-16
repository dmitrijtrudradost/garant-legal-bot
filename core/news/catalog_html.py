"""Самодостаточный HTML-каталог сфер и фильтров ГАРАНТ ПРАЙМ — под смартфон.

HTML и PDF лежат в docs/ (`garant-sfery-i-filtry.html` / `.pdf`).
В VK HTML печатается в PDF (`html_to_pdf`): документы сообщества не принимают `.html`.
"""

from __future__ import annotations

import html as html_lib
from collections.abc import Sequence
from pathlib import Path

from core.news.category_tree import BRANCH_INFO_TYPE, BRANCH_INTEREST, find_branch_children

CATALOG_TITLE = "ГАРАНТ ПРАЙМ — сферы и фильтры"
CATALOG_HTML_FILENAME = "garant-sfery-i-filtry.html"
CATALOG_PDF_FILENAME = "garant-sfery-i-filtry.pdf"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CATALOG_HTML_PATH = PROJECT_ROOT / "docs" / CATALOG_HTML_FILENAME
CATALOG_PDF_PATH = PROJECT_ROOT / "docs" / CATALOG_PDF_FILENAME

_HELP_HTML = """
<p>Напишите боту тему и период — или нажмите кнопку в чате. Кнопки — быстрый путь к частым запросам.</p>
<p><strong>Приоритет темы.</strong> Сначала охрана (слова «охрана» или «лицензирование»). Затем названная сфера из этого списка. Если сфера не названа — главные новости по основным сферам.</p>
<p><strong>Период от сегодня:</strong> «за неделю», «за месяц», «за 6 месяцев», «за год».</p>
<p><strong>Свой период.</strong> Даты в одном сообщении со сферой: ДД.ММ.ГГГГ-ДД.ММ.ГГГГ, например 01.08.2026-06.09.2026.</p>
<p>«ещё» — следующие 10 новостей из уже найденного списка.</p>
<p>«лимиты» или «остаток запросов» — сколько вызовов API ГАРАНТ осталось в этом месяце.</p>
<p><strong>Примеры запросов.</strong></p>
<ol>
<li>Охранные новости за месяц</li>
<li>Новости в сфере образование за 6 месяцев</li>
<li>Новости в сфере строительство за период 01.08.2026-10.09.2026</li>
<li>Главные новости за неделю</li>
</ol>
"""

_PAGE_CSS = """
:root {
  --bg: #F7F1E8;
  --paper: #FFFCF7;
  --ink: #2C2416;
  --muted: #5C5346;
  --accent: #8B5A3C;
  --line: #E4D5C1;
}
* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  font-size: 17px;
  line-height: 1.45;
}
main {
  max-width: 40rem;
  margin: 0 auto;
  padding: 1.25rem 1.1rem 2.5rem;
  background: var(--paper);
  min-height: 100vh;
}
h1 {
  margin: 0 0 0.75rem;
  font-size: 1.45rem;
  font-weight: 650;
  color: var(--accent);
  line-height: 1.3;
}
h2 {
  margin: 1.75rem 0 0.65rem;
  padding-top: 0.85rem;
  border-top: 1px solid var(--line);
  font-size: 1.15rem;
  font-weight: 650;
  color: var(--accent);
}
p { margin: 0 0 0.8rem; color: var(--ink); }
ul {
  margin: 0.2rem 0 0.6rem;
  padding: 0 0 0 1.15rem;
}
li {
  margin: 0.35rem 0;
  padding: 0.05rem 0;
}
li ul { margin-top: 0.25rem; }
.muted { color: var(--muted); font-size: 0.95rem; }
@media print {
  html, body { background: var(--bg); print-color-adjust: exact; -webkit-print-color-adjust: exact; }
  main { min-height: auto; }
}
"""


def render_catalog_html(categories: Sequence[dict]) -> str:
    """HTML со справкой, деревом «Сфера интересов» и фильтрами «Вид информации»."""
    interest = find_branch_children(list(categories), BRANCH_INTEREST) or []
    info_type = find_branch_children(list(categories), BRANCH_INFO_TYPE) or []
    interest_html = _render_nodes(interest) or "<p class=\"muted\">Список сфер пуст.</p>"
    filters_html = _render_nodes(info_type) or "<p class=\"muted\">Список фильтров пуст.</p>"
    title = html_lib.escape(CATALOG_TITLE)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="ru">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{title}</title>\n"
        f"<style>{_PAGE_CSS}</style>\n"
        "</head>\n"
        "<body>\n"
        "<main>\n"
        f"<h1>{title}</h1>\n"
        "<h2>Справка</h2>\n"
        f"{_HELP_HTML}"
        "<h2>Сферы интересов</h2>\n"
        f"{interest_html}\n"
        "<h2>Фильтры</h2>\n"
        '<p class="muted">Вид информации и регионы.</p>\n'
        f"{filters_html}\n"
        "</main>\n"
        "</body>\n"
        "</html>\n"
    )


def save_catalog_html(html: str, path: Path | None = None) -> Path:
    """Пишет каталог в docs/, чтобы файл можно было открыть локально."""
    target = path or CATALOG_HTML_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding="utf-8")
    return target


def save_catalog_pdf(pdf_bytes: bytes, path: Path | None = None) -> Path:
    """Пишет PDF-каталог в docs/ рядом с HTML."""
    target = path or CATALOG_PDF_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(pdf_bytes)
    return target


def _render_nodes(nodes: Sequence[dict]) -> str:
    if not nodes:
        return ""
    items: list[str] = []
    for node in nodes:
        title = html_lib.escape(str(node.get("text") or "").strip() or "Без названия")
        children = node.get("children") or []
        inner = _render_nodes(children)
        items.append(f"<li>{title}{inner}</li>")
    return "<ul>" + "".join(items) + "</ul>"


async def html_to_pdf(html: str) -> bytes:
    """Печатает самодостаточный HTML в PDF через Chromium (Playwright).

    VK не принимает HTML как документ сообщества (wrong_file / 130), PDF — принимает.
    """
    from playwright.async_api import async_playwright

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            await page.set_content(html, wait_until="load")
            return await page.pdf(
                format="A4",
                print_background=True,
                margin={"top": "12mm", "bottom": "14mm", "left": "12mm", "right": "12mm"},
            )
        finally:
            await browser.close()
