"""Резолюция дерева категорий ГАРАТ Коннект (`GET /v2/prime`) в ID.

Вынесено из `parser_api.py` в отдельный модуль чистых функций (см. ТЗ
`tz/tz-garant-news-filtering.md`, раздел 3.3): форма дерева категорий и
поиск по нему — это знание о предметной области ГАРАНТа, не зависящее от
того, как дерево получено (HTTP + кэш — это забота `GarantApiParser`).
Здесь всё тестируется без HTTP-моков и без класса-парсера.

Ветки дерева (подтверждено живым вызовом `GET /v2/prime` 09.09.2026,
см. README, раздел «Модуль новостей ГАРАНТ ПРАЙМ»):

- **«Вид информации»** — федеральное/региональное законодательство,
  судебная практика; территория (например, «г.Москва») лежит вложенно
  внутри узла «Региональное законодательство» этой же ветки, а не как
  отдельный параметр API.
- **«Сфера интересов»** — предметные темы («Частная сыскная и охранная
  деятельность», «Налоги» и т.п.) — сюда попадают темы пресетов.

Критическое правило ГАРАНТа (подтверждено дословно в документации,
см. ТЗ раздел 1.2): категории из ДВУХ разных веток в одном вызове
`POST /v2/prime/create-news` дают пересечение (AND), а не объединение —
для объединения нужно два отдельных вызова. Это сама функция резолюции
не решает — она только отвечает на вопрос "какие ID из ЭТОЙ ветки
подходят"; вызывающий код (`GarantApiParser`) решает, сколько вызовов
делать и как объединять результаты.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence

BRANCH_INFO_TYPE = "Вид информации"
BRANCH_INTEREST = "Сфера интересов"

STEM_MIN_LENGTH = 4
"""Минимальная длина слова, чтобы считаться значимой "основой" при
сопоставлении с деревом категорий — отсекает короткие служебные слова.
Осторожность: слишком короткие/общие слова (например, "охрана" отдельно)
дают ложные срабатывания на непричастные узлы ("Охрана труда", "Охрана
здоровья населения") — подтверждено живым деревом 09.09.2026, см. README
и `presets.py` (там из-за этого не используется голое слово "охрана" как
единственный признак темы)."""

GENERIC_STEM_BLOCKLIST = {"деятельность"}
"""Слова, которые сами по себе НЕ считаются значимой "основой" — несмотря
на длину ≥STEM_MIN_LENGTH, они встречаются как общий суффикс в десятках
несвязанных узлов дерева категорий (например, "деятельность" — в
"Страховая деятельность", "Научная деятельность", "Риэлтерская
деятельность" и т.п.) и при OR-сопоставлении слов внутри одной фразы дают
массовые ложные совпадения — подтверждено живым деревом 09.09.2026 (см.
ТЗ tz-garant-news-filtering.md, реальный баг с пресетом безопасности,
резолвившимся в 10 несвязанных узлов вместо 1). Отбрасываются только если
после этого у фразы остаётся хотя бы одно значимое слово — иначе (фраза
состоит ровно из одного такого слова) отбрасывать нечем, оставляем как есть."""


def extract_stems(text: str) -> list[str]:
    """Слова текста (от STEM_MIN_LENGTH символов) как "основы" для сопоставления —
    та же идиома частичного совпадения, что уже используется в IntentRouter.

    Общие слова из GENERIC_STEM_BLOCKLIST отбрасываются (см. её докстроку) —
    если это не оставляет фразу совсем без значимых слов."""
    words = [word for word in re.findall(r"[а-яёa-z]+", text.lower()) if len(word) >= STEM_MIN_LENGTH]
    filtered = [word for word in words if word not in GENERIC_STEM_BLOCKLIST]
    return filtered or words


def walk_nodes(nodes: list[dict]) -> Iterator[tuple[str, int]]:
    """Рекурсивно обходит узлы дерева произвольной глубины, отдавая (text, id) для каждого узла."""
    for node in nodes:
        yield node.get("text", ""), node.get("id")
        children = node.get("children") or []
        if children:
            yield from walk_nodes(children)


def find_branch_children(tree_categories: list[dict], branch: str) -> list[dict] | None:
    """Ищет топ-узел дерева с text == branch (без учёта регистра/пробелов) и
    возвращает его children. None, если такого топ-узла нет вообще —
    это и есть триггер branch-fallback в `resolve_categories`."""
    normalized_branch = branch.strip().lower()
    for node in tree_categories:
        if node.get("text", "").strip().lower() == normalized_branch:
            return node.get("children") or []
    return None


def resolve_categories(
    tree_categories: list[dict],
    keywords: Sequence[str],
    *,
    branch: str | None = None,
) -> list[int]:
    """ID узлов дерева, чьё название пересекается по основам с keywords.

    - `branch=None` -> обход всего дерева как есть.
    - `branch=<имя>` и такой топ-узел найден -> обход ТОЛЬКО его children
      (сам топ-узел — это ось, а не категория, в фильтр не попадает).
    - `branch=<имя>`, но топ-узла с таким названием нет (например, старая
      плоская тестовая фикстура без веток вообще) -> fallback: обход всего
      дерева, как если бы branch=None. Единственный механизм обратной
      совместимости со старыми плоскими деревьями/тестами.
    - Ничего не найдено -> `[]`. Fallback на "все корневые ID" сюда
      сознательно НЕ входит — у `topic`/`territory`/`info_type` разный смысл
      отсутствия совпадения, это решает вызывающий код (`GarantApiParser`).
    """
    if not keywords:
        return []

    if branch is not None:
        branch_children = find_branch_children(tree_categories, branch)
        nodes_pool = branch_children if branch_children is not None else tree_categories
    else:
        nodes_pool = tree_categories

    all_nodes = list(walk_nodes(nodes_pool))
    matched: set[int] = set()
    for keyword in keywords:
        stems = extract_stems(keyword)
        if not stems:
            continue
        grounded = [stem for stem in stems if any(stem_hits_text(stem, text) for text, _ in all_nodes)]
        if not grounded:
            continue
        for text, node_id in all_nodes:
            # Одна фраза — AND по стемам: «воздушный транспорт» не должен
            # зацепить все виды транспорта из-за общего слова «транспорт».
            # Несколько ключей пресета по-прежнему объединяются (OR снаружи).
            # Стемы, которые не бьются ни в один узел («предоставь»), отброшены.
            if all(stem_hits_text(stem, text) for stem in grounded):
                matched.add(node_id)

    return sorted(matched)


def stem_hits_text(stem: str, text: str) -> bool:
    """Совпадение основы с названием узла: подстрока или общая основа с отличающимся окончанием."""
    stem_n = _fold_yo(stem)
    text_n = _fold_yo(text)
    if stem_n in text_n:
        return True
    for word in re.findall(r"[а-яa-z]+", text_n):
        if len(word) < STEM_MIN_LENGTH:
            continue
        if stem_n in word or word in stem_n:
            return True
        common = 0
        for left, right in zip(stem_n, word):
            if left != right:
                break
            common += 1
        shorter = min(len(stem_n), len(word))
        if common >= STEM_MIN_LENGTH and common >= shorter - 1:
            return True
    return False


def _fold_yo(text: str) -> str:
    return text.lower().replace("ё", "е")
