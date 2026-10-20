"""Разбор HTML-каталога шаблонов договоров (topic 5703683).

Живая сверка 20.10.2026: `GET /v2/topic/5703683/html` отдаёт `items[]`,
а ссылки внутри `text` ведут на отдельные документы
`/#/document/{topic}/entry/0`, не на параграфы самого каталога.
`/html` и `/download` сидят в одной квоте экспорта (`topic/html`,
`topic/download` и соседние имена в `GET /v2/limits`).
`GET /v2/topic/{id}` — отдельная квота «информация о документе».
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

CATALOG_TOPIC = 5703683
DOCUMENT_PAGE_URL = "https://internet.garant.ru/#/document/{topic}/entry/0"
_DOCUMENT_HREF = re.compile(r"document/(\d+)")
_FORBIDDEN_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MAX_STEM_LENGTH = 120


@dataclass(frozen=True)
class TemplateRef:
    """Один шаблон из каталога: номер документа ГАРАНТ и подпись ссылки."""

    topic: int
    title: str


def template_page_url(topic: int) -> str:
    """Страница документа на сайте ГАРАНТ, с которой его открывают."""
    return DOCUMENT_PAGE_URL.format(topic=topic)


def parse_template_links(items: list, *, catalog_topic: int = CATALOG_TOPIC) -> list[TemplateRef]:
    """Уникальные topic в порядке появления. Сам каталог в список не входит."""
    seen: set[int] = set()
    refs: list[TemplateRef] = []
    for item in items:
        text = item.get("text") if isinstance(item, dict) else ""
        soup = BeautifulSoup(text or "", "html.parser")
        for anchor in soup.find_all("a", href=True):
            match = _DOCUMENT_HREF.search(str(anchor.get("href") or ""))
            if not match:
                continue
            topic = int(match.group(1))
            if topic == catalog_topic or topic in seen:
                continue
            title = anchor.get_text(" ", strip=True) or str(topic)
            seen.add(topic)
            refs.append(TemplateRef(topic=topic, title=title))
    return refs


def safe_filename(topic: int, title: str, extension: str = ".docx") -> str:
    """`{topic}_{название}` без символов, запрещённых в Windows, обрезка stem до 120."""
    cleaned = _FORBIDDEN_FILENAME.sub(" ", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    stem = f"{topic}_{cleaned}" if cleaned else str(topic)
    if len(stem) > _MAX_STEM_LENGTH:
        stem = stem[:_MAX_STEM_LENGTH].rstrip(" .")
    suffix = extension if extension.startswith(".") else f".{extension}"
    return f"{stem}{suffix}"
