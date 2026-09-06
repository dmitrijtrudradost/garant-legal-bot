# Как добавить новый интерфейс

Любой новый интерфейс (Telegram-бот, веб-виджет и т.д.) — это тонкий адаптер
поверх `core.bot_core.BotCore`, по образцу `interfaces/vk/vk_interface.py`
(транспорт с событиями) или `interfaces/console/console_interface.py`
(простой синхронный ввод/вывод).

## Шаги

1. Создать пакет `interfaces/<name>/` с `__init__.py` и `<name>_interface.py`.
2. Класс интерфейса наследуется от `interfaces.base.BaseInterface` и реализует:
   - `__init__(self, bot_core: BotCore, ...)` — принимает `BotCore` и любые
     параметры транспорта (токен, конфиг и т.п.), сохраняет их через `super().__init__(bot_core)`.
   - `run(self) -> None` — запускает приём сообщений (polling, long-poll, REPL — что угодно).
3. Внутри обработчика входящего события: собрать `core.models.IncomingMessage`
   (`peer_id`, `user_name`, `text`, `interface="<name>"`), вызвать
   `await self._bot_core.handle_message(incoming)`, отправить
   `outgoing.text` обратно пользователю штатным способом транспорта.
4. **Никакой бизнес-логики** (диалог, история, новости) внутри интерфейса —
   вся логика уже реализована в `BotCore` и переиспользуется автоматически.
5. Подключить новый интерфейс в `main.py` (новый флаг командной строки,
   например `--telegram`), по аналогии с `--vk`/`--console`.
