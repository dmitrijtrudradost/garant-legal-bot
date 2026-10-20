from datetime import date, timedelta

import pytest

from core.intent_router import HELP_TEXT, IntentRouter

router = IntentRouter()


@pytest.mark.parametrize(
    "text,expected_topic_substring",
    [
        ("Предоставь мне изменения в законодательстве", "охранная деятельность"),
        ("Что нового по охране?", "охранная деятельность"),
        ("Есть изменения по налогам?", "Налоги"),
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
    assert any("охранная деятельность" in topic for topic in query.topic)
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
        ("охранные новости за 6 месяцев", 180),
        ("Охрана за полгода", 180),
        ("Охрана за год", 365),
    ],
)
def test_route_applies_period_from_text_to_date_from(text, expected_days):
    query = router.route(text)

    assert query is not None
    expected_date_from = date.today() - timedelta(days=expected_days)
    assert query.date_from == expected_date_from


def test_route_six_months_uses_security_preset_not_custom_topic():
    query = router.route("охранные новости за 6 месяцев")

    assert query is not None
    assert any("охранная деятельность" in topic for topic in query.topic)
    assert query.date_from == date.today() - timedelta(days=180)
    assert query.date_to == date.today()


def test_route_recognizes_button_labels():
    """Кнопки VK-клавиатуры (interfaces/vk/vk_interface.py) шлют такие тексты сообщением."""
    security = router.route("🛡 Охрана — месяц")
    main = router.route("📋 Главные новости — месяц")
    assert security is not None
    assert main is not None
    assert (security.date_to - security.date_from).days == 30
    assert (main.date_to - main.date_from).days == 30
    assert len(security.topic) == 1
    assert len(main.topic) > 1


def test_route_help_button_is_not_a_news_request():
    assert router.route("Справка") is None
    assert IntentRouter.is_help_request("Справка") is True


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


def test_is_help_request_exact_phrases():
    for phrase in ("справка", "помощь", "как пользоваться", "список сфер", "список фильтров"):
        assert IntentRouter.is_help_request(phrase) is True
    assert IntentRouter.is_help_request("📅 Свой период") is True
    assert IntentRouter.is_help_request("хочу свой период новостей") is True


def test_is_limits_request_exact_phrases():
    assert IntentRouter.is_limits_request("лимиты") is True
    assert IntentRouter.is_limits_request("Лимиты") is True
    assert IntentRouter.is_limits_request("остаток запросов") is True
    assert IntentRouter.is_limits_request("какие лимиты по охране") is False
    assert "остаток запросов" in HELP_TEXT


def test_template_command_exact_phrases():
    assert IntentRouter.template_command("шаблоны договоров") == ("list", "")
    assert IntentRouter.template_command("Шаблоны договоров") == ("list", "")
    assert IntentRouter.template_command("шаблон 1") == ("one", "1")
    assert IntentRouter.template_command("шаблон аренды офиса") == ("one", "аренды офиса")
    assert IntentRouter.template_command("какие шаблоны договоров") is None
    assert IntentRouter.template_command("шаблон") is None
    assert IntentRouter.template_command("сохранить") == ("save", "")
    assert IntentRouter.template_command("сохрани список") is None
    assert "сохранить" in HELP_TEXT


def test_is_custom_period_help_request_without_dates():
    assert IntentRouter.is_custom_period_help_request("📅 Свой период") is True
    assert IntentRouter.is_custom_period_help_request("хочу свой период новостей") is True


def test_is_custom_period_help_request_false_when_dates_present():
    # Даты уже указаны — это не просьба объяснить формат, а готовый запрос
    assert IntentRouter.is_custom_period_help_request("свой период 01.08.2026-06.09.2026") is False


def test_is_custom_period_help_request_false_for_unrelated_text():
    assert IntentRouter.is_custom_period_help_request("привет, как дела") is False


# -- Территория (REGION_KEYWORDS) ------------------------------------------------


def test_route_detects_moscow_territory_keyword():
    query = router.route("новости по охране в Москве")

    assert query is not None
    assert query.territory == "Москва"


@pytest.mark.parametrize("text", ["Что нового по охране?", "Есть изменения по налогам?"])
def test_route_without_region_keyword_leaves_territory_none(text):
    query = router.route(text)

    assert query is not None
    assert query.territory is None


# -- Произвольная тема в чате (дополнительно к ТЗ) -------------------------------


def test_route_recognizes_custom_topic_phrase():
    query = router.route("Новости по строительству")

    assert query is not None
    assert query.topic == ["строительству"]


def test_route_custom_topic_strips_trailing_period_clause():
    query = router.route("Что нового по строительству за месяц?")

    assert query is not None
    assert query.topic == ["строительству"]
    assert query.date_from == date.today() - timedelta(days=30)


def test_route_security_keyword_takes_priority_over_custom_topic_pattern():
    """"новости по охране" совпадает и с SECURITY_KEYWORDS, и с CUSTOM_TOPIC_PATTERN —
    готовый пресет должен выиграть, а не произвольная тема "охране"."""
    query = router.route("новости по охране")

    assert query is not None
    assert any("охранная деятельность" in topic for topic in query.topic)


@pytest.mark.parametrize(
    "text,expected_topic",
    [
        ("Воздушный транспорт за период 01.08.2026-06.09.2026", "воздушный транспорт"),
        ("Новости из сферы строительство за 01.08.2026-06.09.2026", "строительство"),
        ("по образованию за неделю", "образованию"),
        (
            "Предоставь новости в сфере Образования за период 01.01.2026-10.09.2026",
            "образования",
        ),
        ("Новости в сфере Легкая промышленность за 6 месяцев", "легкая промышленность"),
    ],
)
def test_route_named_sphere_becomes_custom_topic(text, expected_topic):
    query = router.route(text)

    assert query is not None
    assert query.topic == [expected_topic]


