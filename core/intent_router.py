"""IntentRouter — определяет, обычный это диалог или запрос новостей ГАРАНТ ПРАЙМ.

MVP: keyword-matching (по основам слов, без учёта падежей/склонений через
NLP). При необходимости заменить на классификатор/NLP — осознанное
упрощение для первой итерации (см. ТЗ, раздел 3.4 и 9).

Территория (`REGION_KEYWORDS`) и произвольные темы (`CUSTOM_TOPIC_PATTERN`) —
тот же MVP-принцип, тот же класс ограничений (см. ТЗ tz-garant-news-filtering.md,
раздел 3.3.5, и docstring соответствующих констант ниже). `IntentRouter`
синхронный и не обращается к дереву категорий ГАРАНТ сам — он только
извлекает СЫРЫЕ ключевые слова (`NewsQuery.territory`/`.topic`), а
резолюция по дереву происходит один раз, в `GarantApiParser`
(`core/news/category_tree.py`) — без дублирования обхода дерева.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from core.models import NewsQuery
from core.news.presets import (
    DEFAULT_LOOKBACK_DAYS,
    PRESET_ALL_MAIN,
    PRESET_SECURITY_ORG,
    PRESET_TAX_ACCOUNTING,
    preset_custom_topic,
)

# Ключевые слова/основы, вынесенные константами — расширять здесь, не трогая логику ниже.
# Фразы-триггеры целиком (срабатывают сами по себе).
NEWS_TRIGGER_PHRASES = [
    "главные новости",
    "предоставь мне изменения",
]
# Общее правило для новостей о законодательстве: в сообщении встречается
# и слово про новизну/изменения, и слово про закон/законодательство —
# так «что нового в законе», «какие новости по закону», «изменения в
# законодательстве» распознаются одинаково, независимо от падежа/числа.
LAW_STEMS = ["законодательств", "закон"]
CHANGE_STEMS = ["измен", "нов", "обновлен"]

SECURITY_KEYWORDS = ["охран", "лицензир"]
TAX_KEYWORDS = ["налог", "бухгалт", "бухучет", "бухучёт"]

# Период, за который нужны новости — по словам из текста (в т.ч. с кнопок
# VK-клавиатуры, см. interfaces/vk/vk_interface.py). Порядок важен: более
# специфичные варианты ("3 месяца") проверяются раньше общих ("месяц"),
# иначе "3 месяца" ошибочно распознается как "месяц" (1 подстрока в другой).
PERIOD_RULES: list[tuple[list[str], int]] = [
    (["3 мес", "квартал", "три месяца"], 90),
    (["недел"], 7),
    (["месяц"], 30),
]

# Явно указанный период датами (например, с кнопки "Свой период"): "ДД.ММ.ГГГГ-ДД.ММ.ГГГГ".
# Если он есть в тексте — используется вместо слов-периодов (PERIOD_RULES) и
# сам по себе делает сообщение новостным запросом, даже без других триггеров.
CUSTOM_PERIOD_PATTERN = re.compile(
    r"(\d{1,2}\.\d{1,2}\.\d{4})\s*[-–—]\s*(\d{1,2}\.\d{1,2}\.\d{4})"
)

# Фраза кнопки "📅 Свой период" (interfaces/vk/vk_interface.py) без указанных
# дат — просьба объяснить пользователю формат, не новостной запрос сам по себе.
CUSTOM_PERIOD_HELP_PHRASE = "свой период"
CUSTOM_PERIOD_HELP_TEXT = (
    "Напишите период в формате ДД.ММ.ГГГГ-ДД.ММ.ГГГГ, например: 01.08.2026-06.09.2026 — "
    "и я пришлю новости ГАРАНТ ПРАЙМ за это время. Можно уточнить тему словом "
    "«охрана» или «налоги» в этом же сообщении."
)

# Регион, упомянутый в тексте — сырое ключевое слово в NewsQuery.territory,
# резолюция по дереву категорий — уже в GarantApiParser (см. докстроку модуля).
# Сознательно небольшой куратируемый список (не полный справочник регионов
# РФ) — ТЗ явно называет эту возможность опциональной и небольшой.
REGION_KEYWORDS: list[tuple[list[str], str]] = [
    (["москв"], "Москва"),
    (["петербург", "спб"], "Санкт-Петербург"),
    (["татарстан"], "Татарстан"),
]

# Произвольная тема в чате ("новости по строительству" и т.п.) — расширение
# сверх ТЗ tz-garant-news-filtering.md, по прямому запросу пользователя
# ("настраиваемый фильтр под различные сферы"). MVP-регэксп, не NLP: ловит
# только форму "(что) нов.../измен... по/о/об/про <тема>" — не произвольную
# формулировку. Резолюция самой фразы в ID дерева категорий — тем же
# механизмом, что и у готовых пресетов (core/news/category_tree.py), без
# дополнительного кода здесь.
CUSTOM_TOPIC_PATTERN = re.compile(r"(?:нов\w*|измен\w*)\s+(?:по|о|об|про)\s+(.+)", re.IGNORECASE)
_PERIOD_CLAUSE_PATTERN = re.compile(
    r"\bза\s+(?:\d+\s+)?(?:недел\w*|месяц\w*|квартал\w*|год\w*|дн\w*)\b", re.IGNORECASE
)


class IntentRouter:
    def route(self, text: str) -> NewsQuery | None:
        """Вернуть NewsQuery, если сообщение распознано как новостной запрос, иначе None (обычный диалог)."""
        normalized = text.lower()

        custom_range = self._extract_custom_range(text)
        custom_topic = self._extract_custom_topic(text)

        is_general_law_news = any(stem in normalized for stem in LAW_STEMS) and any(
            stem in normalized for stem in CHANGE_STEMS
        )
        is_news_request = (
            custom_range is not None
            or is_general_law_news
            or any(phrase in normalized for phrase in NEWS_TRIGGER_PHRASES)
            or any(keyword in normalized for keyword in (*SECURITY_KEYWORDS, *TAX_KEYWORDS))
            or custom_topic is not None
        )
        if not is_news_request:
            return None

        if custom_range is not None:
            date_from, date_to = custom_range
        else:
            date_from = date.today() - timedelta(days=self._detect_period_days(normalized))
            date_to = date.today()

        if any(keyword in normalized for keyword in SECURITY_KEYWORDS):
            query = PRESET_SECURITY_ORG(date_from=date_from, date_to=date_to)
        elif any(keyword in normalized for keyword in TAX_KEYWORDS):
            query = PRESET_TAX_ACCOUNTING(date_from=date_from, date_to=date_to)
        elif custom_topic:
            query = preset_custom_topic([custom_topic], date_from=date_from, date_to=date_to)
        else:
            query = PRESET_ALL_MAIN(date_from=date_from, date_to=date_to)

        territory = self._detect_territory(normalized)
        if territory:
            query.territory = territory
        return query

    @staticmethod
    def is_custom_period_help_request(text: str) -> bool:
        """Нажата кнопка "Свой период" (или написана эта фраза) без реальных дат —
        нужно объяснить формат, а не пытаться получить новости или отвечать через AI.
        """
        normalized = text.lower()
        return CUSTOM_PERIOD_HELP_PHRASE in normalized and IntentRouter._extract_custom_range(text) is None

    @staticmethod
    def _extract_custom_range(text: str) -> tuple[date, date] | None:
        match = CUSTOM_PERIOD_PATTERN.search(text)
        if not match:
            return None
        try:
            date_from = date(*reversed([int(part) for part in match.group(1).split(".")]))
            date_to = date(*reversed([int(part) for part in match.group(2).split(".")]))
        except ValueError:
            return None  # некорректная дата (например, 31.02.2026) — игнорируем как обычный текст
        if date_from > date_to:
            date_from, date_to = date_to, date_from
        return date_from, date_to

    @staticmethod
    def _detect_period_days(normalized: str) -> int:
        """Определяет период по словам в тексте ("неделю"/"месяц"/"3 месяца"/"квартал").

        Если период явно не упомянут — используется значение по умолчанию
        (см. `core.news.presets.DEFAULT_LOOKBACK_DAYS`).
        """
        for stems, days in PERIOD_RULES:
            if any(stem in normalized for stem in stems):
                return days
        return DEFAULT_LOOKBACK_DAYS

    @staticmethod
    def _detect_territory(normalized: str) -> str | None:
        """Регион, упомянутый в тексте (см. REGION_KEYWORDS в докстроке модуля) —
        только сырое ключевое слово, резолюция по дереву категорий в GarantApiParser."""
        for stems, canonical in REGION_KEYWORDS:
            if any(stem in normalized for stem in stems):
                return canonical
        return None

    @staticmethod
    def _extract_custom_topic(text: str) -> str | None:
        """Произвольная тема из текста вида "новости по X"/"что нового по X" (см.
        CUSTOM_TOPIC_PATTERN в докстроке модуля) — MVP, не NLP, конкретные шаблоны фраз."""
        match = CUSTOM_TOPIC_PATTERN.search(text)
        if not match:
            return None
        phrase = _PERIOD_CLAUSE_PATTERN.split(match.group(1), maxsplit=1)[0]
        phrase = phrase.strip(" \t\n?.!,;:")
        return phrase or None
