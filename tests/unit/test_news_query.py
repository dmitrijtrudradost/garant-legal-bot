from datetime import date

from core.news.presets import PRESET_ALL_MAIN, PRESET_SECURITY_ORG, PRESET_TAX_ACCOUNTING
from core.news.query import NewsQuery


def test_news_query_requires_date_range():
    query = NewsQuery(date_from=date(2026, 1, 1), date_to=date(2026, 1, 8))
    assert query.date_from == date(2026, 1, 1)
    assert query.date_to == date(2026, 1, 8)
    assert query.topic is None


def test_news_query_optional_fields_default_to_none():
    query = NewsQuery(date_from=date.today(), date_to=date.today())
    assert query.authority is None
    assert query.info_type is None
    assert query.territory is None


def test_preset_security_org_has_relevant_topics():
    query = PRESET_SECURITY_ORG()
    assert query.date_from < query.date_to or query.date_from == query.date_to
    assert any("Охранная" in topic for topic in query.topic)


def test_preset_tax_accounting_has_relevant_topics():
    query = PRESET_TAX_ACCOUNTING()
    assert any("Налог" in topic for topic in query.topic)


def test_preset_all_main_combines_both():
    query = PRESET_ALL_MAIN()
    assert any("Охранная" in topic for topic in query.topic)
    assert any("Налог" in topic for topic in query.topic)
