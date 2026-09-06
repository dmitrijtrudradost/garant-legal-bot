# Установка и запуск проекта

Пошаговая инструкция для двух сценариев:
- **А. Локально на этой машине (Windows)**
- **Б. На удалённом сервере (Linux, например Ubuntu/Debian)**

Общая часть (структура `.env`, проверка токенов, команды запуска) одинакова для обоих сценариев — различаются только шаги установки окружения.

---

## 0. Что потребуется заранее

| Переменная | Обязательна | Где взять |
|---|---|---|
| `VK_TOKEN` | да | Токен сообщества ВКонтакте: https://vk.com/editapp?act=create → создать сообщество → в настройках сообщества включить "Сообщения" → LongPoll API → выпустить токен |
| `PROXYAPI_KEY` | да | Регистрация на https://proxyapi.ru → личный кабинет → API-ключ |
| `GARANT_LOGIN`, `GARANT_PASSWORD` | нет (опционально) | Логин/пароль для входа на demo.garant.ru — нужны только для модуля новостей ГАРАНТ ПРАЙМ. Без них бот работает как обычно, на новостной запрос ответит "изменений не найдено" |

Без этих значений под рукой запускать бота бессмысленно — подготовьте их перед началом установки.

---

## А. Установка локально на этой машине (Windows)

### 1. Проверить Python

```powershell
python --version
```

Нужен Python 3.12 или новее. Если не установлен — скачать с https://www.python.org/downloads/ (при установке отметить "Add python.exe to PATH").

### 2. Получить код проекта

Если проект уже лежит локально (как сейчас) — просто перейти в его папку:

```powershell
cd "C:\Users\Дмитрий\Desktop\zerocoder_kurs\задание_9_vkbot_парсер"
```

Если разворачиваете с нуля из репозитория:

```powershell
git clone <репозиторий>
cd задание_9_vkbot_парсер
```

### 3. Создать и активировать виртуальное окружение

```powershell
python -m venv .venv

# PowerShell:
.venv\Scripts\Activate.ps1
# или CMD:
.venv\Scripts\activate.bat
```

После активации в начале строки терминала появится `(.venv)`.

### 4. Установить зависимости

```powershell
pip install -r requirements.txt
```

### 5. Установить браузер для модуля новостей ГАРАНТ ПРАЙМ

```powershell
playwright install chromium
```

(Нужно один раз; браузер скачивается в `%LOCALAPPDATA%\ms-playwright`.)

### 6. Настроить `.env`

Создать файл `.env` в корне проекта (рядом с `main.py`) со следующим содержимым:

```
VK_TOKEN=ваш_токен_сообщества
PROXYAPI_KEY=ваш_ключ_proxyapi

# Опционально, для модуля новостей ГАРАНТ ПРАЙМ:
GARANT_LOGIN=
GARANT_PASSWORD=
```

### 7. Проверить токены перед запуском

```powershell
python test_bot.py
```

Скрипт должен вывести `[OK] VK Token` и `[OK] ProxyAPI`. Если есть `[FAIL]` — проверить соответствующее значение в `.env`.

### 8. Прогнать автотесты (опционально, но рекомендуется)

```powershell
pytest
```

Ожидаемый результат — все тесты зелёные (сеть не используется, тесты работают на моках/фикстурах).

### 9. Запустить бота

```powershell
python main.py --vk         # VK-бот (то же самое, что и просто `python main.py`)
python main.py --console    # локальный чат в терминале — для проверки без VK
```

Для VK-бота: процесс должен вывести `Starting BotPolling for ...` и продолжать работать (это нормально — он слушает LongPoll и не завершается сам). Проверить работу — написать сообщение сообществу ВКонтакте.

Остановка — `Ctrl+C` в терминале.

---

## Б. Установка на удалённом сервере (Linux)

Ниже — вариант для Ubuntu/Debian-подобной системы (команды через `apt`). Для другого дистрибутива соответствующие пакеты нужно поставить их менеджером пакетов.

### 1. Подключиться к серверу

```bash
ssh user@ваш_сервер
```

