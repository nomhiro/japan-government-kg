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


def test_all_four_sources_share_the_same_pdl1_0_license():
    """B-1修正(2026-08-26): 4ソースとも「公共データ利用規約(第1.0版)」(PDL1.0)であること。

    以前は`egov-law`・`houjin-bangou`が「政府標準利用規約(第2.0版)」
    (URL: `https://www.digital.go.jp/resources/terms_of_use`)を記録していたが、
    一次資料(規約ページ本文)を直接確認すると、この2ソースも実際にはPDL1.0
    だった(政府標準利用規約は2024-07-05にPDL1.0へ改訂され廃止されている。
    旧URLは2026-08-26時点で404)。**何があれば落ちるか**: 4ソースのいずれか
    が古い「政府標準利用規約」に戻ると、あるいはURLが
    `terms_of_use`(旧・404)に戻ると落ちる。KGのprovenanceグラフ
    (`dcterms:license`/`dcterms:rights`)はここの値をそのまま書くため、
    ここが正しいことが公開KGの出典表示が正しいことの前提になる。
    """
    expected_license = "公共データ利用規約(第1.0版)(PDL1.0)"
    expected_url = "https://www.digital.go.jp/resources/open_data/public_data_license_v1.0"
    for source_id in ("houjin-bangou", "egov-law", "ministry-codes", "rs-system"):
        src = sources.get_source(source_id)
        assert src.license == expected_license, (source_id, src.license)
        assert src.license_url == expected_url, (source_id, src.license_url)
    assert "terms_of_use" not in sources.get_source("egov-law").license_url, (
        "廃止済み・404の旧URL(政府標準利用規約)に戻っていないこと"
    )


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


def test_path_of_matches_saved_location():
    day = datetime.date(2026, 8, 1)
    snap = lake.save("houjin-bangou", day, "sample.csv", b"x")
    assert lake.path_of("houjin-bangou", day, "sample.csv") == snap.path


# =============================================================================
# Task 10: latest_before(差分検出「前リリース時点でこのソースはどの版か」)
# =============================================================================


def test_latest_before_returns_the_snapshot_exactly_on_the_boundary_date():
    """`before` と同じ日付のスナップショットも対象に入ること(閉区間)。

    何があれば落ちるか: `fetched_on < before` (厳密未満)にすると、単一ソースの
    リリースでは release==fetched_on になるため、前リリース当日に取得した版が
    「1つ古い版」だと誤認され None または別の版が返る。
    """
    day = datetime.date(2026, 8, 1)
    snap = lake.save("houjin-bangou", day, "a.csv", b"x")
    assert lake.latest_before("houjin-bangou", before=day) == snap


def test_latest_before_picks_the_most_recent_snapshot_not_after_the_boundary():
    lake.save("houjin-bangou", datetime.date(2026, 6, 1), "a.csv", b"old")
    mid = lake.save("houjin-bangou", datetime.date(2026, 7, 1), "a.csv", b"mid")
    lake.save("houjin-bangou", datetime.date(2026, 8, 1), "a.csv", b"new")

    assert lake.latest_before("houjin-bangou", before=datetime.date(2026, 7, 15)) == mid


def test_latest_before_returns_none_when_no_snapshot_exists_yet():
    assert lake.latest_before("houjin-bangou", before=datetime.date(2026, 8, 1)) is None


def test_latest_before_returns_none_when_all_snapshots_are_after_the_boundary():
    lake.save("houjin-bangou", datetime.date(2026, 9, 1), "a.csv", b"future")
    assert lake.latest_before("houjin-bangou", before=datetime.date(2026, 8, 1)) is None


# =============================================================================
# Task 10: sources.py の expected_cadence_days(鮮度監視。src/jgkg/freshness.py)
# =============================================================================


def test_cadence_tracked_sources_have_the_documented_values():
    """3ソースにcadenceが設定され、値が仕様(brief)どおりであること。"""
    assert sources.get_source("houjin-bangou").expected_cadence_days == 31
    assert sources.get_source("egov-law").expected_cadence_days == 31
    assert sources.get_source("rs-system").expected_cadence_days == 366


def test_ministry_codes_has_no_cadence_expectation():
    """参照表(手動更新のみ)には鮮度の概念を適用しないこと(無期限=None)。"""
    assert sources.get_source("ministry-codes").expected_cadence_days is None
