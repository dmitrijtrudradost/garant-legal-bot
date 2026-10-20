
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
from core.news.parser_factory import GarantModeConfigError, NullNewsParser, get_news_parser
from core.news.results_cache import InMemoryNewsResultsCache
from interfaces.base import BaseInterface

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def build_bot_core() -> BotCore:
    ai_client = AIClient(api_key=os.getenv("PROXYAPI_KEY", ""))
    history = InMemoryDialogueHistory()
    dialogue_service = DialogueService(history, ai_client)

    try:
        news_parser = get_news_parser()
    except GarantModeConfigError as exc:
        # Явный режим (или mcp) указан, но не может быть использован — громко
        # логируем и продолжаем работу без новостного модуля, а не роняем бота
        # целиком (см. докстроку core/news/parser_factory.py).
        logger.error("Конфигурация новостного модуля ГАРАНТ: %s", exc)
        news_parser = NullNewsParser()

    news_formatter = NewsFormatter()
    intent_router = IntentRouter(ai_client=ai_client)
    results_cache = InMemoryNewsResultsCache()
    template_exporter = _template_exporter(news_parser)

    return BotCore(
        dialogue_service,
        intent_router,
        news_parser,
        news_formatter,
        results_cache,
        template_exporter=template_exporter,
    )


def build_interface(name: str, bot_core: BotCore) -> BaseInterface:
    if name == "vk":
        from interfaces.vk.vk_interface import VKInterface

        return VKInterface(bot_core, vk_token=os.getenv("VK_TOKEN", ""))

    if name == "console":
        from interfaces.console.console_interface import ConsoleInterface

        return ConsoleInterface(bot_core)

    raise ValueError(f"Неизвестный интерфейс: {name}")


def _template_exporter(news_parser):
    """Экспортёр шаблонов только при рабочем API-клиенте (режим api и токен)."""
    client = getattr(news_parser, "api_client", None)
    if client is None:
        return None
    from exports.garant_templates.converter import converter_from_env
    from exports.garant_templates.exporter import GarantTemplateExporter, resolve_templates_dir

    return GarantTemplateExporter(client, resolve_templates_dir(), converter_from_env())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Гарант-ai-бот — единая точка входа")
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
