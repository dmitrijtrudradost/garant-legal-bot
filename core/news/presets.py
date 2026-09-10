"""Готовые пресеты фильтров NewsQuery (см. ТЗ tz-garant-api-dual-mode.md, раздел 3.3,
и tz-garant-news-filtering.md, разделы 2-3.3).

Это конкретные, готовые к использованию наборы значений, а не абстрактные
примеры — IntentRouter подставляет их напрямую при построении запроса.
Темы (`topic`) резолвятся в ID дерева категорий ГАРАНТ уже на стороне
`GarantApiParser` (`core/news/category_tree.py`) — здесь только текстовые
ключевые слова, подобранные и сверенные с живым деревом категорий
(`GET /v2/prime`, 09.09.2026, см. README).

**Почему `authority` не заполняется.** Раньше пресеты заполняли `authority`
(например, "Росгвардия"/"МВД России"), но ни один парсер это поле не читает
— у метода «Лента Прайм» просто нет такого параметра (см. докстроку
`NewsQuery` в `core/models.py`). Заполнять поле, которое никто не применяет,
вводит в заблуждение точностью, которой нет — убрано (ТЗ
tz-garant-news-filtering.md, раздел 3.5).

**Почему `territory="федеральный"` просто убрано, а не заменено на
`info_type=[...]`.** Первая попытка исправления (09.09.2026) заменила
`territory="федеральный"` на `info_type=["Федеральное"]` — по уточнённой
живым деревом категорий модели «федеральный/региональный» это правильная
ось («Вид информации»), но результат оказался хуже прежнего: `GarantApiParser`
при нескольких осях делает **два отдельных вызова и ОБЪЕДИНЯЕТ результаты**
(union, см. докстроку `GarantApiParser`) — а "Федеральное законодательство"
это огромная категория (туда попадает почти любой новый федеральный акт
независимо от темы), поэтому объединение с ней не сужало выдачу, а
фактически СВОДИЛО НА НЕТ фильтр по теме (подтверждено реальным диалогом
09.09.2026 — запрос про охранную деятельность вернул 147 новостей обо всём
подряд). Поэтому пресеты по умолчанию **не ограничивают `info_type` вообще**
— только `topic`. Территория/вид информации остаются доступны через явный
пользовательский ввод (`IntentRouter._detect_territory`) — там та же
осторожность применима: объединение с широкой веткой "Вид информации"
расширяет, а не сужает выдачу, это сознательный компромисс TЗ
(tz-garant-news-filtering.md, раздел 3.3.4), а не баг.
"""

from __future__ import annotations

from datetime import date, timedelta

from core.models import NewsQuery

# Тематики (рубрикатор ГАРАНТ) для охранной деятельности — сверено с живым
# деревом категорий (ветка "Сфера интересов", 09.09.2026): точный узел —
# "Частная сыскная и охранная деятельность" (в дереве вложен под "Суды,
# адвокатура, нотариат, правоохранительные органы"). Только этот один узел —
# специально НЕ включена "Охрана правопорядка и общественной безопасности"
# (id 101 в живом дереве): это про публичную правоохранительную деятельность
# государства, а не про бизнес частных охранных организаций (не то, что
# нужно юристу по охранным организациям), и вдобавок сама эта фраза
# начинается с общего слова "охрана" (без суффикса "-ная"), которое ложно
# совпадает с "Охрана труда"/"Охрана здоровья населения" и т.п. Реальный
# инцидент 09.09.2026 (см. tz-garant-news-filtering.md): с обоими словами
# тема резолвилась в 10 несвязанных узлов вместо одного нужного — оставлен
# только точный, однозначный узел.
_SECURITY_TOPICS = [
    "Частная сыскная и охранная деятельность",
]

# Тематики для налогов и бухучёта — сверено с живым деревом (ветка "Сфера
# интересов"): "Налоги" и "Бухгалтерский учет" — точные узлы; "Страховые
# взносы"/"Отчётность" оставлены как дополнительные ключевые слова (частично
# совпадают по основам с реальными вложенными узлами, не мешают).
_TAX_ACCOUNTING_TOPICS = [
    "Налоги",
    "Страховые взносы",
    "Бухгалтерский учёт",
    "Отчётность",
]

DEFAULT_LOOKBACK_DAYS = 7


def _default_range(date_from: date | None = None, date_to: date | None = None) -> tuple[date, date]:
    resolved_to = date_to or date.today()
    resolved_from = date_from or (resolved_to - timedelta(days=DEFAULT_LOOKBACK_DAYS))
    return resolved_from, resolved_to


def preset_security_org(*, date_from: date | None = None, date_to: date | None = None) -> NewsQuery:
    """«Охранная деятельность» — частная охранная/сыскная деятельность, охрана правопорядка."""
    d_from, d_to = _default_range(date_from, date_to)
    return NewsQuery(date_from=d_from, date_to=d_to, topic=list(_SECURITY_TOPICS))


def preset_tax_accounting(*, date_from: date | None = None, date_to: date | None = None) -> NewsQuery:
    """«Налоги и бухучёт» — налоги, сборы, страховые взносы, бухучёт, отчётность."""
    d_from, d_to = _default_range(date_from, date_to)
    return NewsQuery(date_from=d_from, date_to=d_to, topic=list(_TAX_ACCOUNTING_TOPICS))


def preset_all_main(*, date_from: date | None = None, date_to: date | None = None) -> NewsQuery:
    """«Главные новости по всем сферам охранной организации за прошедшее время».

    Объединение тем PRESET_SECURITY_ORG + PRESET_TAX_ACCOUNTING, без узкой
    темы (общие «главные новости законодательства»).
    date_from по умолчанию — DEFAULT_LOOKBACK_DAYS дней назад, date_to — сегодня.
    """
    d_from, d_to = _default_range(date_from, date_to)
    return NewsQuery(date_from=d_from, date_to=d_to, topic=[*_SECURITY_TOPICS, *_TAX_ACCOUNTING_TOPICS])


def preset_custom_topic(
    keywords: list[str], *, date_from: date | None = None, date_to: date | None = None
) -> NewsQuery:
    """Произвольная тема, введённая пользователем текстом в чате (например,
    «новости по строительству») — не входит в готовые пресеты выше, но
    резолвится в ID дерева категорий тем же механизмом (`GarantApiParser`
    + `core/news/category_tree.py`), без дополнительного кода. Расширение
    поверх ТЗ tz-garant-news-filtering.md, по прямому запросу пользователя
    ("настраиваемый фильтр под различные сферы"). Как и три пресета выше,
    не задаёт `info_type`/`territory` по умолчанию — только `topic`.
    """
    d_from, d_to = _default_range(date_from, date_to)
    return NewsQuery(date_from=d_from, date_to=d_to, topic=list(keywords))


# Именованные константы — как заявлено в ТЗ (PRESET_SECURITY_ORG и т.д.).
# Это функции-фабрики (а не застывшие объекты), т.к. date_from/date_to
# должны каждый раз пересчитываться относительно "сегодня".
PRESET_SECURITY_ORG = preset_security_org
PRESET_TAX_ACCOUNTING = preset_tax_accounting
PRESET_ALL_MAIN = preset_all_main
