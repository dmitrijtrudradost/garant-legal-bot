# Правила (Rules)

Для того чтобы хендлер ловил только нужные сообщения/ивенты, нужны правила.

## Встроенные правила

Все встроенные правила работают только с объектом `Message`.

### PeerRule

`PeerRule(from_chat: bool = True)`

Ограничение источника сообщения:

```python
from vkbottle.dispatch.rules.base import PeerRule

@bot.on.message(PeerRule(from_chat=True))
async def chat_handler(message: Message):
    await message.answer("Сообщение из чата")
```

### CommandRule

```python
CommandRule(
    command_text,
    prefixes,
    args_count=0,
    sep=" "
)
```

Используется для реагирования на команды:

```python
from vkbottle.dispatch.rules.base import CommandRule

@bot.on.message(CommandRule("say", ["!", "/"], 1))
async def say_handler(message: Message, args: tuple[str]):
    await message.answer(f"<<{args[0]}>>")
```

Шорткат:

```python
@bot.on.message(command=("say", 1))
async def say_handler(message: Message, args: tuple[str]):
    await message.answer(f"<<{args[0]}>>")
```

### VBMLRule

```python
VBMLRule(
    pattern,
    patcher=None,
    flags=None
)
```

Парсер текстов сообщений:

```python
from vkbottle.dispatch.rules.base import VBMLRule

rule = VBMLRule("/cmd <eggs:int>")
rst = await rule.check(Message(text="/cmd 11", ...))
assert rst == {"eggs": 11}
```

### RegexRule

`RegexRule(regexp)` - проверка на соответствие регулярному выражению.

### StickerRule

`StickerRule(sticker_ids = None)` - отлов стикеров.

### FromPeerRule

`FromPeerRule(peer_ids)` - отлов сообщений от пользователей/групп с указанными ID.

### AttachementTypeRule

`AttachementTypeRule(attachment_types)` - отлов сообщений с указанным типом вложений.

### ForwardMessagesRule

Проверка наличия вложенных сообщений.

### ReplyMessageRule

`ReplyMessageRule(reply_message: bool = True)` - проверка ответа на сообщение.

### GeoRule

Отлов сообщений с геометкой.

### FuzzyTextRule

`FuzzyTextRule(texts, min_ratio: float = 0.7)` - fuzzy string matching.

### MessageLengthRule

`MessageLengthRule(min_length: int)` - ограничение минимальной длины сообщения.

### ChatActionRule

`ChatActionRule(chat_action_types)` - отлов событий в беседах.

### PayloadRule

`PayloadRule(payload)` - проверка payload сообщения.

### PayloadContainsRule

`PayloadContainsRule(payload_part)` - проверка части payload.

### FromUserRule

`FromUserRule(from_user: bool = True)` - проверка что сообщение от пользователя.

### FuncRule

`FuncRule(func)` - принятие функции для проверки.

### StateRule

`StateRule(state)` - проверка стейт-машины.

## Создание собственных правил

Правило - это класс, соответствующий интерфейсу `ABCRule`:

```python
from typing import Union
from vkbottle.bot import Message
from vkbottle.dispatch.rules import ABCRule

class MyRule(ABCRule[Message]):
    async def check(self, event: Message) -> bool:
        return len(event.text) < 100
```

С параметрами:

```python
class MyRule(ABCRule[Message]):
    def __init__(self, lt: int = 100):
        self.lt = lt
    
    async def check(self, event: Message) -> bool:
        return len(event.text) < self.lt
```

Регистрация в лейблере:

```python
bot.labeler.custom_rules["my_rule"] = MyRule

@bot.on.message(my_rule=50)
async def handler(message: Message):
    ...
```

## Правила-врапперы

### FuncRule

```python
@bot.on.message(func=lambda message: len(message.text) < 100)
async def handler(message: Message):
    ...
```
