"""IntentRouter — определяет, обычный это диалог или запрос новостей ГАРАНТ ПРАЙМ.

Уровень 1 (`route`) — синхронный keyword-matching по основам слов, без NLP.
Уровень 2 (`classify_via_ai`) — один stateless-вызов AI, только если уровень 1
не сработал и в тексте есть юридический корень мягкого шлюза
(`AI_FALLBACK_GATE_STEMS`). Без клиента AI уровень 2 просто не вызывается.

Территория (`REGION_KEYWORDS`) и произвольные темы (`CUSTOM_TOPIC_PATTERN`) —
тот же MVP-принцип, тот же класс ограничений (см. ТЗ tz-garant-news-filtering.md,
раздел 3.3.5, и docstring соответствующих констант ниже). `IntentRouter`
не обращается к дереву категорий ГАРАНТ сам — он только извлекает СЫРЫЕ
ключевые слова (`NewsQuery.territory`/`.topic`), а резолюция по дереву
происходит один раз, в `GarantApiParser` (`core/news/category_tree.py`).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta

from core.ai_client import AIClient, AIClientError
from core.models import NewsQuery
from core.news.presets import (
    DEFAULT_LOOKBACK_DAYS,
    PRESET_ALL_MAIN,
    PRESET_SECURITY_ORG,
    PRESET_TAX_ACCOUNTING,
    preset_custom_topic,
)

logger = logging.getLogger(__name__)

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
# VK-клавиатуры, см. interfaces/vk/vk_interface.py). Числовой шаблон
# («за 6 месяцев») проверяется раньше этих правил, иначе «месяц» внутри
# «6 месяцев» дал бы 30 дней вместо 180. Порядок внутри списка важен:
# более специфичные варианты ("3 месяца") раньше общих ("месяц").
PERIOD_RULES: list[tuple[list[str], int]] = [
    (["3 мес", "квартал", "три месяца"], 90),
    (["недел"], 7),
    (["месяц"], 30),
]

_NUMERIC_PERIOD_PATTERN = re.compile(
    r"за\s+(\d+)\s+(день|дня|дней|недел\w*|мес\w*|год\w*|лет)\b",
    re.IGNORECASE,
)

# Явно указанный период датами: "ДД.ММ.ГГГГ-ДД.ММ.ГГГГ".
# Если он есть в тексте — используется вместо слов-периодов (PERIOD_RULES) и
# сам по себе делает сообщение новостным запросом, даже без других триггеров.
CUSTOM_PERIOD_PATTERN = re.compile(
    r"(\d{1,2}\.\d{1,2}\.\d{4})\s*[-–—]\s*(\d{1,2}\.\d{1,2}\.\d{4})"
)

# Справка в чате (кнопка «Справка» и те же фразы текстом). Не новостной запрос.
HELP_EXACT_PHRASES = frozenset(
    {
        "справка",
        "помощь",
        "как пользоваться",
        "список сфер",
        "список фильтров",
    }
)
CUSTOM_PERIOD_HELP_PHRASE = "свой период"
HELP_TEXT = (
    "Как спросить новости ГАРАНТ ПРАЙМ\n"
    "\n"
    "Напишите тему и период — или нажмите кнопку. Кнопки — быстрый путь к частым запросам.\n"
    "\n"
    "Приоритет темы:\n"
    "1. Охрана — если в тексте есть «охрана» или «лицензирование».\n"
    "2. Названная сфера — например «из сферы строительство» или «воздушный транспорт».\n"
    "3. Иначе — главные новости по основным сферам.\n"
    "\n"
    "Период считается от сегодня: «за неделю», «за месяц», «за 6 месяцев», «за год».\n"
    "\n"
    "Свой период: укажите даты в одном сообщении со сферой, "
    "ДД.ММ.ГГГГ-ДД.ММ.ГГГГ, например 01.08.2026-06.09.2026.\n"
    "\n"
    "«ещё» или кнопка «Показать ещё» — следующие 10 новостей из уже найденных.\n"
    "\n"
    "«лимиты» или «остаток запросов» — сколько вызовов API ГАРАНТ осталось в этом месяце.\n"
    "\n"
    "Примеры запросов\n"
    "1. Охранные новости за месяц\n"
    "2. Новости в сфере образование за 6 месяцев\n"
    "3. Новости в сфере строительство за период 01.08.2026-10.09.2026\n"
    "4. Главные новости за неделю"
)
HELP_CATALOG_LINK_PREFIX = "Список сфер и фильтров: "
HELP_CATALOG_UNAVAILABLE = "Список сфер недоступен."
LIMITS_EXACT_PHRASES = frozenset({"лимиты", "остаток запросов"})
# Совместимость со старым именем: узкая подсказка про даты заменена полной справкой.
CUSTOM_PERIOD_HELP_TEXT = HELP_TEXT

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
SPHERE_TOPIC_PATTERN = re.compile(
    r"(?:из\s+сферы|по\s+сфере|в\s+сфере|сфера)\s+(.+)", re.IGNORECASE
)
_PERIOD_CLAUSE_PATTERN = re.compile(
    r"\bза\s+(?:\d+\s+)?(?:недел\w*|мес\w*|месяц\w*|квартал\w*|год\w*|лет|дн\w*|день|дня|дней|полгода)\b"
    r"|\bза\s+период\b",
    re.IGNORECASE,
)
_TOPIC_STOP_WORDS = frozenset(
    {
        "новости",
        "новость",
        "новостей",
        "изменения",
        "изменение",
        "хочу",
        "узнать",
        "предоставь",
        "предоставить",
        "покажи",
        "дай",
        "пришли",
        "пожалуйста",
        "нужны",
        "нужно",
        "за",
        "период",
        "даты",
        "с",
        "по",
        "про",
        "о",
        "об",
        "из",
        "сферы",
        "сфере",
        "сфера",
        "главные",
        "законодательстве",
        "законодательства",
        "законе",
        "законам",
        "закон",
        "мне",
        "какие",
        "что",
        "там",
        "есть",
    }
)

# Мягкий шлюз перед AI-классификатором: только юридическая/официальная лексика.
# Голые «нов»/«измен»/«закон» сюда не входят — слишком широкие для бытовой речи.
AI_FALLBACK_GATE_STEMS = [
    "норматив",
    "правов",
    "постановлен",
    "приказ",
    "распоряжен",
    "указ",
    "поправк",
    "актуальн",
    "гарант",
    "прайм",
    "юридич",
    "регулирован",
    "законодательств",
]

CLASSIFY_TEMPERATURE = 0.0
CLASSIFY_MAX_TOKENS = 200

NEWS_CLASSIFY_SYSTEM_PROMPT = (
    "Ты классификатор запросов новостей законодательства ГАРАНТ ПРАЙМ. "
    "Пользователь пишет по-русски. Верни СТРОГО один JSON-объект без пояснений "
    "и без markdown-обёртки. Схема: "
    '{"is_news": bool, "topic": "security"|"tax"|"general"|"custom"|null, '
    '"custom_topic": str|null, "period_days": int|null, '
    '"date_from": "YYYY-MM-DD"|null, "date_to": "YYYY-MM-DD"|null, '
    '"territory": str|null}. '
    "is_news=true только если пользователь хочет новости, изменения законодательства, "
    "нормативных актов или правовой информации. "
    "topic: security — охрана и лицензирование охранной деятельности; "
    "tax — налоги и бухучёт; custom — другая конкретная тема "
    "(тогда custom_topic — краткое название темы); "
    "general — общие главные новости законодательства. "
    "period_days: 7 неделя, 30 месяц, 90 квартал, 180 полгода/N месяцев, 365 год; "
    "если период неясен — null. "
    "date_from/date_to заполняй только если явно названы конкретные даты. "
    "territory — регион, если назван, иначе null."
)

# Точные фразы пагинации после нормализации (нижний регистр, без эмодзи).
# Не подстрока: «покажи ещё новости по охране» сюда не попадает.
SHOW_MORE_PHRASES = frozenset(
    {
        "ещё",
        "еще",
        "дальше",
        "далее",
        "следующие",
        "покажи ещё",
        "покажи еще",
        "показать ещё",
        "показать еще",
        "остальные",
        "показать все",
    }
)
SHOW_MORE_BUTTON_LABEL = "➡️ Показать ещё"
_NON_WORD_CHARS = re.compile(r"[^\w\s-]+", re.UNICODE)
_JSON_FENCE_PREFIX = re.compile(r"^```(?:json)?\s*", re.IGNORECASE)
_JSON_FENCE_SUFFIX = re.compile(r"\s*```$")


class IntentRouter:
    def __init__(self, ai_client: AIClient | None = None) -> None:
        self._ai_client = ai_client

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

    def looks_like_news_for_ai(self, text: str) -> bool:
        """Мягкий шлюз: в тексте есть юридический/официальный корень, но жёсткий route() мог не сработать."""
        normalized = text.lower()
        return any(stem in normalized for stem in AI_FALLBACK_GATE_STEMS)

    async def classify_via_ai(self, text: str) -> NewsQuery | None:
        """Один stateless-вызов AI, только если клиент задан и сработал мягкий шлюз.

        Не пишет в историю диалога. Любая ошибка (сеть, битый JSON, is_news не true)
        тихо возвращает None — обычный диалог, бот не падает.
        """
        if self._ai_client is None or not self.looks_like_news_for_ai(text):
            return None

        messages = [
            {"role": "system", "content": NEWS_CLASSIFY_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ]
        try:
            raw = await self._ai_client.complete(
                messages,
                temperature=CLASSIFY_TEMPERATURE,
                max_tokens=CLASSIFY_MAX_TOKENS,
            )
        except AIClientError as exc:
            logger.warning("IntentRouter: AI-классификация недоступна: %s", exc)
            return None

        return self._news_query_from_ai_payload(raw)

    def _news_query_from_ai_payload(self, raw: str) -> NewsQuery | None:
        try:
            data = json.loads(self._strip_json_fence(raw))
        except json.JSONDecodeError:
            logger.warning("IntentRouter: невалидный JSON от AI-классификатора")
            return None

        if not isinstance(data, dict):
            logger.warning("IntentRouter: AI-классификатор вернул не объект JSON")
            return None

        is_news = data.get("is_news")
        if is_news is not True and is_news != "true":
            return None

        date_from, date_to = self._dates_from_ai(data)
        topic = data.get("topic")
        if topic == "security":
            query = PRESET_SECURITY_ORG(date_from=date_from, date_to=date_to)
        elif topic == "tax":
            query = PRESET_TAX_ACCOUNTING(date_from=date_from, date_to=date_to)
        elif topic == "custom":
            custom = data.get("custom_topic")
            if isinstance(custom, str) and custom.strip():
                query = preset_custom_topic([custom.strip()], date_from=date_from, date_to=date_to)
            else:
                query = PRESET_ALL_MAIN(date_from=date_from, date_to=date_to)
        else:
            query = PRESET_ALL_MAIN(date_from=date_from, date_to=date_to)

        territory = data.get("territory")
        if isinstance(territory, str) and territory.strip():
            query.territory = territory.strip()
        return query

    @staticmethod
    def _dates_from_ai(data: dict) -> tuple[date, date]:
        raw_from, raw_to = data.get("date_from"), data.get("date_to")
        if raw_from and raw_to:
            try:
                date_from = date.fromisoformat(str(raw_from)[:10])
                date_to = date.fromisoformat(str(raw_to)[:10])
            except ValueError:
                date_from = date_to = None
            else:
                if date_from > date_to:
                    date_from, date_to = date_to, date_from
                return date_from, date_to

        period_days = data.get("period_days")
        if isinstance(period_days, bool) or not isinstance(period_days, (int, float)) or period_days <= 0:
            days = DEFAULT_LOOKBACK_DAYS
        else:
            days = int(period_days)
        return date.today() - timedelta(days=days), date.today()

    @staticmethod
    def _strip_json_fence(raw: str) -> str:
        text = raw.strip()
        text = _JSON_FENCE_PREFIX.sub("", text, count=1)
        text = _JSON_FENCE_SUFFIX.sub("", text)
        return text.strip()

    @staticmethod
    def is_show_more_request(text: str) -> bool:
        """Точная фраза пагинации («ещё», кнопка «Показать ещё»), не подстрока в произвольном тексте."""
        return IntentRouter._normalize_exact_phrase(text) in SHOW_MORE_PHRASES

    @staticmethod
    def _normalize_exact_phrase(text: str) -> str:
        cleaned = _NON_WORD_CHARS.sub(" ", text.lower())
        return " ".join(cleaned.split())

    @staticmethod
    def is_limits_request(text: str) -> bool:
        """Точные фразы «лимиты» и «остаток запросов» — остаток квоты API, не новости и не AI."""
        return IntentRouter._normalize_exact_phrase(text) in LIMITS_EXACT_PHRASES

    @staticmethod
    def is_help_request(text: str) -> bool:
        """Кнопка «Справка» или та же просьба текстом — инструкция, не новости и не AI."""
        if IntentRouter._normalize_exact_phrase(text) in HELP_EXACT_PHRASES:
            return True
        normalized = text.lower()
        return CUSTOM_PERIOD_HELP_PHRASE in normalized and IntentRouter._extract_custom_range(text) is None

    @staticmethod
    def is_custom_period_help_request(text: str) -> bool:
        """Совместимость: «свой период» без дат и остальные фразы справки."""
        return IntentRouter.is_help_request(text)

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
        """Период от сегодня: сначала «за N день/недел/мес/год», затем полгода/год, затем прежние слова.

        Если период явно не упомянут — используется значение по умолчанию
        (см. `core.news.presets.DEFAULT_LOOKBACK_DAYS`).
        """
        numeric = _NUMERIC_PERIOD_PATTERN.search(normalized)
        if numeric:
            return IntentRouter._numeric_period_to_days(int(numeric.group(1)), numeric.group(2))
        if "полгода" in normalized or "пол года" in normalized:
            return 180
        if re.search(r"(?<!\d)\bгод\b", normalized):
            return 365
        for stems, days in PERIOD_RULES:
            if any(stem in normalized for stem in stems):
                return days
        return DEFAULT_LOOKBACK_DAYS

    @staticmethod
    def _numeric_period_to_days(count: int, unit: str) -> int:
        lowered = unit.lower()
        if lowered.startswith("недел"):
            return 7 * count
        if lowered.startswith("мес"):
            return 30 * count
        if lowered.startswith("год") or lowered.startswith("лет"):
            return 365 * count
        return count

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
        """Тема сферы интересов: шаблоны «из сферы X» / «новости по X», иначе остаток после дат и «за N …»."""
        for pattern in (SPHERE_TOPIC_PATTERN, CUSTOM_TOPIC_PATTERN):
            match = pattern.search(text)
            if match:
                return IntentRouter._clean_topic_phrase(match.group(1))

        has_period = (
            IntentRouter._extract_custom_range(text) is not None
            or _PERIOD_CLAUSE_PATTERN.search(text) is not None
        )
        if not has_period:
            return None
        return IntentRouter._topic_leftover(text)

    @staticmethod
    def _clean_topic_phrase(phrase: str) -> str | None:
        return IntentRouter._topic_leftover(phrase)

    @staticmethod
    def _topic_leftover(text: str) -> str | None:
        cleaned = CUSTOM_PERIOD_PATTERN.sub(" ", text)
        cleaned = _PERIOD_CLAUSE_PATTERN.sub(" ", cleaned)
        words = re.findall(r"[а-яёa-z]+", cleaned.lower())
        kept = [word for word in words if word not in _TOPIC_STOP_WORDS and len(word) >= 4]
        return " ".join(kept) or None
