import datetime
import hashlib

import pytest

from jgkg import lake, sources


@pytest.fixture(autouse=True)
def tmp_lake(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_registry_has_houjin_bangou_with_license():
    src = sources.get_source("houjin-bangou")
    assert src.name
    assert src.url.startswith("https://")
    assert src.license, "ライセンスが未記録のソースを登録してはならない(設計書§11.2)"
    assert src.frequency == "monthly"


def test_get_unknown_source_raises():
    with pytest.raises(KeyError):
        sources.get_source("no-such-source")


def test_save_then_load_roundtrip():
    content = b"col1,col2\n1,2\n"
    day = datetime.date(2026, 8, 1)
    snap = lake.save("houjin-bangou", day, "sample.csv", content)

    assert snap.sha256 == hashlib.sha256(content).hexdigest()
    assert snap.byte_size == len(content)
    assert snap.path.exists()
    assert lake.load("houjin-bangou", day, "sample.csv") == content


def test_snapshots_are_immutable():
    day = datetime.date(2026, 8, 1)
    lake.save("houjin-bangou", day, "sample.csv", b"first")
    with pytest.raises(FileExistsError):
        lake.save("houjin-bangou", day, "sample.csv", b"second")


def test_latest_returns_newest_date():
    lake.save("houjin-bangou", datetime.date(2026, 7, 1), "a.csv", b"x")
    lake.save("houjin-bangou", datetime.date(2026, 8, 1), "a.csv", b"y")
    assert lake.latest("houjin-bangou") == datetime.date(2026, 8, 1)


def test_latest_is_none_when_empty():
    assert lake.latest("houjin-bangou") is None
