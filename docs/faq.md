# FAQ - Часто задаваемые вопросы

## Asyncio

### Что такое coroutine?

Coroutine это функция (сопрограмма), которая должна вызываться через **await**.

```python
import asyncio

async def get_banana() -> str:
    return "banana"

async def main():
    print(get_banana())  # <coroutine object get_banana at 0x...>
    print(await get_banana())  # banana

asyncio.run(main())
```

### Где надо писать await?

Надо **await** писать только внутри **async** функций:

```python
# Плохо
async def foo() -> str:
    return "foo"

def main():
    print(await foo())  # SyntaxError

# Хорошо
import asyncio

async def foo() -> str:
    return "foo"

async def main():
    print(await foo())

asyncio.run(main())
```

### Как происходит блокировка функции?

В асинхронном программировании блокирующие функции - все функции без конструкции **await**, работающие на принципе IO.

Используйте `asyncio.sleep()` вместо `time.sleep()`:

```python
# Плохо
time.sleep(10)

# Хорошо
await asyncio.sleep(10)
```

Для HTTP запросов используйте `aiohttp`:

```python
# Плохо
import requests
r = requests.get('http://httpbin.org/get')

# Хорошо
from vkbottle.http import AiohttpClient
http_client = AiohttpClient()
return await http_client.request_json('http://httpbin.org/get')
```

## Какие методы присутствуют во фреймворке

Все методы из [официальной документации VK API](https://dev.vk.ru/reference).

Методы пишутся в **snake_case**, а не **camelCase**:

```python
from vkbottle.api import API

api = API("token")

# https://api.vk.ru/method/account.ban
await api.account.ban(owner_id=1)

# https://api.vk.ru/method/account.getBanned
await api.account.get_banned(offset=0, count=1)
```

## Как получить токен

### Для пользователя

Используйте сервис [vkhost.github.io](https://vkhost.github.io)

### Для бота

Следуйте [инструкции](https://dev.vk.ru/api/bots/getting-started)

## Как отправить метод, которого нет во фреймворке

Используйте `API.request`:

```python
import asyncio
from vkbottle.api import API

api = API("token")

async def main():
    await api.request("users.get", {})  # Single request
    
    # Multiple request for one session
    async for response in api.request_many(
        [api.APIRequest("users.get", {}), api.APIRequest("groups.get", {})]
    ):
        print(response)

asyncio.run(main())
```

Для бота:

```python
import asyncio
from vkbottle.bot import Bot

bot = Bot("token")

async def main():
    print(await bot.api.request("users.get", {}))
    
    async for response in bot.api.request_many(
        [bot.api.APIRequest("users.get", {}), bot.api.APIRequest("groups.get", {})]
    ):
        print(response)

asyncio.run(main())
```

Через объект Message:

```python
from vkbottle.bot import Bot, Message

bot = Bot(token="token")

@bot.on.message(text="админы")
async def who_admins(message: Message):
    admins = [f"{adm.first_name} {adm.last_name}" 
              for adm in (await message.ctx_api.users.get(admin_ids))]
    await message.answer(f"Администраторы этого бота: {' '.join(admins)}")
```

## Pydantic.error_wrappers.ValidationError

Если ошибка возникла из-за обновления типов:

```bash
pip install git+https://github.com/vkbottle/types -U
```
