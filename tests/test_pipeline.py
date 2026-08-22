import datetime
from pathlib import Path

import pytest
from zenken_rows import zenken_row, zipped

from jgkg import lake, pipeline
from jgkg.connectors import houjin_bangou

DAY = datetime.date(2026, 8, 1)
# 取得して来るソースの日付だけを渡す。参照表(ministry-codes)の日付は
# sources.py の recorded_on から取られる
FETCHED = {"houjin-bangou": DAY}


@pytest.fixture(autouse=True)
def tmp_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "https://jgkg.norr-tech.com")
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    monkeypatch.setenv("JGKG_QUARANTINE_DIR", str(tmp_path / "quarantine"))
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def seeded_lake():
    content = Path("tests/fixtures/houjin_bangou_sample.csv").read_text(encoding="utf-8")
    lake.save("houjin-bangou", DAY, houjin_bangou.FILENAME, zipped(content))


def test_run_produces_nquads_and_report(seeded_lake, tmp_path):
    out = tmp_path / "out"
    report = pipeline.run(FETCHED, out)

    assert report.organizations == 4       # 入力の全件数
    assert report.government_organs == 3   # KGに入れた件数(株式会社1件を除外)
    assert report.ministries >= 1
    assert (out / "kg.nq").exists()

    # graphs は manifest に渡す契約なので、値そのものを固定する
    assert report.graphs_validated >= 2, "データグラフと出典グラフの少なくとも2つが検証される"
    assert report.graphs_quarantined == 0, "正常なfixtureで隔離が発生してはならない"
    assert report.graphs, "グラフ一覧が空である"
    assert all(g.startswith("https://jgkg.norr-tech.com/graph/") for g in report.graphs), (
        f"想定外のグラフURIがある: {report.graphs}"
    )
    assert report.graphs == sorted(report.graphs), "グラフ一覧はソート済みであること"


def test_run_reports_unmatched_ministries(seeded_lake, tmp_path):
    """参照表にあってデータに無い府省を件数として報告する(設計書§8.2)。

    fixtureの参照表3府省はすべてfixture CSVに国の機関として存在するので、
    正常系では突合率100%になる。ここを厳密に固定することで、突合が壊れた
    ときに検出できる。
    """
    report = pipeline.run(FETCHED, tmp_path / "out")
    assert report.ministries == 3, "参照表の3府省すべてが突合されるべき"
    assert report.unmatched_ministries == 0, "正常系で未突合が出てはならない"


@pytest.fixture
def lake_with_duplicate_label():
    """同一法人番号で名称が違う行を1行足したスナップショット。

    訂正履歴・重複登録・並行する別名で実際に起こりうる。`emit_organizations` は
    法人番号ごとに `skos:prefLabel` を2つ出すので、生成SHACLの `sh:maxCount 1`
    に違反し、**その1件のためにそのソースのグラフ全体が隔離される。**
    """
    content = Path("tests/fixtures/houjin_bangou_sample.csv").read_text(encoding="utf-8")
    extra = (
        zenken_row(name="厚生労働省(旧称)", seq="5")
    )
    lake.save(
        "houjin-bangou",
        DAY,
        houjin_bangou.FILENAME,
        zipped(content.rstrip() + "\n" + extra),
    )


def test_quarantine_stops_the_release(lake_with_duplicate_label, tmp_path):
    """隔離が起きたらリリース処理を止めること(設計書§6.3のリリースゲート)。

    **何があれば落ちるか**: `enforce_release_gate` が例外を投げなくなったら落ちる。
    以前は `build.sh` が `graphs_quarantined` を一切見ずに `exit 0` していたため、
    **中身が無いのに出典だけが残ったKGがそのまま出荷される**経路があった。
    """
    report = pipeline.run(FETCHED, tmp_path / "out")
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

    # **manifest に渡す sources に隔離済みソースを載せない。**
    # `--allow-partial` で出荷したとき「houjin-bangou は 2026-08-01 のデータを
    # 含む」と書いてあるのにそのグラフが無い、という嘘になる(I2 と同族)
    assert "houjin-bangou" not in report.sources, report.sources
    assert report.quarantined_sources == ["houjin-bangou"], report.quarantined_sources
    # 落ちなかったソースは残る
    assert "ministry-codes" in report.sources, report.sources


def test_release_gate_allows_a_clean_run(seeded_lake, tmp_path):
    """正常系ではゲートが通ること(常に例外を投げる実装になっていないこと)。"""
    report = pipeline.run(FETCHED, tmp_path / "out")
    assert report.graphs_quarantined == 0
    pipeline.enforce_release_gate(report)


def test_run_reports_rejected_rows(tmp_path):
    """取り込まなかった行数がレポートに出ること。

    しきい値(`MIN_ACCEPT_RATIO` = 50%)の下では `ColumnLayoutError` が出ないため、
    以前は**最大49.9%の行が無音で消えていた**。`organizations` のコメントは
    「入力から解析した全件数」と書いてあったが、実際には取り込んだ件数だった。

    **何があれば落ちるか**: `_parse_reader` の集計を捨てる実装に戻したら落ちる。
    `rows_seen` を `organizations` と同じ値にしたら落ちる。
    """
    good = zenken_row()
    other = zenken_row(houjin_bangou="8000012050001", name="財務省", seq="2")
    # 法人番号が13桁でない行(集計行のような実データのノイズ)を2行混ぜる
    noise = "件数,2,,,,,,,,,,,,,\n"
    lake.save(
        "houjin-bangou",
        DAY,
        houjin_bangou.FILENAME,
        zipped(good + other + noise * 2),
    )

    report = pipeline.run(FETCHED, tmp_path / "out")

    assert report.rows_seen == 4, report.model_dump()
    assert report.organizations == 2, "取り込んだ件数"
    assert report.rows_rejected == 2, "捨てた行数が出ていない"
    assert report.rows_seen == report.organizations + report.rows_rejected


