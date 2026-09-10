"""Тесты core.news.category_tree.resolve_categories — чистые функции, без HTTP/асинхронности."""

from core.news import category_tree


def test_resolve_categories_finds_topic_within_named_branch(garant_api_categories_branched_sample):
    categories = garant_api_categories_branched_sample["categories"]

    ids = category_tree.resolve_categories(
        categories, ["Охранная деятельность"], branch=category_tree.BRANCH_INTEREST
    )

    assert ids == [101]


def test_resolve_categories_finds_territory_leaf_within_branch(garant_api_categories_branched_sample):
    categories = garant_api_categories_branched_sample["categories"]

    ids = category_tree.resolve_categories(categories, ["Москва"], branch=category_tree.BRANCH_INFO_TYPE)

    assert ids == [142]


def test_resolve_categories_finds_info_type_node_within_branch(garant_api_categories_branched_sample):
    categories = garant_api_categories_branched_sample["categories"]

    # Только "Федеральное" (без "законодательство") — иначе стем "законодательство"
    # совпадёт и с "Региональное законодательство" (id 33), см. presets.py и
    # предупреждение о коротких/общих стемах в докстроке category_tree.py.
    ids = category_tree.resolve_categories(categories, ["Федеральное"], branch=category_tree.BRANCH_INFO_TYPE)

    assert ids == [10]


def test_resolve_categories_branch_missing_falls_back_to_whole_tree(garant_api_categories_sample):
    # Старая плоская фикстура — top-level узлов "Вид информации"/"Сфера интересов" вообще нет.
    categories = garant_api_categories_sample["categories"]

    ids = category_tree.resolve_categories(
        categories, ["Охранная деятельность"], branch=category_tree.BRANCH_INTEREST
    )

    assert ids == [101]  # branch не найден -> fallback на обход всего дерева


def test_resolve_categories_without_branch_searches_whole_tree(garant_api_categories_branched_sample):
    categories = garant_api_categories_branched_sample["categories"]

    ids = category_tree.resolve_categories(categories, ["Москва"], branch=None)

    assert ids == [142]


def test_resolve_categories_no_match_returns_empty_list(garant_api_categories_branched_sample):
    categories = garant_api_categories_branched_sample["categories"]

    ids = category_tree.resolve_categories(
        categories, ["Экология и природопользование"], branch=category_tree.BRANCH_INTEREST
    )

    assert ids == []  # без root-fallback внутри самой функции — это забота вызывающего кода


def test_extract_stems_drops_generic_blocklisted_word():
    assert "деятельность" not in category_tree.extract_stems("Частная сыскная и охранная деятельность")


def test_extract_stems_keeps_blocklisted_word_if_it_is_the_only_word():
    # Иначе фраза, состоящая ровно из одного общего слова, потеряла бы все стемы.
    assert category_tree.extract_stems("деятельность") == ["деятельность"]


def test_resolve_categories_ignores_generic_activity_word_false_positives():
    """Регрессия на реальный инцидент 09.09.2026: тема "...охранная деятельность"
    резолвилась в 10 несвязанных узлов из-за общего слова "деятельность"
    (см. README, раздел "Найденный и исправленный баг фильтрации")."""
    categories = [
        {
            "text": "Сфера интересов",
            "id": 1,
            "children": [
                {"text": "Частная сыскная и охранная деятельность", "id": 137, "children": []},
                {"text": "Страховая деятельность", "id": 20, "children": []},
                {"text": "Научная деятельность", "id": 84, "children": []},
                {"text": "Охрана труда", "id": 260, "children": []},
            ],
        }
    ]

    ids = category_tree.resolve_categories(
        categories, ["Частная сыскная и охранная деятельность"], branch=category_tree.BRANCH_INTEREST
    )

    assert ids == [137]  # не [20, 84, 137, 260]
