"""HTTP-клиент API ГАРАНТ: JSON и бинарная выгрузка документа.

Тот же протокол, что раньше жил в `GarantApiParser._call_api`: Bearer-токен,
SSL через certifi, одна повторная попытка после 429, токен не попадает в лог.

Живая сверка 20.10.2026 (topic каталога шаблонов `5703683`):

- `GET /v2/topic/5703683` — `access=ACCESS_IS_FREE`.
- `GET /v2/topic/5703683/html` — в `items[].text` ссылки вида
  `/#/document/{topic}/entry/0` на отдельные документы (больше тысячи topic),
  а не на параграфы самого каталога.
- `GET /v2/topic/{topic}/download` — `Content-Type: application/rtf`, тело
  начинается с `{\\rtf1`. Метода DOCX нет.
- Квоты `GET /v2/limits` (сам этот вызов квоту не уменьшает):
  семейство с `names` `topic/html`, `topic/download`, `entry/html`,
  `topic/download-odt`, `topic/download-pdf` — экспорт (сюда входят `/html`
  и `/download`); семейство `names: ["topic"]` — информация о документе
  (`GET /v2/topic/{id}`, отдельный месячный лимит).
"""

from __future__ import annotations

import asyncio
import logging
import ssl
from typing import Literal, NoReturn

import aiohttp
import certifi

logger = logging.getLogger(__name__)

_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

GARANT_API_BASE_URL = "https://api.garant.ru"
GARANT_API_TOPIC_PATH = "/v2/topic"

RATE_LIMIT_RETRY_DELAY_SECONDS = 1.0
"""Пауза перед единственной повторной попыткой после 429."""

Scope = Literal["news", "document"]


class GarantApiError(Exception):
    """Ошибка обращения к API ГАРАНТ (сеть, авторизация, лимиты, прочее).

    `user_message` — текст, безопасный для показа пользователю бота.
    `status` — HTTP-код, если ошибка пришла от сервера, иначе None.
    """

    def __init__(
        self,
        user_message: str,
        *,
        technical_details: str = "",
        status: int | None = None,
    ) -> None:
        super().__init__(technical_details or user_message)
        self.user_message = user_message
        self.status = status


class GarantApiNotFoundError(GarantApiError):
    """404 — категория или документ не найдены."""