def test_parse_stats_counts_short_rows():
    """列数不足の行数が数えられること(住所などが空文字になっている行)。"""
    from jgkg.transform.organization import ParseStats, parse_text

    good = zenken_row()
    short = "2,8000012050001,1,2015-10-05,2015-10-05,101,財務省\n"  # 7列
    stats = ParseStats()
    orgs = list(parse_text(good * 3 + short, stats=stats))

    assert len(orgs) == 4
    assert stats.rows_seen == 4
    assert stats.rows_short == 1, "列数不足の行が数えられていない"
    assert stats.rows_rejected == 0, "13桁の法人番号は読めているので棄却ではない"


def test_run_records_a_date_per_source(seeded_lake, tmp_path):
    """ソースごとに「いつ時点か」を記録すること。

    以前は法人番号スナップショットの取得日を府省参照表の
    `prov:generatedAtTime` に流用しており、CQ P0-4 が2ソースのうち1つについて
    根拠のない日付を答えていた。参照表には取得日が存在しないので、
    リポジトリに記録した日(`sources.py` の `recorded_on`)を使う。

    **何があれば落ちるか**: `run` が単一日付を全ソースに流用する実装に戻ったら
    落ちる(2つの値が同じ日付になる)。
    """
    from jgkg.sources import get_source

    report = pipeline.run(FETCHED, tmp_path / "out")
    recorded_on = get_source("ministry-codes").recorded_on
    assert recorded_on is not None, "参照表の recorded_on が記録されていない"
    assert report.sources == {
        "houjin-bangou": DAY.isoformat(),
        "ministry-codes": recorded_on.isoformat(),
    }
    assert report.sources["houjin-bangou"] != report.sources["ministry-codes"], (
        "参照表の日付が法人番号の取得日と同じになっている(流用の再発)"
    )
    # リリース名は呼び出し側が渡した取得日から決まる(recorded_on を混ぜない)
    assert report.release == DAY.isoformat()


def test_run_refuses_to_guess_a_missing_fetch_date(seeded_lake, tmp_path):
    """取得日が渡されていないソースについて日付を捏造しないこと。"""
    with pytest.raises(ValueError, match="取得日が1件も渡されていない"):
        pipeline.run({}, tmp_path / "out")

    with pytest.raises(KeyError, match="houjin-bangou"):
        pipeline.run({"ministry-codes": DAY}, tmp_path / "out")


def test_reference_table_digest_matches_the_registry():
    """コミット済み参照表の内容が `sources.py` の記録と一致すること。

    参照表はレイクにスナップショットが無いので、内容ハッシュが「どの版を
    使ったか」の唯一の証拠になる。**何があれば落ちるか**: `ministry-codes.csv`
    を編集して `sources.py` の `sha256` / `recorded_on` を更新しなければ落ちる。
    """
    from jgkg.sources import content_digest, get_source

    src = get_source("ministry-codes")
    assert src.local_path, "参照表のパスが記録されていない"
    actual = content_digest(Path(src.local_path).read_bytes())
    assert actual == src.sha256, (
        f"参照表の内容が sources.py の記録と一致しない。"
        f" 実ファイル={actual} 記録={src.sha256}。"
        " 参照表を更新したなら sources.py の sha256 と recorded_on も更新する"
    )


def test_run_is_idempotent(seeded_lake, tmp_path):
    out = tmp_path / "out"
    first = pipeline.run(FETCHED, out)
    second = pipeline.run(FETCHED, out)
    assert first.organizations == second.organizations
    assert (out / "kg.nq").exists()


def test_run_fails_on_an_empty_snapshot(tmp_path):
    """0件を正常終了として返さないこと。

    列位置がずれていると `_cell` は空文字を返し、法人番号が13桁でない行は
    黙って捨てられるため、以前は `organizations=0` で「成功」を報告し、
    空のKGが build.sh から exit 0 で出荷された。
    """
    lake.save("houjin-bangou", DAY, houjin_bangou.FILENAME, zipped(""))
    with pytest.raises(ValueError, match="1件も解析できなかった"):
        pipeline.run(FETCHED, tmp_path / "out")


def test_run_fails_when_no_government_organ_is_found(tmp_path):
    """国の機関が0件なら失敗すること。

    法人種別の列がずれると `is_government_organ` が全行 False になる。
    その場合でも法人番号と種別コードの形は妥当なままなので、パース段では
    検出できない。**Phase 0 の対象は国の機関なので、0件のKGは成功ではない。**

    **何があれば落ちるか**: この下限チェックを外したら落ちる。
    """
    row = zenken_row(houjin_bangou="9999999999999", name="株式会社サンプル", kind="301", seq="3")
    lake.save("houjin-bangou", DAY, houjin_bangou.FILENAME, zipped(row * 3))
    with pytest.raises(ValueError, match="国の機関"):
        pipeline.run(FETCHED, tmp_path / "out")


def test_run_fails_when_snapshot_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        pipeline.run(FETCHED, tmp_path / "out")
