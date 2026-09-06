# Клавиатуры и вложения

## Клавиатура

### Создание через Keyboard

```python
from vkbottle import Keyboard, KeyboardButtonColor, Text
```

`Keyboard` принимает параметры `one_time` и `inline`.

Методы `Keyboard`:
- `add(action, color)` - добавляет кнопку к текущему ряду
- `row()` - создаёт следующий ряд кнопок
- `get_json()` - преобразует клавиатуру в JSON-объект

### Пример создания клавиатуры

```python
from vkbottle import Keyboard, KeyboardButtonColor, Text

keyboard = Keyboard(one_time=True, inline=False)

# Первая строка добавляется автоматически
keyboard.add(Text("Кнопка 1"), color=KeyboardButtonColor.POSITIVE)

keyboard.row()  # Переходим на следующую строку

keyboard.add(Text("Кнопка 2"))
keyboard.add(Text("Кнопка 3", payload={"command": 3}))
```

### Отправка клавиатуры

```python
@bot.on.message()
async def send_keyboard(message):
    await message.answer("Смотри сколько кнопок!!", keyboard=keyboard.get_json())
```

### Билдер интерфейс

```python
from vkbottle import Keyboard, KeyboardButtonColor, Text

keyboard = (
    Keyboard(one_time=True, inline=False)
    .add(Text("Кнопка 1"), color=KeyboardButtonColor.POSITIVE)
    .row()
    .add(Text("Кнопка 2"))
    .add(Text("Кнопка 3", payload={"command": 3}))
).get_json()

await message.answer(
    message="Смотри сколько кнопок!!",
    keyboard=keyboard
)
```

### Удаление клавиатуры

Для удаления клавиатуры у пользователя нужно отправить `EMPTY_KEYBOARD`.

## Вложения

### Если есть ссылка на вложение

Если у вас уже есть ссылка на вложение вида `"type{OWNER_ID}_{ITEM_ID}"` (например `"photo-41629685_457239401"`):

```python
attachment = "photo-41629685_457239401"

@bot.on.message
async def send_attachment(message):
    await message.answer("See that attachment!", attachment=attachment)
```

### Динамическая загрузка вложений

Для отправки вложений, загруженных во время работы бота, нужны загрузчики:

```python
uploader = AnyUploader(bot.api)

@bot.on.message()
async def send_attachment(message):
    attachment = await uploader.upload("path/to/file")
    await message.answer("See that attachment!", attachment=attachment)
```

## Шаблоны

На данный момент ВКонтакте поддерживает только один вид шаблона — карусель.

```python
from vkbottle.tools import template_gen, TemplateElement

my_template = template_gen(
    TemplateElement(...),
    TemplateElement(...),
    TemplateElement(...)
)
```

Отправка шаблона:

```python
@bot.on.message()
async def send_template(message):
    await message.answer("Sending template...", template=my_template)
```
