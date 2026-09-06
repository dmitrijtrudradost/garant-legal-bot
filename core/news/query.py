"""NewsQuery — реэкспорт из core.models для удобства импорта из пакета news.

Сам датакласс определён в core/models.py вместе с остальными общими моделями
ядра (см. ТЗ, раздел 2: core/models.py содержит в т.ч. NewsQuery).
"""

from __future__ import annotations

from core.models import NewsQuery

__all__ = ["NewsQuery"]
