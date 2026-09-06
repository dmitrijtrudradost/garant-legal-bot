"""Единая точка входа: собирает зависимости ядра и запускает выбранный интерфейс.

    python main.py --vk         # VK-бот (по умолчанию, для обратной совместимости)
    python main.py --console    # локальный чат в терминале

Никакой бизнес-логики здесь — только сборка зависимостей и выбор интерфейса.
"""

from __future__ import annotations

import argparse
import logging
import os

from dotenv import load_dotenv

from core.ai_client import AIClient
from core.bot_core import BotCore
from core.dialogue_service import DialogueService
from core.history import InMemoryDialogueHistory
from core.intent_router import IntentRouter
from core.news.formatter import NewsFormatter
from core.news.parser import GarantPrimeParser
from interfaces.base import BaseInterface

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def build_bot_core() -> BotCore:
    ai_client = AIClient(api_key=os.getenv("PROXYAPI_KEY", ""))
    history = InMemoryDialogueHistory()
    dialogue_service = DialogueService(history, ai_client)

    news_parser = GarantPrimeParser(
        login=os.getenv("GARANT_LOGIN", ""),
        password=os.getenv("GARANT_PASSWORD", ""),
    )
    news_formatter = NewsFormatter()
    intent_router = IntentRouter()

    return BotCore(dialogue_service, intent_router, news_parser, news_formatter)


def build_interface(name: str, bot_core: BotCore) -> BaseInterface:
    if name == "vk":
        from interfaces.vk.vk_interface import VKInterface

        return VKInterface(bot_core, vk_token=os.getenv("VK_TOKEN", ""))

    if name == "console":
        from interfaces.console.console_interface import ConsoleInterface

        return ConsoleInterface(bot_core)

    raise ValueError(f"Неизвестный интерфейс: {name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="VK AI-бот — единая точка входа")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--vk", action="store_const", dest="interface", const="vk")
    group.add_argument("--console", action="store_const", dest="interface", const="console")
    parser.set_defaults(interface="vk")
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()

    bot_core = build_bot_core()
    interface = build_interface(args.interface, bot_core)
    interface.run()


if __name__ == "__main__":
    main()
