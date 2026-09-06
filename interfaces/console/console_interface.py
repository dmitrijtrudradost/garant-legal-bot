"""ConsoleInterface — REPL-чат в терминале поверх того же BotCore, что и VK.

Полноценный аналог VK-бота: тот же диалог, та же история, тот же модуль
новостей — разница только в источнике ввода (input()) и выводе (print()).
"""

from __future__ import annotations

import asyncio
import sys

from core.bot_core import BotCore
from core.models import IncomingMessage
from interfaces.base import BaseInterface

EXIT_COMMANDS = {"/exit", "exit", "quit"}
CONSOLE_PEER_ID = "console-session"


class ConsoleInterface(BaseInterface):
    def __init__(self, bot_core: BotCore) -> None:
        super().__init__(bot_core)

    def run(self) -> None:
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:
        self._force_utf8_io()

        if self._bot_core.is_new_dialogue(CONSOLE_PEER_ID):
            print(self._bot_core.greeting_for(None))

        print("Введите сообщение (/exit для выхода):")
        while True:
            try:
                text = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nПока!")
                return

            if not text:
                continue
            if text.lower() in EXIT_COMMANDS:
                print("Пока!")
                return

            incoming = IncomingMessage(
                peer_id=CONSOLE_PEER_ID,
                user_name=None,
                text=text,
                interface="console",
            )
            outgoing = await self._bot_core.handle_message(incoming)
            print(outgoing.text)

    @staticmethod
    def _force_utf8_io() -> None:
        """На Windows кодировка stdin/stdout по умолчанию может быть не UTF-8
        (например, cp1251), из-за чего кириллица искажается при вводе/выводе.
        """
        for stream in (sys.stdin, sys.stdout):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                try:
                    reconfigure(encoding="utf-8")
                except (ValueError, OSError):
                    pass