def test_route_dates_without_sphere_use_all_main_preset():
    query = router.route("01.08.2026-06.09.2026")

    assert query is not None
    assert any("охранная деятельность" in topic for topic in query.topic)
    assert any("Налоги" in topic for topic in query.topic)


def test_route_main_news_button_uses_all_main_preset():
    query = router.route("📋 Главные новости — месяц")

    assert query is not None
    assert any("охранная деятельность" in topic for topic in query.topic)
    assert any("Налоги" in topic for topic in query.topic)
    assert query.date_from == date.today() - timedelta(days=30)


def test_route_security_in_sphere_phrase_still_uses_preset():
    query = router.route(
        "Предоставь новости в сфере охранных услуг за период 01.01.2026-10.09.2026"
    )

    assert query is not None
    assert any("охранная деятельность" in topic for topic in query.topic)


# -- Пагинация «ещё» (точное совпадение, не подстрока) ---------------------------


@pytest.mark.parametrize(
    "text",
    ["ещё", "еще", "дальше", "Показать ещё", "➡️ Показать ещё", "показать все"],
)
def test_is_show_more_request_exact_phrases(text):
    assert IntentRouter.is_show_more_request(text) is True


def test_is_show_more_request_false_for_news_phrase_containing_esche():
    """«покажи ещё новости по охране» — новый запрос, не пагинация."""
    assert IntentRouter.is_show_more_request("покажи ещё новости по охране") is False
    assert router.route("покажи ещё новости по охране за месяц") is not None


def test_is_show_more_request_false_for_unrelated_text():
    assert IntentRouter.is_show_more_request("ещё раз привет") is False
    assert IntentRouter.is_show_more_request("привет, как дела") is False


# -- AI-шлюз (уровень 2) ---------------------------------------------------------


class RecordingAIClient:
    def __init__(self, reply: str | BaseException):
        self.reply = reply
        self.calls: list[dict] = []

    async def complete(self, messages, *, temperature=None, max_tokens=None):
        self.calls.append(
            {"messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        )
        if isinstance(self.reply, BaseException):
            raise self.reply
        return self.reply


def test_looks_like_news_for_ai_uses_legal_stems_only():
    router_ai = IntentRouter()
    assert router_ai.looks_like_news_for_ai("что поменялось в нормативке за месяц") is True
    assert router_ai.looks_like_news_for_ai("привет, как дела") is False
    assert router_ai.looks_like_news_for_ai("у меня новый сотрудник") is False


@pytest.mark.asyncio
async def test_classify_via_ai_does_not_call_client_without_gate_stem():
    client = RecordingAIClient('{"is_news": true, "topic": "general"}')
    router_ai = IntentRouter(ai_client=client)

    result = await router_ai.classify_via_ai("привет, как дела")

    assert result is None
    assert client.calls == []


@pytest.mark.asyncio
async def test_classify_via_ai_does_not_call_client_when_ai_missing():
    router_ai = IntentRouter()
    assert await router_ai.classify_via_ai("что поменялось в нормативке") is None


@pytest.mark.asyncio
async def test_classify_via_ai_builds_query_from_valid_json():
    payload = (
        '{"is_news": true, "topic": "general", "custom_topic": null, '
        '"period_days": 30, "date_from": null, "date_to": null, "territory": null}'
    )
    client = RecordingAIClient(payload)
    router_ai = IntentRouter(ai_client=client)

    query = await router_ai.classify_via_ai(
        "подскажи, что поменялось в нормативке за последний месяц"
    )

    assert query is not None
    assert query.date_from == date.today() - timedelta(days=30)
    assert any("охранная деятельность" in topic for topic in query.topic)
    assert any("Налоги" in topic for topic in query.topic)
    assert client.calls[0]["temperature"] == 0
    assert client.calls[0]["max_tokens"] == 200


@pytest.mark.asyncio
async def test_classify_via_ai_security_topic_and_territory():
    payload = '{"is_news": true, "topic": "security", "period_days": 7, "territory": "Москва"}'
    router_ai = IntentRouter(ai_client=RecordingAIClient(payload))

    query = await router_ai.classify_via_ai("актуальные приказы по охране в Москве")

    assert query is not None
    assert any("охранная деятельность" in topic for topic in query.topic)
    assert query.territory == "Москва"


@pytest.mark.asyncio
async def test_classify_via_ai_strips_json_fence_and_uses_custom_topic():
    payload = (
        '```json\n{"is_news": true, "topic": "custom", '
        '"custom_topic": "строительство", "period_days": 7}\n```'
    )
    router_ai = IntentRouter(ai_client=RecordingAIClient(payload))

    query = await router_ai.classify_via_ai("что нового в нормативных актах по стройке")

    assert query is not None
    assert query.topic == ["строительство"]


@pytest.mark.asyncio
async def test_classify_via_ai_returns_none_when_is_news_false():
    router_ai = IntentRouter(ai_client=RecordingAIClient('{"is_news": false}'))
    assert await router_ai.classify_via_ai("разбери этот приказ как юрист") is None


@pytest.mark.asyncio
async def test_classify_via_ai_returns_none_on_invalid_json():
    router_ai = IntentRouter(ai_client=RecordingAIClient("это не json"))
    assert await router_ai.classify_via_ai("актуальные постановления") is None


@pytest.mark.asyncio
async def test_classify_via_ai_returns_none_on_ai_client_error():
    from core.ai_client import AIClientError

    router_ai = IntentRouter(ai_client=RecordingAIClient(AIClientError("нет связи")))
    assert await router_ai.classify_via_ai("актуальные постановления") is None
