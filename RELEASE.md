# VK AI-бот 1.2.1

Чат-бот ВКонтакте и консоль: диалог на GPT-4o Mini (ProxyAPI) и новости ГАРАНТ ПРАЙМ.

Дата: 16.10.2026.

## Что нового относительно 1.2

Остаток месячной квоты API ГАРАНТ в чате.

- Фразы «лимиты» и «остаток запросов» вызывают `GET https://api.garant.ru/v2/limits`.
- Ответ — список: название семейства методов и сколько вызовов осталось в этом месяце.
- Кнопки нет. В режиме `browser` и без `GARANT_TOKEN` бот пишет, что лимиты доступны только в режиме `api`.
- Описание этих фраз добавлено в справку и в каталог сфер.

## Запуск

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
python main.py --vk
```

В `.env` нужны `VK_TOKEN` и `PROXYAPI_KEY`. Для API-новостей и лимитов: `GARANT_TOKEN` и `GARANT_MODE=api`. Для browser: `GARANT_LOGIN`, `GARANT_PASSWORD`, `GARANT_MODE=browser` (лента — `GARANT_BROWSER_BASE_URL`, по умолчанию `https://internet.garant.ru`). У токена VK должно быть право документы (`docs`).
