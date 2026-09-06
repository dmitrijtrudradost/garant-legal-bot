"""Готовые пресеты фильтров NewsQuery (см. ТЗ, раздел 3.3).

Это конкретные, готовые к использованию наборы значений, а не абстрактные
примеры — IntentRouter подставляет их напрямую при построении запроса.
"""

from __future__ import annotations

from datetime import date, timedelta

from core.models import NewsQuery

# Тематики (рубрикатор ГАРАНТ) для охранной деятельности.
_SECURITY_TOPICS = [
    "Охранная деятельность",
    "Лицензирование охранной деятельности",
    "Применение оружия и спецсредств",
    "Трудовые отношения (охрана)",
]
_SECURITY_AUTHORITIES = ["Росгвардия", "МВД России"]

# Тематики для налогов и бухучёта.
_TAX_ACCOUNTING_TOPICS = [
    "Налоги, сборы",
    "Страховые взносы",
    "Бухгалтерский учёт",
    "Отчётность",
]
_TAX_ACCOUNTING_AUTHORITIES = ["ФНС России", "Минфин России"]

DEFAULT_LOOKBACK_DAYS = 7


def _default_range(date_from: date | None = None, date_to: date | None = None) -> tuple[date, date]:
    resolved_to = date_to or date.today()
    resolved_from = date_from or (resolved_to - timedelta(days=DEFAULT_LOOKBACK_DAYS))
    return resolved_from, resolved_to


def preset_security_org(*, date_from: date | None = None, date_to: date | None = None) -> NewsQuery:
    """«Охранная деятельность» — лицензирование, спецсредства, трудовые отношения охранников."""
    d_from, d_to = _default_range(date_from, date_to)
    return NewsQuery(
        date_from=d_from,
        date_to=d_to,
        topic=list(_SECURITY_TOPICS),
        authority=list(_SECURITY_AUTHORITIES),
        territory="федеральный",
    )


def preset_tax_accounting(*, date_from: date | None = None, date_to: date | None = None) -> NewsQuery:
    """«Налоги и бухучёт» — налоги, сборы, страховые взносы, бухучёт, отчётность."""
    d_from, d_to = _default_range(date_from, date_to)
    return NewsQuery(
        date_from=d_from,
        date_to=d_to,
        topic=list(_TAX_ACCOUNTING_TOPICS),
        authority=list(_TAX_ACCOUNTING_AUTHORITIES),
        territory="федеральный",
    )


def preset_all_main(*, date_from: date | None = None, date_to: date | None = None) -> NewsQuery:
    """«Главные новости по всем сферам охранной организации за прошедшее время».

    Объединение тем/органов PRESET_SECURITY_ORG + PRESET_TAX_ACCOUNTING,
    без узкой темы (общие «главные новости законодательства»).
    date_from по умолчанию — DEFAULT_LOOKBACK_DAYS дней назад, date_to — сегодня.
    """
    d_from, d_to = _default_range(date_from, date_to)
    return NewsQuery(
        date_from=d_from,
        date_to=d_to,
        topic=[*_SECURITY_TOPICS, *_TAX_ACCOUNTING_TOPICS],
        authority=[*_SECURITY_AUTHORITIES, *_TAX_ACCOUNTING_AUTHORITIES],
        territory="федеральный",
    )


# Именованные константы — как заявлено в ТЗ (PRESET_SECURITY_ORG и т.д.).
# Это функции-фабрики (а не застывшие объекты), т.к. date_from/date_to
# должны каждый раз пересчитываться относительно "сегодня".
PRESET_SECURITY_ORG = preset_security_org
PRESET_TAX_ACCOUNTING = preset_tax_accounting
PRESET_ALL_MAIN = preset_all_main
