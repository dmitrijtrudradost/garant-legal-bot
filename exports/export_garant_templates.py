"""Выгрузка шаблонов договоров ГАРАНТ в Word.

    python -m exports.export_garant_templates --list
    python -m exports.export_garant_templates --limit 2
    python -m exports.export_garant_templates --only 10164072 --overwrite
"""

from __future__ import annotations

import argparse
import asyncio
import os

from dotenv import load_dotenv

from core.bot_core import format_limits
from core.garant.api_client import GARANT_API_BASE_URL, GarantApiClient, GarantApiError
from exports.garant_templates.catalog import CATALOG_TOPIC
from exports.garant_templates.converter import RtfToDocxConverter
from exports.garant_templates.exporter import GarantTemplateExporter, resolve_templates_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Скачать шаблоны договоров ГАРАНТ в .docx")
    parser.add_argument("--out", default=None, help="Папка (по умолчанию GARANT_TEMPLATES_DIR или downloads/templates)")
    parser.add_argument("--catalog", type=int, default=CATALOG_TOPIC, help="Topic каталога")
    parser.add_argument("--limit", type=int, default=None, help="Скачать не больше N шаблонов")
    parser.add_argument("--only", default=None, help="Только эти topic через запятую")
    parser.add_argument("--list", action="store_true", help="Только перечень, без скачивания")
    parser.add_argument("--overwrite", action="store_true", help="Скачать заново даже если файл уже есть")
    parser.add_argument("--keep-rtf", action="store_true", help="Не удалять RTF после успешной конвертации")
    return parser.parse_args()


def _filter_only(refs, raw: str | None):
    if not raw:
        return refs
    wanted = set()
    for part in raw.split(","):
        piece = part.strip()
        if piece.isdigit():
            wanted.add(int(piece))
    return [ref for ref in refs if ref.topic in wanted]


async def export_templates(args: argparse.Namespace) -> None:
    token = os.getenv("GARANT_TOKEN", "").strip()
    if not token:
        raise SystemExit("GARANT_TOKEN не задан в .env")

    client = GarantApiClient(token, GARANT_API_BASE_URL, log_name="GarantTemplates")
    exporter = GarantTemplateExporter(
        client,
        resolve_templates_dir(args.out),
        RtfToDocxConverter(os.getenv("LIBREOFFICE_PATH", ""), keep_rtf=args.keep_rtf),
    )
    refs = _filter_only(await exporter.list_templates(args.catalog), args.only)
    if args.list:
        for index, ref in enumerate(refs, start=1):
            print(f"{index}. {ref.topic} {ref.title}")
        print(f"Всего: {len(refs)}")
    else:
        summary = await exporter.export(refs, overwrite=args.overwrite, limit=args.limit)
        print(summary.message)
        for result in summary.results:
            place = result.path if result.path is not None else result.message
            print(f"- {result.status}: {result.topic} {place}")

    try:
        limits = await client.get_json("/v2/limits", scope="news")
    except GarantApiError as exc:
        print(exc.user_message)
        return
    if isinstance(limits, list):
        print(format_limits(limits))


def main() -> None:
    load_dotenv()
    args = parse_args()
    asyncio.run(export_templates(args))


if __name__ == "__main__":
    main()
