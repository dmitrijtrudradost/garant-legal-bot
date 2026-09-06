# LongPoll API

## Polling

Библиотека использует `Polling` для реализации longpoll. Для ботов и юзеров создан соответствующий поллинг.

## Методы Polling

### get_server

Получает сервер для поллинга и возвращает его.

### get_event

Получает сервер из get_server и делает долгий POST реквест.

### listen

Асинхронный итератор. Генерирует приходящие ивенты.

### construct

Принимает API, конструирует поллинг с обновленным API при каждом вызове.

## Стандартные параметры для BotPolling / UserPolling

- **api** - если не указано будет получено в `listen`
- **group_id** / **user_id** - если не указано будет получено в `listen`
- **wait** - лимит секунд после которого ВК принудительно возвращает ответ
- **rps_delay** - задержка (по умолчанию 0)

## Запуск LongPoll

### Через Bot

```python
from vkbottle.bot import Bot

bot = Bot(token="token")

# Асинхронный запуск
async def main():
    await bot.run_polling()

# Или синхронный запуск
bot.run_forever()
```

### Атрибуты бота

- `bot.api` - API
- `bot.router` - Router
- `bot.labeler` / `bot.on` - Labeler
- `bot.polling` - Polling
- `bot.callback` - Callback
- `bot.error_handler` - Error handler
- `bot.loop_wrapper` - Loop Wrapper

## Callback API

Для подключения CallbackAPI к сообществу:

```python
import os
from vkbottle.callback import BotCallback
from vkbottle import Bot

TOKEN = os.getenv("VK_TOKEN")
url = os.getenv("VK_URL")
title = os.getenv("VK_TITLE")

callback = BotCallback(
    url=url,
    title=title
)

bot = Bot(token=TOKEN, callback=callback)

# Обработка события
await bot.process_event(event)
```

## Кастомный поллинг

Кастомный поллинг должен унаследовать `ABCPolling` и имплементировать методы:

```python
from vkbottle.polling import ABCPolling

class MyPolling(ABCPolling):
    async def get_server(self):
        ...
    
    async def get_event(self, server):
        ...
    
    async def listen(self):
        ...
```
