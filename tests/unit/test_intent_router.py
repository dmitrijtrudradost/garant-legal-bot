from datetime import date, timedelta

import pytest

from core.intent_router import IntentRouter

router = IntentRouter()


@pytest.mark.parametrize(
    "text,expected_topic_substring",
    [
        ("Предоставь мне изменения в законодательстве", "Охранная деятельность"),
        ("Что нового по охране?", "Охранная деятельность"),
        ("Есть изменения по налогам?", "Налоги, сборы"),
        ("Что там по бухучёту?", "Бухгалтерский учёт"),
    ],
)
def test_route_recognizes_news_requests(text, expected_topic_substring):
    query = router.route(text)

    assert query is not None
    assert any(expected_topic_substring in topic for topic in query.topic)


def test_route_general_news_request_uses_all_main_preset():
    query = router.route("Какие главные новости законодательства?")

    assert query is not None
    assert any("Охранная деятельность" in topic for topic in query.topic)
    assert any("Налоги" in topic for topic in query.topic)


@pytest.mark.parametrize(
    "text",
    [
        "что нового в законе",  # единственное число — раньше не распознавалось
        "какие новости по закону",
        "изменения в законе",
        "что нового в законодательстве",
    ],
)
def test_route_recognizes_law_news_regardless_of_word_form(text):
    """Регресс: раньше срабатывала только точная фраза "что нового в законах" (мн. ч.)."""
    assert router.route(text) is not None


def test_route_returns_none_for_regular_dialogue():
    assert router.route("привет, как дела") is None
    assert router.route("какой сегодня хороший новый день") is None  # "нов" без "закон" — не новости


@pytest.mark.parametrize(
    "text,expected_days",
    [
        ("Охрана: за неделю", 7),
        ("Охрана: за месяц", 30),
        ("Охрана: за 3 мес.", 90),
        ("Что нового по охране в квартале?", 90),
        ("Что нового по охране?", 7),  # период не указан — значение по умолчанию
    ],
)
def test_route_applies_period_from_text_to_date_from(text, expected_days):
    query = router.route(text)

    assert query is not None
    expected_date_from = date.today() - timedelta(days=expected_days)
    assert query.date_from == expected_date_from


def test_route_recognizes_button_labels():
    """Кнопки VK-клавиатуры (interfaces/vk/vk_interface.py) шлют такие тексты сообщением."""
    for label in ["🛡 Охрана — месяц", "📋 Главные новости — месяц"]:
        assert router.route(label) is not None, f"кнопка {label!r} не распознана как новостной запрос"


@pytest.mark.parametrize(
    "text,expected_from,expected_to",
    [
        ("01.08.2026-06.09.2026", date(2026, 8, 1), date(2026, 9, 6)),
        ("Охрана 01.08.2026-06.09.2026", date(2026, 8, 1), date(2026, 9, 6)),
        ("даты с 01.08.2026 – 06.09.2026 пожалуйста", date(2026, 8, 1), date(2026, 9, 6)),
        ("06.09.2026-01.08.2026", date(2026, 8, 1), date(2026, 9, 6)),  # даты переставлены — сортируются сами
    ],
)
def test_route_parses_custom_date_range_from_text(text, expected_from, expected_to):
    query = router.route(text)

    assert query is not None
    assert query.date_from == expected_from
    assert query.date_to == expected_to


def test_route_ignores_invalid_custom_date_range():
    # 31 февраля не существует — считаем, что дат нет, обычный диалог
    assert router.route("31.02.2026-01.03.2026") is None


def test_is_custom_period_help_request_without_dates():
    assert IntentRouter.is_custom_period_help_request("📅 Свой период") is True
    assert IntentRouter.is_custom_period_help_request("хочу свой период новостей") is True


def test_is_custom_period_help_request_false_when_dates_present():
    # Даты уже указаны — это не просьба объяснить формат, а готовый запрос
    assert IntentRouter.is_custom_period_help_request("свой период 01.08.2026-06.09.2026") is False


def test_is_custom_period_help_request_false_for_unrelated_text():
    assert IntentRouter.is_custom_period_help_request("привет, как дела") is False
