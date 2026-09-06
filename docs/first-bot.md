# Первый бот на vkbottle

## Установка

```bash
pip install vkbottle
```

## API

Для начала работы с API следует импортировать нужный объект - `vkbottle.API`:

```python
from vkbottle import API
```

`API` - готовый инструмент для того, чтобы делать запросы к API вконтакте, с полной типизацией.

## Первый запрос

Для инициализации `API` вам понадобится строка (токен) или лист строк (токенов):

```python
import asyncio
from vkbottle import API

async def main():
    api = API("token")
    await api.wall.post(message="#vkbottle прекрасен!")

asyncio.run(main())
```

## Первый бот

Для начала работы с ботом требуется импортировать класс `Bot`:

```python
from vkbottle.bot import Bot
```

Для инициализации бота обязателен аргумент - `token` или `api`:

```python
# Инициализация токеном
bot = Bot(token="token")

# (или) Инициализация с апи
bot = Bot(api=api)
```

## Хендлеры сообщений

Для добавления хендлеров используется `labeler`:

```python
from vkbottle.bot import Bot, Message

bot = Bot(token="token")

@bot.on.message(text="Привет")
async def hi_handler(message: Message):
    users_info = await bot.api.users.get(message.from_id)
    await message.answer("Привет, {}".format(users_info[0].first_name))

bot.run_forever()
```

### Декораторы для сообщений

Для сообщений в vkbottle существует 3 декоратора:

- `.message` - обрабатывает сообщения и из бесед и из личных переписок
- `.private_message` - обрабатывает сообщения только из личных переписок
- `.chat_message` - обрабатывает сообщения только из бесед

### Описание кода

- `@bot.on.message(text="Привет")` - декоратор, означающий что если сообщение будет отвечать заданным правилам, сработает хендлер
- `async def hi_handler(message: Message)` - объявление хендлера
- `users_info = await bot.api.users.get(message.from_id)` - запрос к API
- `await message.answer("Привет, {}".format(users_info[0].first_name))` - отправка сообщения
- `bot.run_forever()` - синхронный запуск бота

## Запуск

```python
bot.run_forever()
```

Или асинхронно:

```python
import asyncio

async def main():
    await bot.run_polling()

asyncio.run(main())
```
