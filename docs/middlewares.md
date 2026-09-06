# Мидлвари и return менеджеры

## Мидлвари

Мидлвари - внешние слои, покрывающие обработку хендлеров. У мидлварей есть два состояния:
- `pre` - до начала поиска хендлера
- `post` - после обработки хендлера

### Создание мидлвари

```python
from vkbottle import BaseMiddleware
from vkbottle.bot import Message

class MiddlewareName(BaseMiddleware[Message]):
    ...
```

### Метод pre

`pre` имеет доступ к ивенту через `self` и может вернуть ошибку через `self.stop` или обновить контекст через `self.send`:

```python
from vkbottle.bot import Message
from vkbottle import BaseMiddleware, MiddlewareResponse

class NoBotMiddleware(BaseMiddleware[Message]):
    async def pre(self):
        if self.event.from_id < 0:
            self.stop("from_id меньше 0")
```

### Метод post

`post` обычно используется для статистики и логов:

```python
from vkbottle.bot import Message
from vkbottle import BaseMiddleware

class LogMiddleware(BaseMiddleware[Message]):
    async def post(self):
        if not self.handlers:
            return
        print(f"{len(self.handlers)} хендлеров сработало на сообщение. "
              f"Они вернули {self.handle_responses}, "
              f"все они принадлежали к view {self.view}")
```

### Регистрация мидлварей

```python
bot.labeler.message_view.register_middleware(NoBotMiddleware)
bot.labeler.message_view.register_middleware(LogMiddleware)
```

## Return менеджеры

Возвращая значения некоторых типов из хендлера, сработают хендлеры return менеджера:

| Тип значения | Что произойдет |
|--------------|----------------|
| str | строка отправится как сообщение |
| tuple или list | все элементы будут конвертированы в строки и отправлены как сообщения |
| dict | словарь распакуется как непозиционные аргументы для метода message.answer |
