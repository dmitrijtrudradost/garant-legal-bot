"""RTF шаблона ГАРАНТ → DOCX через LibreOffice (`soffice --headless`).

Метода DOCX у API нет: `GET /v2/topic/{id}/download` возвращает RTF
(сверено 20.10.2026, тело `{\\rtf1`). Если soffice не найден, RTF остаётся
на диске — Word его открывает.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

CONVERT_TIMEOUT_SECONDS = 120
_WINDOWS_SOFFICE = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")
_LINUX_SOFFICE = Path("/usr/bin/soffice")


class RtfToDocxConverter:
    """Конвертация одного RTF. `keep_rtf=True` не удаляет исходник после успеха."""

    def __init__(self, soffice_path: str | None = None, *, keep_rtf: bool = False) -> None:
        explicit = (soffice_path or "").strip()
        self._explicit = explicit or None
        self._keep_rtf = keep_rtf

    def resolve_soffice(self) -> str | None:
        if self._explicit:
            candidate = Path(self._explicit)
            if candidate.is_file():
                return str(candidate)
            found = shutil.which(self._explicit)
            return found
        found = shutil.which("soffice")
        if found:
            return found
        if _WINDOWS_SOFFICE.is_file():
            return str(_WINDOWS_SOFFICE)
        if _LINUX_SOFFICE.is_file():
            return str(_LINUX_SOFFICE)
        return None

    async def convert(self, rtf_path: Path) -> Path:
        """DOCX рядом с RTF. Нет LibreOffice или сбой конвертации — возвращается RTF."""
        soffice = self.resolve_soffice()
        if soffice is None:
            logger.error(
                "LibreOffice не найден (LIBREOFFICE_PATH или soffice в PATH). Оставлен RTF: %s",
                rtf_path,
            )
            return rtf_path

        docx_path = rtf_path.with_suffix(".docx")
        process = await asyncio.create_subprocess_exec(
            soffice,
            "--headless",
            "--convert-to",
            "docx",
            "--outdir",
            str(rtf_path.parent),
            str(rtf_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=CONVERT_TIMEOUT_SECONDS)
        except TimeoutError:
            process.kill()
            await process.wait()
            logger.error("LibreOffice не успел сконвертировать %s за %s с", rtf_path.name, CONVERT_TIMEOUT_SECONDS)
            return rtf_path

        if process.returncode != 0 or not docx_path.is_file():
            logger.error(
                "LibreOffice не создал DOCX для %s (код %s): %s",
                rtf_path.name,
                process.returncode,
                (stderr or stdout or b"").decode("utf-8", errors="replace")[:500],
            )
            return rtf_path

        if not self._keep_rtf:
            rtf_path.unlink(missing_ok=True)
        return docx_path


def converter_from_env(*, keep_rtf: bool = False) -> RtfToDocxConverter:
    return RtfToDocxConverter(os.getenv("LIBREOFFICE_PATH", ""), keep_rtf=keep_rtf)