class GarantApiClient:
    """Низкоуровневые GET/POST к api.garant.ru.

    `scope="news"` сохраняет прежние тексты ошибок ленты ПРАЙМ.
    `scope="document"` — нейтральные тексты для шаблонов и прочих документов;
    403 в этом режиме — «Нет доступа по лицензии.»
    """

    def __init__(
        self,
        token: str,
        base_url: str = GARANT_API_BASE_URL,
        *,
        log_name: str = "GarantApiClient",
    ) -> None:
        self._token = token
        self._base_url = base_url
        self._log_name = log_name

    async def get_json(self, path: str, *, scope: Scope = "news") -> dict | list:
        data = await self._request("GET", path, scope=scope, binary=False)
        if isinstance(data, (dict, list)):
            return data
        raise GarantApiError(
            _user_message(scope, "other"),
            technical_details=f"ожидался JSON, получен {type(data).__name__}",
        )

    async def post_json(self, path: str, body: dict, *, scope: Scope = "news") -> dict | list:
        data = await self._request("POST", path, json_body=body, scope=scope, binary=False)
        if isinstance(data, (dict, list)):
            return data
        raise GarantApiError(
            _user_message(scope, "other"),
            technical_details=f"ожидался JSON, получен {type(data).__name__}",
        )

    async def get_bytes(self, path: str, *, scope: Scope = "document") -> bytes:
        data = await self._request("GET", path, scope=scope, binary=True)
        if isinstance(data, bytes):
            return data
        raise GarantApiError(
            _user_message(scope, "other"),
            technical_details="ожидалось бинарное тело ответа",
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict | None = None,
        scope: Scope = "news",
        binary: bool = False,
        _retry: bool = True,
    ) -> dict | list | bytes:
        """Общий HTTP-вызов. Токен никогда не попадает в лог."""
        url = f"{self._base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "*/*" if binary else "application/json",
        }
        if json_body is not None:
            headers["Content-type"] = "application/json"

        try:
            async with aiohttp.ClientSession() as session:
                request = (
                    session.post(url, json=json_body, headers=headers, ssl=_SSL_CONTEXT)
                    if method == "POST"
                    else session.get(url, headers=headers, ssl=_SSL_CONTEXT)
                )
                async with request as response:
                    if response.status == 200:
                        if binary:
                            return await response.read()
                        return await response.json()

                    if response.status == 429 and _retry:
                        logger.warning(
                            "%s: 429 на %s — пауза %sс и одна повторная попытка.",
                            self._log_name,
                            path,
                            RATE_LIMIT_RETRY_DELAY_SECONDS,
                        )
                        await asyncio.sleep(RATE_LIMIT_RETRY_DELAY_SECONDS)
                        return await self._request(
                            method,
                            path,
                            json_body=json_body,
                            scope=scope,
                            binary=binary,
                            _retry=False,
                        )

                    body = await response.text()
                    self._raise_for_status(response.status, path, body, scope)

        except aiohttp.ClientError as exc:
            logger.error("%s: сетевая ошибка при обращении к %s: %s", self._log_name, path, exc)
            raise GarantApiError(
                _user_message(scope, "network"),
                technical_details=str(exc),
            ) from exc

    def _raise_for_status(self, status: int, path: str, body: str, scope: Scope) -> NoReturn:
        safe_body = body[:500]

        if status == 400:
            logger.error("%s: 400 Bad Request на %s: %s", self._log_name, path, safe_body)
            raise GarantApiError(_user_message(scope, 400), technical_details=safe_body, status=400)
        if status == 401:
            logger.error("%s: 401 Unauthorized на %s — требуется обновить GARANT_TOKEN.", self._log_name, path)
            raise GarantApiError(_user_message(scope, 401), technical_details=safe_body, status=401)
        if status == 403:
            logger.error("%s: 403 Forbidden на %s: %s", self._log_name, path, safe_body)
            raise GarantApiError(_user_message(scope, 403), technical_details=safe_body, status=403)
        if status == 404:
            logger.warning("%s: 404 Not Found на %s: %s", self._log_name, path, safe_body)
            raise GarantApiNotFoundError(_user_message(scope, 404), technical_details=safe_body, status=404)
        if status == 423:
            if scope == "news" and path.startswith(GARANT_API_TOPIC_PATH):
                logger.error(
                    "%s: 423 на %s — квота метода «Информация о документе» "
                    "(не более 300 запросов в календарный месяц) исчерпана: %s",
                    self._log_name,
                    path,
                    safe_body,
                )
            else:
                logger.error("%s: 423 на %s — месячная квота исчерпана: %s", self._log_name, path, safe_body)
            raise GarantApiError(_user_message(scope, 423, path), technical_details=safe_body, status=423)
        if status == 429:
            logger.error("%s: 429 на %s даже после повторной попытки.", self._log_name, path)
            raise GarantApiError(_user_message(scope, 429), technical_details=safe_body, status=429)

        logger.error("%s: неожиданный статус %s на %s: %s", self._log_name, status, path, safe_body)
        raise GarantApiError(_user_message(scope, "other"), technical_details=safe_body, status=status)


def _user_message(scope: Scope, kind: int | str, path: str = "") -> str:
    if scope == "document":
        return _DOCUMENT_MESSAGES.get(kind, _DOCUMENT_MESSAGES["other"])
    if kind == 423 and path.startswith(GARANT_API_TOPIC_PATH):
        return (
            "Извините, лимит уточнения точных дат новостей на этот месяц исчерпан "
            "(не более 300 запросов в календарный месяц) — показаны даты по умолчанию."
        )
    return _NEWS_MESSAGES.get(kind, _NEWS_MESSAGES["other"])


_NEWS_MESSAGES: dict[int | str, str] = {
    400: "Извините, сейчас не удалось получить новости (некорректный запрос к источнику).",
    401: "Извините, источник новостей ГАРАНТ временно недоступен (проблема с доступом).",
    403: "Извините, источник новостей ГАРАНТ недоступен (недостаточно прав/лицензии).",
    404: "Извините, сейчас не удалось получить новости по заданной категории.",
    423: (
        "Извините, источник новостей ГАРАНТ временно недоступен "
        "(исчерпана квота запросов до конца месяца)."
    ),
    429: "Извините, источник новостей ГАРАНТ сейчас перегружен запросами. Попробуйте позже.",
    "network": "Извините, не удалось связаться с источником новостей ГАРАНТ (проблема сети). Попробуйте позже.",
    "other": "Извините, сейчас не удалось получить новости. Попробуйте позже.",
}

_DOCUMENT_MESSAGES: dict[int | str, str] = {
    400: "Не удалось получить документ: некорректный запрос.",
    401: "Источник документов ГАРАНТ недоступен (проблема с доступом).",
    403: "Нет доступа по лицензии.",
    404: "Документ не найден.",
    423: "Квота выгрузки документов ГАРАНТ на этот месяц исчерпана.",
    429: "Источник документов ГАРАНТ перегружен запросами. Попробуйте позже.",
    "network": "Не удалось связаться с ГАРАНТ (проблема сети). Попробуйте позже.",
    "other": "Не удалось получить документ. Попробуйте позже.",
}
