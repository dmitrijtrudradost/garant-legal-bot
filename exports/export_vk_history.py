"""Выгрузка истории переписки сообщества с пользователем через VK API.

Не pytest и не часть ядра бота — живой вызов messages.getConversations /
messages.getHistory по VK_TOKEN из .env (токен сообщества).

    python -m exports.export_vk_history
    python -m exports.export_vk_history --from 2026-09-10
    python -m exports.export_vk_history --from "2026-09-10 15:00" --to "2026-09-10 16:30"
    python -m exports.export_vk_history --peer-id 123456789 --from 2026-09-08
"""

from __future__ import annotations

import argparse
import asyncio
import os
import ssl
from datetime import datetime
from pathlib import Path

import aiohttp
import certifi
from dotenv import load_dotenv

VK_API_VERSION = "5.199"
VK_API_URL = "https://api.vk.com/method/{method}"
HISTORY_PAGE_SIZE = 200
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "downloads" / "dialogs"

_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())


class VkApiError(Exception):
    """Ошибка метода VK API. Текст без access_token."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"VK API error {code}: {message}")
        self.code = code
        self.vk_message = message


def parse_bound(value: str, *, end_of_day: bool) -> datetime:
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(value, fmt)
        except ValueError:
            continue
        if fmt == "%Y-%m-%d" and end_of_day:
            return parsed.replace(hour=23, minute=59, second=59)
        return parsed
    raise argparse.ArgumentTypeError(
        f"Ожидается ГГГГ-ММ-ДД или ГГГГ-ММ-ДД ЧЧ:ММ, получено: {value!r}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Выгрузить диалог пользователя с ботом VK в downloads/dialogs/"
    )
    parser.add_argument(
        "--peer-id",
        type=int,
        default=None,
        help="ID пользователя (vk.com/id…). Без флага — самый свежий диалог.",
    )
    parser.add_argument(
        "--from",
        dest="date_from",
        default=None,
        help="Начало интервала: ГГГГ-ММ-ДД или ГГГГ-ММ-ДД ЧЧ:ММ (локальное время ПК).",
    )
    parser.add_argument(
        "--to",
        dest="date_to",
        default=None,
        help="Конец интервала: ГГГГ-ММ-ДД или ГГГГ-ММ-ДД ЧЧ:ММ (локальное время ПК).",
    )
    return parser.parse_args()


async def vk_call(session: aiohttp.ClientSession, token: str, method: str, **params) -> dict:
    payload = {key: value for key, value in params.items() if value is not None}
    payload["access_token"] = token
    payload["v"] = VK_API_VERSION
    url = VK_API_URL.format(method=method)
    async with session.get(url, params=payload, ssl=_SSL_CONTEXT) as response:
        data = await response.json()
    if "error" in data:
        error = data["error"]
        raise VkApiError(int(error.get("error_code", 0)), str(error.get("error_msg", "unknown")))
    return data["response"]


async def resolve_peer_id(session: aiohttp.ClientSession, token: str, peer_id: int | None) -> int:
    if peer_id is not None:
        return peer_id
    response = await vk_call(session, token, "messages.getConversations", count=1)
    items = response.get("items") or []
    if not items:
        raise SystemExit("Диалогов с ботом нет — сообщество ещё ни с кем не переписывалось.")
    return int(items[0]["conversation"]["peer"]["id"])


async def fetch_history(session: aiohttp.ClientSession, token: str, peer_id: int) -> list[dict]:
    items: list[dict] = []
    offset = 0
    while True:
        response = await vk_call(
            session,
            token,
            "messages.getHistory",
            peer_id=peer_id,
            count=HISTORY_PAGE_SIZE,
            offset=offset,
        )
        page = response.get("items") or []
        if not page:
            break
        items.extend(page)
        if len(page) < HISTORY_PAGE_SIZE:
            break
        offset += len(page)
    items.sort(key=lambda message: message.get("date", 0))
    return items


def filter_by_range(
    items: list[dict],
    date_from: datetime | None,
    date_to: datetime | None,
) -> list[dict]:
    if date_from is None and date_to is None:
        return items
    from_ts = date_from.timestamp() if date_from else None
    to_ts = date_to.timestamp() if date_to else None
    selected: list[dict] = []
    for message in items:
        stamp = float(message.get("date", 0))
        if from_ts is not None and stamp < from_ts:
            continue
        if to_ts is not None and stamp > to_ts:
            continue
        selected.append(message)
    return selected


def role_for(from_id: int) -> str:
    return "бот" if from_id < 0 else "пользователь"


def message_text(message: dict) -> str:
    text = (message.get("text") or "").strip()
    if text:
        return text
    if message.get("attachments"):
        return "[вложение]"
    if message.get("action"):
        return f"[действие: {message['action'].get('type', 'unknown')}]"
    return "[пустое сообщение]"


def output_filename(peer_id: int) -> Path:
    """Имя с датой и временем выгрузки, чтобы файлы за один день не затирали друг друга."""
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return OUTPUT_DIR / f"{peer_id}_{stamp}.md"


def render_markdown(
    peer_id: int,
    items: list[dict],
    date_from: datetime | None,
    date_to: datetime | None,
) -> str:
    if date_from is None and date_to is None:
        interval = "вся доступная история"
    else:
        start = date_from.strftime("%Y-%m-%d %H:%M") if date_from else "начало"
        finish = date_to.strftime("%Y-%m-%d %H:%M") if date_to else "сейчас"
        interval = f"{start} — {finish}"

    lines = [
        f"# Диалог VK peer_id={peer_id}",
        "",
        f"- Выгружено: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
        f"- Интервал: {interval}",
        f"- Сообщений: {len(items)}",
        "",
    ]
    if not items:
        lines.append("_В выбранном интервале сообщений нет._")
        lines.append("")
        return "\n".join(lines)

    for message in items:
        when = datetime.fromtimestamp(message.get("date", 0)).strftime("%d.%m.%Y %H:%M")
        role = role_for(int(message.get("from_id", 0)))
        text = message_text(message).replace("\r\n", "\n")
        lines.append(f"**{when} | {role}**")
        lines.append("")
        lines.append(text)
        lines.append("")
    return "\n".join(lines)


async def export_history(args: argparse.Namespace) -> Path:
    token = os.getenv("VK_TOKEN", "").strip()
    if not token:
        raise SystemExit("VK_TOKEN не задан в .env")

    date_from = parse_bound(args.date_from, end_of_day=False) if args.date_from else None
    date_to = parse_bound(args.date_to, end_of_day=True) if args.date_to else None
    if date_from and date_to and date_from > date_to:
        raise SystemExit("--from позже --to")

    async with aiohttp.ClientSession() as session:
        peer_id = await resolve_peer_id(session, token, args.peer_id)
        items = await fetch_history(session, token, peer_id)

    items = filter_by_range(items, date_from, date_to)
    path = output_filename(peer_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(peer_id, items, date_from, date_to), encoding="utf-8")
    return path


def main() -> None:
    load_dotenv()
    args = parse_args()
    try:
        path = asyncio.run(export_history(args))
    except VkApiError as exc:
        raise SystemExit(f"[FAIL] {exc}") from exc
    print(f"[OK] Диалог сохранён: {path}")


if __name__ == "__main__":
    main()
