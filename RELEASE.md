# чатбот_гарант_версия 1.2.2

Чат-бот ВКонтакте и консоль: диалог на GPT-4o Mini (ProxyAPI), новости ГАРАНТ ПРАЙМ и шаблоны договоров.

Дата: 20.10.2026.

## Что нового относительно 1.2.1

Шаблоны договоров из ГАРАНТ в Word.

- Фразы «шаблоны договоров», «шаблон N» и «шаблон» с частью названия. Кнопки нет, AI для этих фраз не вызывается.
- Список длиннее 10 пунктов листается командой «ещё». Один шаблон приходит файлом: в VK — документом, в консоли — путём к файлу.
- `GET /v2/topic/5703683/html` даёт каталог, `GET /v2/topic/{id}/download` — RTF. DOCX делает LibreOffice (`soffice`). Нет LibreOffice — остаётся RTF.
- Повторная выгрузка берёт уже скачанный файл, если `last_modified` не менялся. `ACCESS_BY_MONEY`, `ACCESS_BY_REQUEST` и `ACCESS_DENIED` пропускаются. 423 останавливает выгрузку.
- В режиме `browser` и без `GARANT_TOKEN` бот пишет, что шаблоны доступны только в режиме `api`.
- Выгрузка диалога VK запускается как `python -m exports.export_vk_history`.

## Запуск

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
playwright install chromium
copy .env.example .env
python main.py --vk
```

В `.env` нужны `VK_TOKEN` и `PROXYAPI_KEY`. Для API-новостей, лимитов и шаблонов: `GARANT_TOKEN` и `GARANT_MODE=api`. Для `.docx` — LibreOffice (`LIBREOFFICE_PATH`, если `soffice` не в PATH). Для browser: `GARANT_LOGIN`, `GARANT_PASSWORD`, `GARANT_MODE=browser`. У токена VK должно быть право документы (`docs`).