### 2. Установить Python 3.12+ и git (если ещё не установлены)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
python3 --version   # убедиться, что 3.12+
```

Если в репозиториях дистрибутива более старый Python — подключить `deadsnakes` PPA или собрать из исходников (зависит от ОС).

### 3. Получить код проекта

```bash
git clone <репозиторий>
cd задание_9_vkbot_парсер
```

(Либо скопировать проект на сервер любым другим способом — `scp`, `rsync` и т.п., если репозитория ещё нет.)

### 4. Создать и активировать виртуальное окружение

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 5. Установить зависимости Python

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 6. Установить браузер и системные зависимости для Playwright

На "чистом" сервере Chromium требует системных библиотек — флаг `--with-deps` ставит их автоматически (потребует `sudo`):

```bash
sudo env "PATH=$PATH" python -m playwright install --with-deps chromium
```

Если `sudo` недоступен — установить пакеты вручную по списку из вывода команды `playwright install-deps` и затем `playwright install chromium` уже без `--with-deps`.

### 7. Настроить `.env`

```bash
nano .env
```

Содержимое — как в разделе А, шаг 6:

```
VK_TOKEN=ваш_токен_сообщества
PROXYAPI_KEY=ваш_ключ_proxyapi
GARANT_LOGIN=
GARANT_PASSWORD=
```

Сохранить (`Ctrl+O`, `Enter`, `Ctrl+X` в nano). Проверить, что файл не попадёт в git (`.gitignore` уже это учитывает).

### 8. Проверить токены и прогнать тесты

```bash
python test_bot.py
pytest
```

### 9. Пробный запуск (в текущей сессии терминала)

```bash
python main.py --vk
```

Проверить работу из ВКонтакте, затем остановить `Ctrl+C`. Только после успешной пробы переходить к запуску как постоянного сервиса (шаг 10) — иначе сервис будет молча падать по тем же причинам, которые проще увидеть в интерактивном режиме.

### 10. Запуск как постоянный сервис (чтобы бот работал после отключения от SSH и переживал перезагрузку сервера)

Рекомендуемый способ — `systemd`.

Создать файл `/etc/systemd/system/vkbot.service` (нужны root-права, `sudo nano ...`):

```ini
[Unit]
Description=VK AI-bot
After=network.target

[Service]
Type=simple
User=<ваш_пользователь_на_сервере>
WorkingDirectory=/полный/путь/до/задание_9_vkbot_парсер
ExecStart=/полный/путь/до/задание_9_vkbot_парсер/.venv/bin/python main.py --vk
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Подставить реальные пути (`pwd` в директории проекта покажет полный путь) и имя пользователя.

Применить и запустить:

```bash
sudo systemctl daemon-reload
sudo systemctl enable vkbot     # автозапуск при перезагрузке сервера
sudo systemctl start vkbot
```

Проверка статуса и логов:

```bash
sudo systemctl status vkbot
journalctl -u vkbot -f          # смотреть логи в реальном времени
```

Остановка/перезапуск:

```bash
sudo systemctl stop vkbot
sudo systemctl restart vkbot
```

**Альтернатива без systemd** (если нет root-доступа для создания unit-файла) — `tmux`/`screen`:

```bash
tmux new -s vkbot
# внутри сессии tmux:
source .venv/bin/activate
python main.py --vk
# отсоединиться от сессии, не останавливая процесс: Ctrl+B, затем D
```

Вернуться к сессии позже: `tmux attach -t vkbot`. Минус этого способа — бот не переживёт перезагрузку сервера и не перезапустится сам при падении (в отличие от `systemd` с `Restart=on-failure`).

### 11. Обновление кода на сервере

```bash
cd задание_9_vkbot_парсер
git pull
source .venv/bin/activate
pip install -r requirements.txt   # если requirements.txt менялся
sudo systemctl restart vkbot      # если используется systemd
```

---

## Проверка после запуска (общая для обоих сценариев)

1. Написать боту сообщение в сообществе ВКонтакте — должно прийти приветствие (при первом обращении) и ответ AI.
2. Написать что-то вроде «Что нового по охране?» или «Изменения в законодательстве» — должен сработать новостной модуль (при отсутствии `GARANT_LOGIN`/`GARANT_PASSWORD` — ответ «изменений не найдено», это ожидаемо).
3. Локально проверить второй интерфейс: `python main.py --console`.

## Частые проблемы

| Проблема | Причина / решение |
|---|---|
| `test_bot.py` пишет `[FAIL] VK Token` | Неверный или просроченный `VK_TOKEN` — перевыпустить в настройках сообщества |
| `test_bot.py` пишет `[FAIL] ProxyAPI` | Неверный `PROXYAPI_KEY` или закончился баланс на proxyapi.ru |
| При новостном запросе всегда «изменений не найдено» | Не заданы `GARANT_LOGIN`/`GARANT_PASSWORD`, либо разметка сайта demo.garant.ru ещё не до конца подтверждена (см. `TODO` в `core/news/parser.py` и раздел "Известные ограничения" в `README.md`) |
| Ошибка Playwright `Executable doesn't exist` | Не выполнен `playwright install chromium` (Windows) или `playwright install --with-deps chromium` (Linux) |
| На Windows в консоли (`--console`) кириллица выглядит как знаки вопроса/иероглифы | Кодировка терминала — сам интерфейс принудительно переключает stdin/stdout в UTF-8, но при пайпе через сторонние оболочки (например git-bash) вывод самого терминала может остаться в другой кодировке — на поведение бота это не влияет |
| Бот в systemd постоянно перезапускается (`Restart=on-failure` крутится) | Смотреть `journalctl -u vkbot -f` — почти всегда неверный путь в `WorkingDirectory`/`ExecStart` или отсутствующий `.env` |
