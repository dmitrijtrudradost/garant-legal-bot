"""Выгрузка шаблонов договоров: метаданные, RTF, DOCX, manifest.json.

Пауза между вызовами API — не меньше 0.1 с (лимит 20 запросов/с).
423 останавливает всю выгрузку. 403 и 404 пропускают шаблон.
Платный и недоступный `access` не скачивается.
Повторный запуск докачивает только новое и документы с другим `last_modified`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from core.garant.api_client import GarantApiError, GarantApiNotFoundError
from exports.garant_templates.catalog import (
    CATALOG_TOPIC,
    TemplateRef,
    parse_template_links,
    safe_filename,
)
from exports.garant_templates.converter import RtfToDocxConverter

logger = logging.getLogger(__name__)

INTER_CALL_DELAY_SECONDS = 0.1
DOWNLOADABLE_ACCESS = frozenset({"ACCESS_IS_FREE"})
MANIFEST_NAME = "manifest.json"


class TemplateQuotaExhausted(Exception):
    """423 — месячная квота метода исчерпана, продолжать выгрузку нельзя."""

    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


@dataclass
class ExportResult:
    topic: int
    title: str
    status: str
    path: Path | None
    message: str


@dataclass
class ExportSummary:
    downloaded: int
    skipped: int
    errors: int
    stopped: bool
    message: str
    results: list[ExportResult]


def resolve_templates_dir(raw: str | None = None) -> Path:
    """`GARANT_TEMPLATES_DIR` или `downloads/templates` относительно текущего каталога."""
    if raw is None:
        raw = os.getenv("GARANT_TEMPLATES_DIR", "")
    value = (raw or "").strip()
    path = Path(value) if value else Path("downloads") / "templates"
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


class GarantTemplateExporter:
    def __init__(self, client, out_dir: Path, converter: RtfToDocxConverter) -> None:
        self._client = client
        self._out_dir = Path(out_dir)
        self._converter = converter
        self._manifest = self._load_manifest()
        self._api_calls = 0

    @property
    def out_dir(self) -> Path:
        return self._out_dir

    async def list_templates(self, catalog_topic: int = CATALOG_TOPIC) -> list[TemplateRef]:
        data = await self._client.get_json(f"/v2/topic/{catalog_topic}/html", scope="document")
        items = data.get("items") if isinstance(data, dict) else []
        return parse_template_links(list(items or []), catalog_topic=catalog_topic)

    async def export(
        self,
        refs: list[TemplateRef],
        *,
        overwrite: bool = False,
        limit: int | None = None,
    ) -> ExportSummary:
        selected = list(refs)
        if limit is not None:
            selected = selected[: max(limit, 0)]
        self._out_dir.mkdir(parents=True, exist_ok=True)
        self._api_calls = 0
        results: list[ExportResult] = []
        downloaded = skipped = errors = 0
        stopped = False
        stop_message = ""
        for ref in selected:
            try:
                result = await self._export_one(ref, overwrite=overwrite)
            except TemplateQuotaExhausted as exc:
                stopped = True
                stop_message = exc.user_message
                break
            results.append(result)
            if result.status == "ok":
                downloaded += 1
            elif result.status == "skipped":
                skipped += 1
            else:
                errors += 1
        counts = f"Скачано: {downloaded}, пропущено: {skipped}, ошибок: {errors}."
        if stopped:
            message = f"{stop_message} {counts}"
        else:
            message = counts
        return ExportSummary(downloaded, skipped, errors, stopped, message, results)

    async def _export_one(self, ref: TemplateRef, *, overwrite: bool) -> ExportResult:
        try:
            meta = await self._get_json(f"/v2/topic/{ref.topic}")
        except TemplateQuotaExhausted:
            raise
        except _Skipped as exc:
            self._remember(ref, status="skipped", message=exc.message)
            return ExportResult(ref.topic, ref.title, "skipped", None, exc.message)
        except _Failed as exc:
            self._remember(ref, status="error", message=exc.message)
            return ExportResult(ref.topic, ref.title, "error", None, exc.message)

        if not isinstance(meta, dict):
            message = "Неожиданный ответ информации о документе."
            self._remember(ref, status="error", message=message)
            return ExportResult(ref.topic, ref.title, "error", None, message)

        access = meta.get("access")
        if access not in DOWNLOADABLE_ACCESS:
            message = f"Нет доступа по лицензии ({access})."
            logger.warning("Шаблон %s пропущен: access=%s", ref.topic, access)
            self._remember(ref, status="skipped", last_modified=_modified(meta), message=message)
            return ExportResult(ref.topic, ref.title, "skipped", None, message)

        last_modified = _modified(meta)
        cached = self._cached_file(ref.topic, last_modified, overwrite=overwrite)
        if cached is not None:
            return ExportResult(ref.topic, ref.title, "skipped", cached, "Файл уже скачан, дата не менялась.")

        try:
            payload = await self._get_bytes(f"/v2/topic/{ref.topic}/download")
        except TemplateQuotaExhausted:
            raise
        except _Skipped as exc:
            self._remember(ref, status="skipped", last_modified=last_modified, message=exc.message)
            return ExportResult(ref.topic, ref.title, "skipped", None, exc.message)
        except _Failed as exc:
            self._remember(ref, status="error", last_modified=last_modified, message=exc.message)
            return ExportResult(ref.topic, ref.title, "error", None, exc.message)

        if not payload.startswith(b"{\\rtf"):
            message = "Ответ /download не является RTF."
            self._remember(ref, status="error", last_modified=last_modified, message=message)
            return ExportResult(ref.topic, ref.title, "error", None, message)

        docx_name = safe_filename(ref.topic, ref.title, ".docx")
        rtf_path = self._out_dir / Path(docx_name).with_suffix(".rtf").name
        rtf_path.write_bytes(payload)
        delivered = await self._converter.convert(rtf_path)
        self._remember(
            ref,
            status="ok",
            file=delivered.name,
            last_modified=last_modified,
            message="",
        )
        return ExportResult(ref.topic, ref.title, "ok", delivered, "")

    async def _get_json(self, path: str) -> dict | list:
        await self._pause()
        try:
            return await self._client.get_json(path, scope="document")
        except GarantApiError as exc:
            self._raise_api(exc)
            raise

    async def _get_bytes(self, path: str) -> bytes:
        await self._pause()
        try:
            return await self._client.get_bytes(path, scope="document")
        except GarantApiError as exc:
            self._raise_api(exc)
            raise

    @staticmethod
    def _raise_api(exc: GarantApiError):
        if exc.status == 423:
            raise TemplateQuotaExhausted(exc.user_message) from exc
        if isinstance(exc, GarantApiNotFoundError) or exc.status in (403, 404):
            raise _Skipped(exc.user_message) from exc
        raise _Failed(exc.user_message) from exc

    async def _pause(self) -> None:
        if self._api_calls:
            await asyncio.sleep(INTER_CALL_DELAY_SECONDS)
        self._api_calls += 1

    def _cached_file(self, topic: int, last_modified: str, *, overwrite: bool) -> Path | None:
        if overwrite:
            return None
        entry = self._manifest.get(str(topic)) or {}
        if entry.get("status") != "ok" or entry.get("last_modified") != last_modified:
            return None
        filename = entry.get("file")
        if not isinstance(filename, str) or not filename:
            return None
        path = self._out_dir / filename
        if path.is_file():
            return path
        return None

    def _remember(
        self,
        ref: TemplateRef,
        *,
        status: str,
        message: str,
        file: str | None = None,
        last_modified: str = "",
    ) -> None:
        entry = {
            "topic": ref.topic,
            "title": ref.title,
            "file": file or "",
            "last_modified": last_modified,
            "status": status,
            "message": message,
        }
        self._manifest[str(ref.topic)] = entry
        self._save_manifest()

    def _load_manifest(self) -> dict[str, dict]:
        path = self._out_dir / MANIFEST_NAME
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return {}
        templates = data.get("templates") if isinstance(data, dict) else None
        if not isinstance(templates, dict):
            return {}
        return {str(key): value for key, value in templates.items() if isinstance(value, dict)}

    def _save_manifest(self) -> None:
        self._out_dir.mkdir(parents=True, exist_ok=True)
        payload = {"templates": self._manifest}
        (self._out_dir / MANIFEST_NAME).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class _Skipped(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class _Failed(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _modified(meta: dict) -> str:
    value = meta.get("last_modified")
    return value.strip() if isinstance(value, str) else ""
