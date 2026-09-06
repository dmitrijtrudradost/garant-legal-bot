# Обработка ошибок

## VKAPIError

`VKAPIError` - подтип `CodeException` для обработки ошибок VK API.

```python
from vkbottle import VKAPIError
```

### Поля ошибки

- `code` - код ошибки (int)
- `error_msg` - описание ошибки (str)

## try ... except VKAPIError

```python
try:
    await api.wall.post()
except VKAPIError as e:
    print("Возникла ошибка", e.code)
```

## try ... except VKAPIError[code]

Обработка конкретной ошибки:

```python
try:
    await api.messages.send(peer_id=1, message="привет!", random_id=0)
except VKAPIError[902] as e:
    print("не могу отправить сообщение из-за настроек приватности")
except VKAPIError as e:
    print("не могу отправить:", e.error_msg)
```

## Специфичные ошибки

### CaptchaError

- `captcha_sid` - идентификатор captcha (str)
- `captcha_img` - ссылка на изображение (str)

## ErrorHandler

У `ErrorHandler` есть 4 метода:

- `register_error_handler` - декоратор для регистрации хендлера ошибок
- `register_undefined_error_handler` - хендлер для неизвестных ошибок
- `handle` - передача ошибки в соответствующий хендлер
- `catch` - декоратор для ловли ошибок из функции

### Регистрация хендлера ошибок

```python
from vkbottle import Bot, VKAPIError

bot = Bot("token")

@bot.error_handler.register_error_handler(RuntimeError)
async def runtime_error_handler(e: RuntimeError):
    print("возникла ошибка runtime", e)

@bot.error_handler.register_error_handler(VKAPIError[902])
async def unable_to_write_handler(e: VKAPIError):
    print("человек не разрешил отправлять сообщения", e)
```

### Несколько типов ошибок

```python
@bot.error_handler.register_error_handler(TypeError, ValueError)
async def type_or_value_error_handler(e: TypeError | ValueError):
    print("возникла ошибка type или value", e)

@bot.error_handler.register_error_handler(*VKAPIError[6, 9])
async def limit_reached_write_handler(e: VKAPIError):
    print("ой, слишком много запросов", e)
```
