"""Обёртка над ProxyAPI (chat/completions) — перенесено из старого bot.py.

Отвечает только за HTTP-обращение к ProxyAPI и разбор ответа/ошибок.
Не знает ничего про историю диалога, VK или консоль.
"""

from __future__ import annotations

import logging
import ssl

import aiohttp
import certifi

logger = logging.getLogger(__name__)

_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


class AIClientError(Exception):
    """Ошибка обращения к AI (сеть, лимит, неверный ключ, прочее).

    `user_message` — текст, безопасный для показа пользователю бота.
    """

    def __init__(self, user_message: str, *, technical_details: str = ""):
        super().__init__(technical_details or user_message)
        self.user_message = user_message


class AIClient:
    """Клиент ProxyAPI (модель по умолчанию — GPT-4o Mini)."""

    def __init__(
        self,
        api_key: str,
        *,
        api_url: str = "https://api.proxyapi.ru/v1/chat/completions",
        model: str = "openai/gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> None:
        self._api_key = api_key
        self._api_url = api_url
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Отправляет историю сообщений в ProxyAPI и возвращает текст ответа ассистента.

        `temperature` / `max_tokens` перекрывают значения конструктора на один вызов
        (классификатор намерений использует temperature=0 и короткий max_tokens).
        Бросает AIClientError с понятным для пользователя текстом при любом сбое.
        Ключ API никогда не попадает в лог.
        """
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature if temperature is None else temperature,
            "max_tokens": self._max_tokens if max_tokens is None else max_tokens,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self._api_url, json=payload, headers=headers, ssl=_SSL_CONTEXT
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.info("ProxyAPI: успешный ответ (модель=%s)", self._model)
                        return data["choices"][0]["message"]["content"]

                    text = await response.text()
                    return self._raise_for_status(response.status, text)

        except aiohttp.ClientError as exc:
            logger.error("ProxyAPI: сетевая ошибка: %s", exc)
            raise AIClientError(
                "Извините, не удалось связаться с AI-сервисом (проблема сети). Попробуйте позже.",
                technical_details=str(exc),
            ) from exc

    def _raise_for_status(self, status: int, body: str) -> str:
        if status in (401, 403):
            logger.error("ProxyAPI: ошибка авторизации (status=%s)", status)
            raise AIClientError(
                "Извините, AI-сервис недоступен из-за проблемы с ключом доступа. "
                "Сообщите администратору бота."
            )
        if status == 429:
            logger.error("ProxyAPI: превышен лимит запросов (status=429)")
            raise AIClientError(
                "Извините, сейчас слишком много запросов к AI. Попробуйте через минуту."
            )

        logger.error("ProxyAPI: ошибка %s: %s", status, body[:500])
        raise AIClientError("Извините, произошла ошибка при обращении к AI.")
