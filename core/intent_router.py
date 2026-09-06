"""IntentRouter — определяет, обычный это диалог или запрос новостей ГАРАНТ ПРАЙМ.

MVP: keyword-matching (по основам слов, без учёта падежей/склонений через
NLP). При необходимости заменить на классификатор/NLP — осознанное
упрощение для первой итерации (см. ТЗ, раздел 3.4 и 9).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from core.models import NewsQuery
from core.news.presets import DEFAULT_LOOKBACK_DAYS, PRESET_ALL_MAIN, PRESET_SECURITY_ORG, PRESET_TAX_ACCOUNTING

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


class IntentRouter:
    def route(self, text: str) -> NewsQuery | None:
        """Вернуть NewsQuery, если сообщение распознано как новостной запрос, иначе None (обычный диалог)."""
        normalized = text.lower()

        custom_range = self._extract_custom_range(text)

        is_general_law_news = any(stem in normalized for stem in LAW_STEMS) and any(
            stem in normalized for stem in CHANGE_STEMS
        )
        is_news_request = (
            custom_range is not None
            or is_general_law_news
            or any(phrase in normalized for phrase in NEWS_TRIGGER_PHRASES)
            or any(keyword in normalized for keyword in (*SECURITY_KEYWORDS, *TAX_KEYWORDS))
        )
        if not is_news_request:
            return None

        if custom_range is not None:
            date_from, date_to = custom_range
        else:
            date_from = date.today() - timedelta(days=self._detect_period_days(normalized))
            date_to = date.today()

        if any(keyword in normalized for keyword in SECURITY_KEYWORDS):
            return PRESET_SECURITY_ORG(date_from=date_from, date_to=date_to)

        if any(keyword in normalized for keyword in TAX_KEYWORDS):
            return PRESET_TAX_ACCOUNTING(date_from=date_from, date_to=date_to)

        return PRESET_ALL_MAIN(date_from=date_from, date_to=date_to)

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
