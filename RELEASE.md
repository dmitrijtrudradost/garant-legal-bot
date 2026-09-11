# VK AI-бот 1.2

Чат-бот ВКонтакте и консоль: диалог на GPT-4o Mini (ProxyAPI) и новости ГАРАНТ ПРАЙМ.

Дата: 11.09.2026.

## Что нового относительно 1.1

Режим `browser` доведён до паритета фильтров с `api` на рабочей ленте `internet.garant.ru`.

- Лента задаётся `GARANT_BROWSER_BASE_URL` (по умолчанию `https://internet.garant.ru`). Логин — SSO `account.garant.ru`.
- Фильтры UI: тема через модалку «Полный список» (дерево + поле «Фильтр»); территория и вид информации — только если темы нет.
- Кнопки «за неделю» / «за месяц» на сайте — радио. Свой период в чате — поля «За период» (`from`/`to`).
- «Главные новости» на сайте без узкой темы (только период). Несколько тем пресета одним чекбоксом схлопывали ленту в охрану.
- Ссылки на документы — полные URL (`https://internet.garant.ru/#/document/…`).
- Первая страница сайта ~20 карточек; парсер листает `ul.paginator` (до `MAX_FEED_PAGES`).
- Справка: PDF-каталог сфер в документы VK, повтор загрузки, кэш ссылки `https://vk.com/doc…`.
- alreadyused и заглушка mobileonline без «Войти» — «подождите», не «изменений не найдено».
- Повтор того же запроса в кулдаун 60 с — уже снятая лента, без второго входа.
- После «Применить» ждём «Лента отфильтрована» / «Ничего не найдено», не класс `.resetFilter` на панели.

Аудит 10–11.09.2026: `internet.garant.ru` подтверждён (логин, apply, пагинатор, меню, свой период). `demo.garant.ru` после сессии internet ответил alreadyused и отдельно не подтверждён.

## Запуск

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
python main.py --vk
```

В `.env` нужны `VK_TOKEN` и `PROXYAPI_KEY`. Для API-новостей: `GARANT_TOKEN` и `GARANT_MODE=api`. Для browser: `GARANT_LOGIN`, `GARANT_PASSWORD`, `GARANT_MODE=browser` (лента — `GARANT_BROWSER_BASE_URL`, по умолчанию `https://internet.garant.ru`). У токена VK должно быть право документы (`docs`).
