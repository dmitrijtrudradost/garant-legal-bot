import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def proxyapi_sample_response() -> dict:
    return json.loads((FIXTURES_DIR / "proxyapi_sample_response.json").read_text(encoding="utf-8"))


@pytest.fixture
def garant_prime_sample_html() -> str:
    return (FIXTURES_DIR / "garant_prime_sample.html").read_text(encoding="utf-8")


@pytest.fixture
def garant_api_categories_sample() -> dict:
    return json.loads((FIXTURES_DIR / "garant_api_prime_categories_sample.json").read_text(encoding="utf-8"))


@pytest.fixture
def garant_api_news_sample() -> dict:
    return json.loads((FIXTURES_DIR / "garant_api_prime_news_sample.json").read_text(encoding="utf-8"))


@pytest.fixture
def garant_api_categories_branched_sample() -> dict:
    return json.loads(
        (FIXTURES_DIR / "garant_api_prime_categories_branched_sample.json").read_text(encoding="utf-8")
    )
