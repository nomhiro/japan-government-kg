import datetime
from pathlib import Path

import httpx
import pytest

from jgkg import lake
from jgkg.connectors import houjin_bangou


@pytest.fixture(autouse=True)
def tmp_lake(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def sample_bytes():
    return Path("tests/fixtures/houjin_bangou_sample.csv").read_bytes()


def _client(payload: bytes) -> httpx.Client:
    def handler(request):
        return httpx.Response(200, content=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_saves_snapshot_to_lake(sample_bytes):
    day = datetime.date(2026, 8, 1)
    result = houjin_bangou.fetch("https://example.test/zenken.zip", day, client=_client(sample_bytes))

    assert result.skipped is False
    assert result.snapshot.source_id == "houjin-bangou"
    assert lake.load("houjin-bangou", day, houjin_bangou.FILENAME) == sample_bytes


def test_fetch_is_idempotent(sample_bytes):
    """同じ取得日に2度呼んでも例外にならず、2度目はスキップされる。

    冪等性は設計書§11.1の要件。中断からの再開を可能にする。
    """
    day = datetime.date(2026, 8, 1)
    houjin_bangou.fetch("https://example.test/z.zip", day, client=_client(sample_bytes))
    second = houjin_bangou.fetch("https://example.test/z.zip", day, client=_client(sample_bytes))

    assert second.skipped is True
    assert second.snapshot.sha256


def test_fetch_raises_on_http_error():
    def handler(request):
        return httpx.Response(503)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        houjin_bangou.fetch("https://example.test/z.zip", datetime.date(2026, 8, 1), client=client)
