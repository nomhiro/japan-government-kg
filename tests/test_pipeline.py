import datetime
from pathlib import Path

import pytest

from jgkg import lake, pipeline
from jgkg.connectors import houjin_bangou

DAY = datetime.date(2026, 8, 1)


@pytest.fixture(autouse=True)
def tmp_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "http://localhost:8080/kg")
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    monkeypatch.setenv("JGKG_QUARANTINE_DIR", str(tmp_path / "quarantine"))
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def seeded_lake():
    content = Path("tests/fixtures/houjin_bangou_sample.csv").read_bytes()
    lake.save("houjin-bangou", DAY, houjin_bangou.FILENAME, content)


def test_run_produces_nquads_and_report(seeded_lake, tmp_path):
    out = tmp_path / "out"
    report = pipeline.run(DAY, out)

    assert report.organizations == 4       # 入力の全件数
    assert report.government_organs == 3   # KGに入れた件数(株式会社1件を除外)
    assert report.ministries >= 1
    assert (out / "kg.nq").exists()

    # graphs は manifest に渡す契約なので、値そのものを固定する
    assert report.graphs_validated >= 2, "データグラフと出典グラフの少なくとも2つが検証される"
    assert report.graphs_quarantined == 0, "正常なfixtureで隔離が発生してはならない"
    assert report.graphs, "グラフ一覧が空である"
    assert all(g.startswith("http://localhost:8080/kg/graph/") for g in report.graphs), (
        f"想定外のグラフURIがある: {report.graphs}"
    )
    assert report.graphs == sorted(report.graphs), "グラフ一覧はソート済みであること"


def test_run_reports_unmatched_ministries(seeded_lake, tmp_path):
    """参照表にあってデータに無い府省を件数として報告する(設計書§8.2)。

    fixtureの参照表3府省はすべてfixture CSVに国の機関として存在するので、
    正常系では突合率100%になる。ここを厳密に固定することで、突合が壊れた
    ときに検出できる。
    """
    report = pipeline.run(DAY, tmp_path / "out")
    assert report.ministries == 3, "参照表の3府省すべてが突合されるべき"
    assert report.unmatched_ministries == 0, "正常系で未突合が出てはならない"


@pytest.fixture
def lake_with_duplicate_label():
    """同一法人番号で名称が違う行を1行足したスナップショット。

    訂正履歴・重複登録・並行する別名で実際に起こりうる。`emit_organizations` は
    法人番号ごとに `skos:prefLabel` を2つ出すので、生成SHACLの `sh:maxCount 1`
    に違反し、**その1件のためにそのソースのグラフ全体が隔離される。**
    """
    content = Path("tests/fixtures/houjin_bangou_sample.csv").read_bytes()
    extra = (
        "5,8000012070001,1,2015-10-05,2015-10-05,101,厚生労働省(旧称)"
        ",,,,100,8916,東京都,千代田区,霞が関1-2-2\n"
    )
    lake.save(
        "houjin-bangou",
        DAY,
        houjin_bangou.FILENAME,
        content.rstrip(b"\r\n") + b"\n" + extra.encode("utf-8"),
    )


def test_quarantine_stops_the_release(lake_with_duplicate_label, tmp_path):
    """隔離が起きたらリリース処理を止めること(設計書§6.3のリリースゲート)。

    **何があれば落ちるか**: `enforce_release_gate` が例外を投げなくなったら落ちる。
    以前は `build.sh` が `graphs_quarantined` を一切見ずに `exit 0` していたため、
    **中身が無いのに出典だけが残ったKGがそのまま出荷される**経路があった。
    """
    report = pipeline.run(DAY, tmp_path / "out")
    assert report.graphs_quarantined == 1, (
        f"重複ラベルで隔離が起きるという前提が崩れている: {report.model_dump()}"
    )

    with pytest.raises(pipeline.QuarantineNotEmptyError, match="隔離"):
        pipeline.enforce_release_gate(report)

    # 明示的に指定した場合だけ続行する(既定は止まる側)
    pipeline.enforce_release_gate(report, allow_partial=True)

    # 隔離の爆発半径を記録しておく: 法人番号グラフが丸ごと消え、出典グラフだけが残る。
    # これは C2 の未修正の残件(出典記述の除外)であり、ゲートで出荷を止めている
    remaining = report.graphs
    assert not any("graph/houjin-bangou/" in g for g in remaining), remaining
    assert any(g.endswith("/graph/provenance") for g in remaining), remaining


def test_release_gate_allows_a_clean_run(seeded_lake, tmp_path):
    """正常系ではゲートが通ること(常に例外を投げる実装になっていないこと)。"""
    report = pipeline.run(DAY, tmp_path / "out")
    assert report.graphs_quarantined == 0
    pipeline.enforce_release_gate(report)


def test_run_is_idempotent(seeded_lake, tmp_path):
    out = tmp_path / "out"
    first = pipeline.run(DAY, out)
    second = pipeline.run(DAY, out)
    assert first.organizations == second.organizations
    assert (out / "kg.nq").exists()


def test_run_fails_when_snapshot_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        pipeline.run(DAY, tmp_path / "out")
