from datetime import date

import pytest

from core.models import NewsQuery
from core.news.parser_mcp import GarantMcpParser


@pytest.mark.asyncio
async def test_fetch_raises_not_implemented():
    parser = GarantMcpParser()
    query = NewsQuery(date_from=date(2026, 1, 1), date_to=date(2026, 1, 31))

    with pytest.raises(NotImplementedError, match="не реализован"):
        await parser.fetch(query)
