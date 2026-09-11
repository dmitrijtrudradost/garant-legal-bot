# VK AI-бот 1.2

Чат-бот ВКонтакте и консоль: диалог на GPT-4o Mini (ProxyAPI) и новости ГАРАНТ ПРАЙМ.

## Что нового

- Режим `browser` ходит на `internet.garant.ru` (переменная `GARANT_BROWSER_BASE_URL`).
- Фильтры ленты через UI: период датами, тема (дерево + «Фильтр»); территория и вид информации только если темы нет.
- Аудит 10.09.2026: internet подтверждён включая apply темы; demo в тот день не подтверждён (alreadyused). Пустая лента — «Ничего не найдено».

## Запуск

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
python main.py --vk
```

В `.env`: `VK_TOKEN`, `PROXYAPI_KEY`. Для API-новостей: `GARANT_TOKEN` и `GARANT_MODE=api`. Для browser: `GARANT_LOGIN`, `GARANT_PASSWORD`, `GARANT_MODE=browser`.
