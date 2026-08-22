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


def test_partial_save_can_be_retried():
    """データ本体だけが残った中途半端な状態から再保存できること。

    メタデータ書き込みの失敗やプロセス中断でデータだけが残ったとき、
    それをコミット済みと誤判定すると、そのスナップショットは永久に
    再取得できなくなる(設計書§11.1の冪等性に反する)。
    """
    day = datetime.date(2026, 8, 1)
    d = lake._dir("houjin-bangou", day)
    d.mkdir(parents=True, exist_ok=True)
    # 中断されたsaveを模す: データ本体だけを置き、メタデータは書かない
    (d / "sample.csv").write_bytes(b"partial")

    # 再保存が拒否されず、正しくコミットされること
    snap = lake.save("houjin-bangou", day, "sample.csv", b"complete")
    assert snap.byte_size == len(b"complete")
    assert lake.load("houjin-bangou", day, "sample.csv") == b"complete"
    assert (d / "sample.csv.meta.json").exists()

    # コミット済みになったので、以後は不変
    with pytest.raises(FileExistsError):
        lake.save("houjin-bangou", day, "sample.csv", b"third")


def test_no_temp_files_left_after_save():
    """一時ファイルが残らないこと。"""
    day = datetime.date(2026, 8, 1)
    lake.save("houjin-bangou", day, "sample.csv", b"x")
    d = lake._dir("houjin-bangou", day)
    leftovers = [p.name for p in d.iterdir() if p.name.startswith(".") and p.name.endswith(".tmp")]
    assert leftovers == [], f"一時ファイルが残っている: {leftovers}"
