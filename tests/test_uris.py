import datetime

import pytest

from jgkg import uris
from jgkg.config import Settings

# 既定値と異なるベースURIを使い、設定が実際に読まれていることを証明する。
# .invalid は予約TLDなので、誤って本物のホストを指すことがない。
TEST_BASE = "https://uri-test.invalid/kg"


@pytest.fixture(autouse=True)
def fixed_base(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", TEST_BASE)
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_org_uri_uses_houjin_bangou():
    assert uris.org_uri("6000012070001") == f"{TEST_BASE}/id/org/6000012070001"


def test_org_uri_rejects_malformed_houjin_bangou():
    with pytest.raises(ValueError):
        uris.org_uri("12345")


def test_law_uri_and_version_uri():
    assert uris.law_uri("507M60000100010") == f"{TEST_BASE}/id/law/507M60000100010"
    assert uris.law_version_uri("507M60000100010", datetime.date(2026, 8, 1)) == (
        f"{TEST_BASE}/id/law/507M60000100010/20260801"
    )


def test_unresolved_jurisdiction_uri_is_keyed_by_law_id_and_name():
    """law_id と name の両方が材料になること。

    何があれば落ちるか: name だけで鍵にすると、同じ旧省庁名を指す別の法令が
    同一のURIに収束し、CQ9が数えたい「法令ごとの件数」が測れなくなる
    """
    a = uris.unresolved_jurisdiction_uri("326M50000400100", "大蔵省")
    b = uris.unresolved_jurisdiction_uri("331M50000400200", "大蔵省")
    assert a != b
    assert a == f"{TEST_BASE}/id/unresolved/jurisdiction/326M50000400100/%E5%A4%A7%E8%94%B5%E7%9C%81"


def test_unresolved_jurisdiction_uri_rejects_empty_parts():
    with pytest.raises(ValueError):
        uris.unresolved_jurisdiction_uri("", "大蔵省")
    with pytest.raises(ValueError):
        uris.unresolved_jurisdiction_uri("326M50000400100", "")


def test_graph_uri_encodes_source_and_date():
    assert uris.graph_uri("houjin-bangou", datetime.date(2026, 8, 1)) == (
        f"{TEST_BASE}/graph/houjin-bangou/2026-08-01"
    )


def test_term_uri_uses_fragment():
    assert uris.term_uri("org", "所管") == f"{TEST_BASE}/def/org#所管"


def test_base_uri_trailing_slash_is_normalized(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "https://uri-test.invalid/kg/")
    from jgkg.config import get_settings
    get_settings.cache_clear()
    assert Settings().base_uri == "https://uri-test.invalid/kg"
