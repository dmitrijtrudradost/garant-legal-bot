# Разделение кода

Разделение кода - очень важная вещь для создания структуры проекта.

## Стандартная иерархия файлов

```
/src/
├── handlers
│   ├── __init__.py
│   ├── admin.py
│   ├── chat.py
│   └── ping.py
├── bot.py
└── config.py
```

## config.py

Файл с конфигом для глобальных переменных:

```python
from vkbottle import API, BuiltinStateDispenser
from vkbottle.bot import BotLabeler

api = API("token")
labeler = BotLabeler()
state_dispenser = BuiltinStateDispenser()
```

## ping.py

Простой хендлер в папке handlers:

```python
from config import labeler

@labeler.message(text="ping")
async def ping_handler(message):
    await message.answer("pong")
```

## chat.py

Использование `auto_rules` для автоматического добавления правил:

```python
from vkbottle.bot import BotLabeler, Message, rules
from vkbottle_types.objects import MessagesConversation

class ChatInfoRule(rules.ABCRule[Message]):
    async def check(self, message: Message) -> dict[str, Any]:
        chats_info = await message.ctx_api.messages.get_conversations_by_id(message.peer_id)
        return {"chat": chats_info.items[0]}

chat_labeler = BotLabeler()
chat_labeler.vbml_ignore_case = True
chat_labeler.auto_rules = [rules.PeerRule(from_chat=True), ChatInfoRule()]

@chat_labeler.message(command="самобан")
async def kick(message: Message, chat: MessagesConversation):
    await message.ctx_api.messages.remove_chat_user(message.chat_id, message.from_id)
    await message.answer(f"Участник самоустранился из {chat.chat_settings.title} по собственному желанию")

@chat_labeler.message(text="где я")
async def where_am_i(message: Message, chat: MessagesConversation):
    await message.answer(f"Вы в <<{chat.chat_settings.title}>>")
```

## admin.py

Команды только для создателя бота:

```python
from vkbottle.bot import BotLabeler, Message, rules

admin_labeler = BotLabeler()
admin_labeler.auto_rules = [rules.FromPeerRule(1)]  # Допустим, вы являетесь Павлом Дуровым

@admin_labeler.message(command="halt")
async def halt(_):
    exit(0)
```

## __init__.py

Импорт всех лейблеров:

```python
from .chat import chat_labeler
from .admin import admin_labeler
from .ping import labeler

__all__ = ("admin_labeler", "chat_labeler", "labeler")
```

## bot.py

Создание бота и регистрация лейблеров:

```python
from vkbottle import Bot
from config import api, state_dispenser, labeler
from handlers import chat_labeler, admin_labeler

labeler.load(chat_labeler)
labeler.load(admin_labeler)

bot = Bot(
    api=api,
    labeler=labeler,
    state_dispenser=state_dispenser,
)

bot.run_forever()
```
