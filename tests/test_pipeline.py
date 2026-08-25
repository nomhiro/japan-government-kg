import datetime
from pathlib import Path

import pytest
from zenken_rows import zenken_row, zipped

from jgkg import lake, pipeline
from jgkg.connectors import egov_law, houjin_bangou

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

    assert report.organizations == 41       # 入力の全件数(現行40機関+株式会社1件)
    assert report.government_organs == 40   # KGに入れた件数(株式会社1件を除外)
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

    裁定B15で参照表は40行(RS実データの[5]所管府省庁/政策所管府省庁列と
    [6]府省庁列のdistinctの和集合37件 + 法令経路3機関)に拡張された。
    `houjin_bangou_sample.csv` もこの40機関すべてを実在の法人番号で
    含む(R45)ので、正常系では突合率100%になる。ここを厳密に固定することで、
    突合が壊れたときに検出できる。
    """
    report = pipeline.run(FETCHED, tmp_path / "out")
    assert report.ministries == 40, "参照表の40機関すべてが突合されるべき"
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


def test_run_reports_no_reference_violations_for_current_pipeline_output(seeded_lake, tmp_path):
    """裁定B4: 参照整合ゲートの結果がレポートに乗ること。

    現状の`pipeline.run`はhoujin-bangou/ministry-codesしか流していないため、
    参照制約(`law:jurisdiction`等)を持つデータはまだ無い。**空であること自体を
    固定する**(フィールドの存在と、法令をまだ流していない現状での既定動作)。
    法令を流すpipelineへの結線はTask 4の範囲外(Task 7/9/11)。
    """
    report = pipeline.run(FETCHED, tmp_path / "out")
    assert report.reference_violations == []


def test_enforce_release_gate_stops_on_reference_violations():
    """参照整合ゲートの違反も、SHACL隔離と同じ扱いでリリースを止めること(裁定B4)。

    `graphs_quarantined == 0` でも `reference_violations` が非空なら止まる
    (どちらか一方だけを見る実装に戻ったら落ちる)。
    """
    report = pipeline.PipelineReport(
        release="2026-08-01",
        rows_seen=1,
        rows_rejected=0,
        rows_short=0,
        organizations=1,
        government_organs=1,
        ministries=1,
        unmatched_ministries=0,
        graphs_validated=2,
        graphs_quarantined=0,
        graphs=["https://jgkg.norr-tech.com/graph/egov-law/2026-08-01"],
        sources={},
        quarantined_sources=[],
        reference_violations=[
            ".../id/law/1 -.../jurisdiction-> .../unresolved/x: 型が無い(期待クラス: .../Organization)"
        ],
    )
    with pytest.raises(pipeline.QuarantineNotEmptyError, match="参照整合"):
        pipeline.enforce_release_gate(report)

    # 明示的に指定した場合だけ続行する(既定は止まる側。既存のSHACL隔離と同じ契約)
    pipeline.enforce_release_gate(report, allow_partial=True)


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
    # リリース名は成果物ディレクトリのbasenameから決まる(Ruling B31。
    # 取得日やrecorded_onを混ぜない——同じ日に複数リリースを作ると
    # 取得日ベースの同一性は衝突するため)
    assert report.release == "out", (
        f"リリース名がout_dirのbasenameになっていない: {report.release!r}"
    )


def test_run_same_day_releases_are_distinguishable_by_release_field(seeded_lake, tmp_path):
    """Ruling B31の判定基準(a): 同日に作った2つのリリースがmanifestだけで

    区別できること。取得日を全く変えずに`out_dir`だけを変えた2回の`run()`が、
    異なる`release`を報告することを確認する(以前の`max(fetched_on.values())`
    方式では、取得日が同じなら両方とも同じ`release`になり、manifest.jsonだけを
    見ても区別できなかった——Task 11で実際に踏んだ不具合)。

    何があれば落ちるか: `release`を再び`max(fetched_on.values())`のような
    取得日由来の値に戻すと、releaseAとreleaseBが同じ文字列になり、
    このテストの`!=`アサーションが落ちる。
    """
    release_a = pipeline.run(FETCHED, tmp_path / "2026-08-25")
    release_b = pipeline.run(FETCHED, tmp_path / "2026-08-26")

    assert release_a.release != release_b.release, (
        "取得日が同じ2つのリリースのreleaseフィールドが衝突している"
        "(manifestだけではリリースを区別できない。Ruling B31違反)"
    )
    assert release_a.release == "2026-08-25"
    assert release_b.release == "2026-08-26"


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


# =============================================================================
# Task 8 Step 4: --include-all-corporations 相当のフラグ
#
# 全法人は`graph/houjin-bangou-all/{日付}`という別グラフに、kg.nqへの追記の
# 形で足す(国の機関の既存グラフは変えない)。既定(フラグ未指定)では触らない。
# =============================================================================


def test_run_without_the_flag_leaves_all_corporations_untouched(seeded_lake, tmp_path):
    """既定(フラグ未指定)では全法人グラフに触れないこと(§8.2の作法を裏側で守る:

    新しい経路を追加しても、既存の縦スライスの振る舞いを変えない)。
    """
    from jgkg import uris

    report = pipeline.run(FETCHED, tmp_path / "out")

    assert report.corporations_all == 0
    assert report.corporations_all_dedup_removed == 0
    assert report.corporations_all_quarantined == 0
    all_graph_uri = uris.graph_uri("houjin-bangou-all", DAY)
    assert all_graph_uri not in report.graphs


def test_run_with_the_flag_streams_all_corporations_into_a_separate_graph_appended_to_kg_nq(
    seeded_lake, tmp_path
):
    """フラグON: houjin-bangou-allが別グラフとしてkg.nqに追記され、レポートに

    corporations_all/dedup件数が乗ること。既存の国の機関グラフ(848件規模の
    縦スライス)は変えない、という設計上の要求(task-8-brief.md)を、
    「両方のグラフがkg.nqに存在する」ことで確認する。
    """
    from jgkg import uris

    out = tmp_path / "out"
    report = pipeline.run(FETCHED, out, include_all_corporations=True)

    all_graph_uri = uris.graph_uri("houjin-bangou-all", DAY)
    gov_graph_uri = uris.graph_uri("houjin-bangou", DAY)
    assert all_graph_uri in report.graphs
    assert gov_graph_uri in report.graphs, "国の機関の既存グラフが変わってしまっている"
    # fixtureの全件数(現行40機関+株式会社1件。test_run_produces_nquads_and_reportと同じ数)
    assert report.corporations_all == 41
    assert report.corporations_all_dedup_removed == 0
    assert report.corporations_all_quarantined == 0

    kg_text = (out / "kg.nq").read_text(encoding="utf-8")
    assert f"<{all_graph_uri}>" in kg_text, "houjin-bangou-allグラフがkg.nqに追記されていない"

    # O-10: 合格時は中間ファイル(houjin-bangou-all.nq)を削除すること。
    # 内容はkg.nqへ追記済みで二重に持つ理由が無く、581万件規模(約1GB)を
    # 毎回残すと成果物ディレクトリが肥大する
    assert not (out / "houjin-bangou-all.nq").exists(), (
        "合格したのに中間ファイルが残っている"
    )


def test_run_with_the_flag_dedups_and_reports_the_removed_count(
    lake_with_duplicate_label, tmp_path
):
    """全法人ストリームは法人番号の重複を後勝ちでdedupし、除いた件数を報告する。

    使うフィクスチャ(`lake_with_duplicate_label`)は既存の国の機関パスでは
    SHACL不合格(skos:prefLabelが2つ)→隔離を起こすもの(test_quarantine_stops_
    the_release参照)。houjin-bangou-all側はdedupがSHACLより先に重複を解消
    するため、**この部分は隔離されない**ことを対比として示す。
    """
    report = pipeline.run(FETCHED, tmp_path / "out", include_all_corporations=True)

    assert report.corporations_all_dedup_removed == 1, (
        "重複行がdedupされたことが報告されていない(消したことを黙らない)"
    )
    assert report.corporations_all_quarantined == 0, (
        "dedupで解消されたはずの重複が、全法人グラフの隔離を引き起こしている"
    )


def test_run_with_the_flag_records_provenance_for_the_new_graph(seeded_lake, tmp_path):
    """原則7(出典の無い事実をKGに入れない)。houjin-bangou-allグラフにも

    PROV-O記述が存在すること(emit.pyの他の全グラフと同じ扱い)。
    """
    from rdflib import Dataset, URIRef
    from rdflib.namespace import PROV

    from jgkg import uris

    out = tmp_path / "out"
    pipeline.run(FETCHED, out, include_all_corporations=True)
    all_graph_uri = uris.graph_uri("houjin-bangou-all", DAY)

    ds = Dataset(default_union=True)
    ds.parse(out / "kg.nq", format="nquads")
    described = list(ds.objects(URIRef(all_graph_uri), PROV.wasDerivedFrom))
    assert described, f"houjin-bangou-allグラフに出典の記述が無い: {all_graph_uri}"


def test_run_with_the_flag_adds_the_new_graphs_provenance_before_the_shacl_gate_runs(
    seeded_lake, tmp_path, monkeypatch
):
    """F-5: houjin-bangou-allの出典トリプルは、`validate_dataset`が呼ばれる

    **前**に`ds`へ追加されていること(順序そのものを直接確認する)。

    以前は`passing_dataset`が返した`clean`に後からこのグラフを足していたため、
    `validate_dataset`はこの出典トリプルを一度も見ないまま素通りしていた。
    出典グラフは`rdf:type`を持たずSHACLが何も制約しないため、この順序違いは
    最終的なkg.nqの見た目(トリプル数やgraphs_validatedの値)には現れない
    — houjin-bangou以外のソースの出典も同じ`/graph/provenance`という
    1つの名前付きグラフに集約されるため、グラフの個数自体はフラグの有無で
    変わらない。そのため、`validate_dataset`をラップして**呼ばれた瞬間の
    dsの中身**を直接覗く(順序という観測しにくい性質を直接確認する)。
    """
    from rdflib import URIRef
    from rdflib.namespace import PROV

    from jgkg import uris
    from jgkg import validate as validate_mod

    all_graph_uri = uris.graph_uri("houjin-bangou-all", DAY)
    real_validate_dataset = validate_mod.validate_dataset
    seen_at_call_time: list[bool] = []

    def _spy(ds, shapes_dir):
        seen_at_call_time.append(
            (URIRef(all_graph_uri), PROV.wasDerivedFrom, None) in ds
        )
        return real_validate_dataset(ds, shapes_dir)

    monkeypatch.setattr(pipeline.validate, "validate_dataset", _spy)
    pipeline.run(FETCHED, tmp_path / "out", include_all_corporations=True)

    assert seen_at_call_time == [True], (
        "validate_datasetが呼ばれた時点でhoujin-bangou-allの出典トリプルが"
        "dsに入っていない(dsではなくcleanに後から足している疑いがある)"
    )


def test_run_with_the_flag_does_not_append_when_batch_validation_fails(
    seeded_lake, tmp_path, monkeypatch
):
    """バッチ検証(validate_stream)が不合格なら、kg.nqへ追記しないこと。

    **既定は止まる側**(enforce_release_gateの既存の哲学と同じ)。検証前に
    本体へ混ぜてしまうと、壊れたデータが出荷されてから気づくことになる。
    `validate_stream`をモンキーパッチして「不合格」を人為的に起こす
    (実データでこの経路が落ちる具体的な入力を作るのは難しい —
    houjinBangouのSHACL patternとCSVパース側の正規表現が同一で、
    dedupが重複由来のmaxCount違反も解消するため。ここでは
    ゲートの配線そのものを確認する)。
    """
    from jgkg import uris
    from jgkg import validate as validate_mod

    def _fake_validate_stream(nq_path, shapes_dir, quarantine_dir, batch_size=50_000):
        return [
            validate_mod.ValidationResult(
                graph_uri=uris.graph_uri("houjin-bangou-all", DAY),
                conforms=False,
                report_text="FAKE VIOLATION(テスト用)",
                batch_index=0,
                violation_count=1,
                report_path=str(quarantine_dir / "fake.report.txt"),
            )
        ]

    monkeypatch.setattr(pipeline.validate, "validate_stream", _fake_validate_stream)

    out = tmp_path / "out"
    report = pipeline.run(FETCHED, out, include_all_corporations=True)

    assert report.corporations_all_quarantined == 1
    all_graph_uri = uris.graph_uri("houjin-bangou-all", DAY)
    assert all_graph_uri not in report.graphs

    # O-10: 不合格時は中間ファイル(houjin-bangou-all.nq)を削除しないこと。
    # 事実上の隔離物として、入力全体を再現できる状態のまま残す
    assert (out / "houjin-bangou-all.nq").exists(), (
        "不合格なのに中間ファイルが削除されてしまっている"
    )

    kg_text = (out / "kg.nq").read_text(encoding="utf-8")
    assert f"<{all_graph_uri}>" not in kg_text, (
        "不合格のグラフがkg.nqに追記されてしまっている(検証前に本体へ混ぜている疑いがある)"
    )

    with pytest.raises(pipeline.QuarantineNotEmptyError, match="全法人"):
        pipeline.enforce_release_gate(report)
    pipeline.enforce_release_gate(report, allow_partial=True)  # 明示指定時だけ続行


# =============================================================================
# Task 10(Ruling B17): egov-law / rs-system の pipeline.run への結線
# =============================================================================

RS_YEAR = 2025
KOUSEIROUDOU_BANGOU = "6000012070001"  # 厚生労働省(実在。R45)
WOLFSTYLE_BANGOU = "3010001137944"     # 株式会社ウルフスタイル(実在RS支出先。R45)


def _zip_single_csv(text: str, member: str = "data.csv") -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, text)
    return buf.getvalue()


def _rs_row_for(group: str, values: dict) -> list[str]:
    from jgkg.transform import rs_columns

    spec = rs_columns.RS_FILES[group]
    row = [""] * len(spec.full_header)
    for name, value in values.items():
        row[spec.col[name]] = value
    return row


def _rs_csv_text(group: str, rows: list[list[str]]) -> str:
    import csv
    import io

    from jgkg.transform import rs_columns

    spec = rs_columns.RS_FILES[group]
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(spec.full_header)
    writer.writerows(rows)
    return buf.getvalue()


def _save_rs_snapshot(fetched_on, groups: dict[str, list[list[str]]]) -> None:
    from jgkg.connectors import rs_system

    for group, rows in groups.items():
        filename = rs_system.filename_for(group, RS_YEAR)
        content = _zip_single_csv(_rs_csv_text(group, rows))
        lake.save("rs-system", fetched_on, filename, content)


def _egov_law_jsonl(records: list[dict]) -> bytes:
    import json

    lines = [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records]
    return ("\n".join(lines) + "\n").encode("utf-8") if lines else b""


def _minimal_law_record(law_id: str, law_num: str, law_title: str = "テスト法令") -> dict:
    return {
        "law_info": {
            "law_id": law_id, "law_num": law_num, "law_num_type": "MinisterialOrdinance",
            "law_type": "MinisterialOrdinance", "promulgation_date": "2020-01-01",
        },
        "revision_info": None,
        "current_revision_info": {"law_title": law_title, "abbrev": None, "repeal_status": "None"},
    }


@pytest.fixture
def houjin_with_a_company():
    """厚生労働省(政府機関)と株式会社ウルフスタイル(民間)の2行だけの小さいスナップショット。

    rs-systemのministry解決・recipient解決の両方を、実在の値(R45)で
    exerciseするための最小構成(共有fixture`houjin_bangou_sample.csv`の
    唯一の民間法人はRSのセンチネル値と同じ番号を偶然持つため、ここでは
    専用のスナップショットを別に作る)。
    """
    content = (
        zenken_row(houjin_bangou=KOUSEIROUDOU_BANGOU, name="厚生労働省", kind="101")
        + zenken_row(houjin_bangou=WOLFSTYLE_BANGOU, name="株式会社ウルフスタイル", kind="301", seq="2")
    )
    lake.save("houjin-bangou", DAY, houjin_bangou.FILENAME, zipped(content))


def test_run_requires_all_corporations_flag_when_rs_system_is_included():
    """rs-systemを含むのにinclude_all_corporations=Falseなら、ファイルへ触れる前に

    即座にエラーになること(裁定B17懸念2/B18)。
    """
    with pytest.raises(ValueError, match="include_all_corporations"):
        pipeline.run({"houjin-bangou": DAY, "rs-system": DAY}, Path("unused"))


def test_run_wires_egov_law_into_a_named_graph_with_resolved_jurisdiction(
    houjin_with_a_company, tmp_path
):
    from jgkg import uris
    from jgkg.connectors import egov_law

    lake.save(
        "egov-law", DAY, egov_law.FILENAME,
        _egov_law_jsonl([_minimal_law_record("323M60000100010", "令和三年厚生労働省令第一号")]),
    )
    report = pipeline.run({"houjin-bangou": DAY, "egov-law": DAY}, tmp_path / "out")

    assert uris.graph_uri("egov-law", DAY) in report.graphs
    assert report.law_records == 1
    assert report.law_jurisdiction_resolved == 1
    assert report.law_jurisdiction_unresolved == 0
    assert report.law_jurisdiction_extraction_failed == 0
    # 最終レビュー要修正5: 全解決でも4キー全部が(0埋めで)出ること
    assert report.law_jurisdiction_unresolved_by_reason == {
        "OLD_MINISTRY": 0, "OBSOLETE_ORGANIZATION": 0, "NO_CANDIDATE": 0, "AMBIGUOUS": 0,
    }
    assert report.sources["egov-law"] == DAY.isoformat()


def test_run_wires_egov_law_counts_unresolved_and_extraction_failed(
    houjin_with_a_company, tmp_path
):
    """未解決(NO_CANDIDATE)と抽出失敗(EXTRACTION_FAILED)がそれぞれ

    別カウンタに載ること(結線タスクが行うと申し送られていた計数)。
    """
    lake.save(
        "egov-law", DAY, egov_law.FILENAME,
        _egov_law_jsonl([
            # 参照表に無い名称(NO_CANDIDATE)
            _minimal_law_record("999RS0000000099", "ダミー機関規則第一号"),
            # 府省令の形をしているのに1文字の区分(「政」)= 経路1対象外(None)。
            # これはjurisdictionsにもEXTRACTION_FAILEDにも数えない対象外行
            _minimal_law_record("999RS0000000098", "令和三年政令第一号"),
        ]),
    )
    report = pipeline.run({"houjin-bangou": DAY, "egov-law": DAY}, tmp_path / "out")

    assert report.law_records == 2
    assert report.law_jurisdiction_resolved == 0
    assert report.law_jurisdiction_unresolved == 1  # ダミー機関 -> NO_CANDIDATE
    assert report.law_jurisdiction_extraction_failed == 0
    # 最終レビュー要修正5: NO_CANDIDATE1件が理由別の欄にも載ること
    assert report.law_jurisdiction_unresolved_by_reason == {
        "OLD_MINISTRY": 0, "OBSOLETE_ORGANIZATION": 0, "NO_CANDIDATE": 1, "AMBIGUOUS": 0,
    }


def test_run_wires_egov_law_tallies_unresolved_by_reason_separately(
    houjin_with_a_company, tmp_path
):
    """理由が違う複数の未解決が、それぞれ正しいキーに数えられること

    (最終レビュー要修正5)。

    何があれば落ちるか: 理由別の内訳が実際には`reason`で分岐せず
    (例: 常に同じキーに加算する、または`law_jurisdiction_unresolved`の
    総数をどこか1つのキーに丸めるような実装に退化すると)、このテストの
    ようにOLD_MINISTRYとNO_CANDIDATEが両方1件ずつ発生する入力で、
    どちらかが0のまま(または合計2が1つのキーに載る)になって落ちる。
    """
    lake.save(
        "egov-law", DAY, egov_law.FILENAME,
        _egov_law_jsonl([
            # 大蔵省はdata/reference/old-ministries.csvに実在する旧省庁名
            # (OLD_MINISTRY)
            _minimal_law_record("999RS0000000097", "昭和二十六年大蔵省令第百号"),
            # 参照表(houjin_with_a_companyには厚生労働省しか無い)に無い名称
            # (NO_CANDIDATE)
            _minimal_law_record("999RS0000000099", "ダミー機関規則第一号"),
        ]),
    )
    report = pipeline.run({"houjin-bangou": DAY, "egov-law": DAY}, tmp_path / "out")

    assert report.law_jurisdiction_resolved == 0
    assert report.law_jurisdiction_unresolved == 2
    assert report.law_jurisdiction_unresolved_by_reason == {
        "OLD_MINISTRY": 1, "OBSOLETE_ORGANIZATION": 0, "NO_CANDIDATE": 1, "AMBIGUOUS": 0,
    }


def test_run_wires_rs_system_and_reports_budget_and_ratio_observation(
    houjin_with_a_company, tmp_path
):
    """rs-systemの結線: グラフが出現し、BuildStats(束ね・センチネル・解決/未解決)

    がPipelineReportに載り、B24(6)の比の分布が観測として計算されること。
    """
    from jgkg import uris

    _save_rs_snapshot(DAY, {
        "project_summary": [
            _rs_row_for("project_summary", {
                "project_id": "1", "fiscal_year": "2025", "project_name": "テスト事業1",
                "ministry_name": "厚生労働省",
            }),
            _rs_row_for("project_summary", {
                "project_id": "2", "fiscal_year": "2025", "project_name": "テスト事業2",
                "ministry_name": "厚生労働省",
            }),
            # project 3: 前年度執行額はあるが支出先の記録が1件も無い(合計0)。
            # advisor2回目レビュー指摘: task-9-report.mdの「Σ[23]==0」枠
            # (「その他」と別枠)をpipeline.pyでも別枠にできているかの確認
            _rs_row_for("project_summary", {
                "project_id": "3", "fiscal_year": "2025", "project_name": "テスト事業3",
                "ministry_name": "厚生労働省",
            }),
        ],
        "budget_summary": [
            # project 1: 当年度100・前年度執行額100(=分母100。比を計算できる)
            _rs_row_for("budget_summary", {
                "project_id": "1", "budget_fiscal_year": "2025",
                "budget_amount": "100", "executed_amount": "0",
            }),
            _rs_row_for("budget_summary", {
                "project_id": "1", "budget_fiscal_year": "2024",
                "budget_amount": "90", "executed_amount": "100",
            }),
            # project 2: 前年度の行が無い(分母欠損。budget_ratio_no_denominatorに数える)
            _rs_row_for("budget_summary", {
                "project_id": "2", "budget_fiscal_year": "2025",
                "budget_amount": "50", "executed_amount": "0",
            }),
            # project 3: 前年度執行額50(分母50>0)。当年度の行は無くてもよい
            # (_prior_year_executed_amountはproject自身のfiscal_yearから
            # 前年度を逆算して直接引くだけで、当年度行の有無を問わない)
            _rs_row_for("budget_summary", {
                "project_id": "3", "budget_fiscal_year": "2024",
                "budget_amount": "40", "executed_amount": "50",
            }),
        ],
        "policy_measure_laws_and_regulations": [],
        "payee_payment_information": [
            # project 1: 実在の支出先へ200円(=分母100の2倍。比2.0)
            _rs_row_for("payee_payment_information", {
                "project_id": "1", "recipient_name": "株式会社ウルフスタイル",
                "recipient_houjin_bangou": WOLFSTYLE_BANGOU, "expenditure_amount": "200",
                "recipient_other_flag": "FALSE",
            }),
            # project 2: センチネル(法人でない支払先。B18)
            _rs_row_for("payee_payment_information", {
                "project_id": "2", "recipient_name": "個人Ａ",
                "recipient_houjin_bangou": "9999999999999", "expenditure_amount": "10",
                "recipient_other_flag": "FALSE",
            }),
            # project 3: 支出先の記録が1件も無い(意図的。合計=0を作る)
        ],
    })

    report = pipeline.run(
        {"houjin-bangou": DAY, "rs-system": DAY}, tmp_path / "out",
        include_all_corporations=True,
    )

    assert uris.graph_uri("rs-system", DAY) in report.graphs
    assert report.reference_violations == [], report.reference_violations
    assert report.budget_projects == 3
    assert report.budget_expenditures == 2
    assert report.budget_recipients_resolved_by_houjin_bangou == 1
    assert report.budget_recipients_sentinel == 1
    # Ruling B27: このfixtureに実在しない法人番号は無いので0(Noneではない
    # ——rs-systemの解決処理は実際に走ったので「未実行」のNoneにはならない)
    assert report.budget_recipients_nonexistent_houjin_bangou == 0
    assert report.budget_ministries_resolved == 3
    # B24(6): project 1はΣ(200)/前年度執行額(100)=2.0、project 2は分母欠損、
    # project 3は分母50>0だが合計0(「その他」と別枠であること。advisor指摘)
    assert report.budget_ratio_exact_2_0 == 1
    assert report.budget_ratio_no_denominator == 1
    assert report.budget_ratio_total_zero == 1
    assert report.budget_ratio_exact_1_0 == 0
    assert report.budget_ratio_other == 0


def test_run_reports_law_and_budget_fields_as_none_when_the_source_is_not_included(
    seeded_lake, tmp_path,
):
    """egov-law/rs-systemを含まないリリースでは、それらに関するフィールドが

    `None`(=未実行)であること(task-10-review.md要修正2)。`0`だと
    「実行して0件だった」と区別できず、Task 11の実測レポートが誤って0を
    公表する事故になりうる。このコードベース自身が`stream_emit.StreamStats.
    houjin_bangou_seen`/`freshness.StaleSource.days_since_last_fetch`で
    0とNoneを区別する作法を既に持っている。
    """
    report = pipeline.run(FETCHED, tmp_path / "out")  # houjin-bangouのみ

    assert report.law_records is None
    assert report.law_jurisdiction_resolved is None
    assert report.law_jurisdiction_unresolved is None
    assert report.law_jurisdiction_unresolved_by_reason is None
    assert report.law_jurisdiction_extraction_failed is None
    assert report.budget_projects is None
    assert report.budget_expenditures is None
    assert report.budget_expenditures_bundled is None
    assert report.budget_recipients_sentinel is None
    assert report.budget_recipients_nonexistent_houjin_bangou is None
    assert report.budget_recipients_resolved_by_houjin_bangou is None
    assert report.budget_recipients_resolved_by_name is None
    assert report.budget_recipients_unresolved is None
    assert report.budget_ministries_resolved is None
    assert report.budget_ministries_unresolved is None
    assert report.budget_basis_law_resolved is None
    assert report.budget_basis_law_unresolved is None
    assert report.budget_ratio_exact_1_0 is None
    assert report.budget_ratio_exact_2_0 is None
    assert report.budget_ratio_exact_3_0 is None
    assert report.budget_ratio_total_zero is None
    assert report.budget_ratio_other is None
    assert report.budget_ratio_no_denominator is None


# =============================================================================
# Task 10修正ラウンド1(Ruling B27。task-10-review.md裁定要1): 実在しない
# 法人番号を第5分類として弾き、参照整合ゲートの違反にしない
# =============================================================================


def test_run_reclassifies_a_nonexistent_recipient_houjin_bangou_and_drops_the_reference_violation(
    houjin_with_a_company, tmp_path,
):
    """支出先の法人番号が13桁の形はしているが、全法人グラフに実在しない場合、

    `budget:recipient`エッジを張らず`payeeLabel`を残す(B18のセンチネルと
    同じ作法。Ruling B27)。裁定要1の実測(全法人フラグONでも60件の参照整合
    違反が残る——法人番号公表サイトの全件データに行として存在しない値)への
    対応。

    何があれば落ちるか: `houjin_bangou_exists`をrs.build_projectsへ結線
    し忘れると、このテストの`report.reference_violations`が空にならない
    (存在しない番号への参照が型無しの違反としてゲートに残る)。
    """
    from rdflib import Dataset, URIRef

    from jgkg import uris
    from jgkg.config import get_settings

    nonexistent_bangou = "1234567890123"  # レビューの実例と同じ、明らかなダミー
    _save_rs_snapshot(DAY, {
        "project_summary": [
            _rs_row_for("project_summary", {
                "project_id": "1", "fiscal_year": "2025", "project_name": "テスト事業1",
                "ministry_name": "厚生労働省",
            }),
        ],
        "budget_summary": [],
        "policy_measure_laws_and_regulations": [],
        "payee_payment_information": [
            _rs_row_for("payee_payment_information", {
                "project_id": "1", "recipient_name": "実在しない架空商事株式会社",
                "recipient_houjin_bangou": nonexistent_bangou, "expenditure_amount": "300",
                "recipient_other_flag": "FALSE",
            }),
        ],
    })

    report = pipeline.run(
        {"houjin-bangou": DAY, "rs-system": DAY}, tmp_path / "out",
        include_all_corporations=True,
    )

    assert report.reference_violations == [], report.reference_violations
    assert report.budget_recipients_nonexistent_houjin_bangou == 1
    assert report.budget_recipients_resolved_by_houjin_bangou == 0

    ds = Dataset(default_union=True)
    ds.parse(tmp_path / "out" / "kg.nq", format="nquads")
    exp_uri = URIRef(uris.expenditure_uri("2025", "1", 0))
    recipient_pred = URIRef(f"{get_settings().base_uri}/def/budget#recipient")
    assert (exp_uri, recipient_pred, None) not in ds, (
        "実在しない法人番号なのにbudget:recipientエッジが張られている"
    )
    payee_label_pred = URIRef(f"{get_settings().base_uri}/def/budget#payeeLabel")
    assert {str(o) for o in ds.objects(exp_uri, payee_label_pred)} == {
        "実在しない架空商事株式会社"
    }


# =============================================================================
# Ruling B30(Task 11修正ラウンド): 支出先として登場する法人番号に限る
# corporations_scope="payees"。実測: 全法人35,584,368quads/13.8GiBに対し、
# 支出先限定は817,982quads/TDB2実サイズ429MiB(§6.3の8GiB判定への対応。
# 修正ラウンド2で実測値に訂正——旧「704,359quads/232MiB」は法人グラフを
# 除外しただけの事前見積りで、実装後の実測ではなかった)
# =============================================================================


def _rs_snapshot_with_one_recipient(fiscal_year: str = "2025") -> None:
    _save_rs_snapshot(DAY, {
        "project_summary": [
            _rs_row_for("project_summary", {
                "project_id": "1", "fiscal_year": fiscal_year, "project_name": "テスト事業1",
                "ministry_name": "厚生労働省",
            }),
        ],
        "budget_summary": [],
        "policy_measure_laws_and_regulations": [],
        "payee_payment_information": [
            _rs_row_for("payee_payment_information", {
                "project_id": "1", "recipient_name": "株式会社ウルフスタイル",
                "recipient_houjin_bangou": WOLFSTYLE_BANGOU, "expenditure_amount": "500",
                "recipient_other_flag": "FALSE",
            }),
        ],
    })


def test_run_payees_scope_requires_include_all_corporations():
    """corporations_scope='payees' は include_all_corporations=True が必須(Ruling B30)。

    法人グラフ自体を作らないなら範囲を選ぶ意味が無い——タイプミスで絞り込みだけが
    指定され、法人グラフが一切無いリリースが黙って成立することを避ける。
    """
    with pytest.raises(ValueError, match="include_all_corporations"):
        pipeline.run(
            {"houjin-bangou": DAY}, Path("unused"),
            include_all_corporations=False, corporations_scope="payees",
        )


def test_run_payees_scope_requires_rs_system():
    """corporations_scope='payees' は rs-system をこのリリースに含むことが必須(Ruling B30)。

    絞り込む対象(支出先として登場する法人番号)そのものがrs-systemのデータから決まる。
    """
    with pytest.raises(ValueError, match="rs-system"):
        pipeline.run(
            {"houjin-bangou": DAY}, Path("unused"),
            include_all_corporations=True, corporations_scope="payees",
        )


def test_run_payees_scope_writes_a_distinctly_named_graph_with_only_recipient_corporations(
    houjin_with_a_company, tmp_path,
):
    """payeesスコープは houjin-bangou-payees という別名グラフに、支出先(実際に

    budget:recipientとして参照される法人)だけを書くこと(Ruling B30)。

    **法人マスタに存在するが支出先ではない法人(厚生労働省。ministry-codes
    経由でBudgetProjectRecordが参照する別の資源)は入らない** —
    houjin-bangou-payeesグラフはあくまで`budget:recipient`の参照先を
    埋めるためのグラフであり、府省の実体はministry-codesグラフが別に持つ。
    """
    from rdflib import RDF, Dataset, URIRef

    from jgkg import uris
    from jgkg.config import get_settings

    _rs_snapshot_with_one_recipient()

    report = pipeline.run(
        {"houjin-bangou": DAY, "rs-system": DAY}, tmp_path / "out",
        include_all_corporations=True, corporations_scope="payees",
    )

    assert report.corporations_scope == "payees"
    payees_uri = uris.graph_uri("houjin-bangou-payees", DAY)
    all_uri = uris.graph_uri("houjin-bangou-all", DAY)
    assert payees_uri in report.graphs, "houjin-bangou-payeesグラフが出現していない"
    assert all_uri not in report.graphs, (
        "houjin-bangou-allという「全法人」グラフ名が出現している"
        "(payeesスコープなのに全法人と誤読される名前になっている)"
    )
    # fix-brief: フィルタ対象は実データでは18,941件相当(修正ラウンド2で
    # 判明。実在する支出先法人の数——「18,994」はセンチネルの扱いを欠いた
    # 古い数値。docs/measurements-phase1.md「恒等式」節参照)のごく少数に
    # なるはず。このfixtureでは支出先1件のみなので、法人グラフに書き出す
    # のはその1件だけ
    assert report.corporations_all == 1
    assert report.reference_violations == [], report.reference_violations

    ds = Dataset(default_union=True)
    ds.parse(tmp_path / "out" / "kg.nq", format="nquads")
    payees_graph = ds.graph(URIRef(payees_uri))
    org_class = URIRef(f"{get_settings().base_uri}/def/org#Organization")
    org_uris_in_payees_graph = {str(s) for s in payees_graph.subjects(RDF.type, org_class)}
    assert org_uris_in_payees_graph == {uris.org_uri(WOLFSTYLE_BANGOU)}, (
        "支出先(株式会社ウルフスタイル)以外の法人、または支出先以外の法人が"
        "houjin-bangou-payeesグラフに入っている"
    )
    assert uris.org_uri(KOUSEIROUDOU_BANGOU) not in {
        str(s) for s in payees_graph.subjects(None, None)
    }, "支出先ではない厚生労働省がhoujin-bangou-payeesグラフに入っている"


def test_run_payees_scope_still_resolves_a_real_recipient_by_houjin_bangou(
    houjin_with_a_company, tmp_path,
):
    """支出先限定でも、実在する支出先の解決(B27の実在確認を含む)は全法人

    モードと同じ結果になること(フィルタは「どこまで法人グラフに書くか」
    だけを変え、rs-system側の解決結果を変えてはならない)。
    """
    _rs_snapshot_with_one_recipient()

    report = pipeline.run(
        {"houjin-bangou": DAY, "rs-system": DAY}, tmp_path / "out",
        include_all_corporations=True, corporations_scope="payees",
    )

    assert report.budget_recipients_resolved_by_houjin_bangou == 1
    assert report.budget_recipients_nonexistent_houjin_bangou == 0
    assert report.budget_recipients_sentinel == 0


def test_run_payees_scope_still_reclassifies_a_nonexistent_recipient(
    houjin_with_a_company, tmp_path,
):
    """payeesスコープでもRuling B27(実在しない法人番号の第5分類)は変わらないこと。

    **何があれば落ちるか**: フィルタ導入がB27のhoujin_bangou_existsの結線を
    壊すと(payeesスコープ下ではstream_stats.houjin_bangou_seenが縮小
    されるため、テストの書き方を誤ると常にTrue/常にFalseになりうる)、
    このテストのnonexistent件数または参照整合違反が変わる。

    **実在の支出先(project 2。株式会社ウルフスタイル)も同居させる** — 実在の
    支出先が1件も無いと、フィルタ後の法人グラフが完全に空になり
    `validate.validate_stream`の「対象0件で合格に退化させない」ガード
    (B-2/F-4)が例外を投げてテストの主旨と無関係な失敗になる
    (実データでは支出先56,667件超に対しnonexistent60件なので、この
    空ファイル化は実運用では起きない——このfixture固有の作り方の問題)。
    """
    nonexistent_bangou = "1234567890123"
    _save_rs_snapshot(DAY, {
        "project_summary": [
            _rs_row_for("project_summary", {
                "project_id": "1", "fiscal_year": "2025", "project_name": "テスト事業1",
                "ministry_name": "厚生労働省",
            }),
            _rs_row_for("project_summary", {
                "project_id": "2", "fiscal_year": "2025", "project_name": "テスト事業2",
                "ministry_name": "厚生労働省",
            }),
        ],
        "budget_summary": [],
        "policy_measure_laws_and_regulations": [],
        "payee_payment_information": [
            _rs_row_for("payee_payment_information", {
                "project_id": "1", "recipient_name": "実在しない架空商事株式会社",
                "recipient_houjin_bangou": nonexistent_bangou, "expenditure_amount": "300",
                "recipient_other_flag": "FALSE",
            }),
            _rs_row_for("payee_payment_information", {
                "project_id": "2", "recipient_name": "株式会社ウルフスタイル",
                "recipient_houjin_bangou": WOLFSTYLE_BANGOU, "expenditure_amount": "500",
                "recipient_other_flag": "FALSE",
            }),
        ],
    })

    report = pipeline.run(
        {"houjin-bangou": DAY, "rs-system": DAY}, tmp_path / "out",
        include_all_corporations=True, corporations_scope="payees",
    )

    assert report.reference_violations == [], report.reference_violations
    assert report.budget_recipients_nonexistent_houjin_bangou == 1
    assert report.budget_recipients_resolved_by_houjin_bangou == 1
    # 実在しない番号の分は法人グラフに書かれない。実在する支出先(ウルフスタイル)
    # の1件だけが書かれる
    assert report.corporations_all == 1


def test_run_payees_scope_carry_over_regenerates_the_payees_graph_but_carries_the_rest(
    houjin_with_a_company, tmp_path, monkeypatch,
):
    """corporations_scope='payees'とcarry-overを同時に使うと、houjin-bangou/

    rs-systemは(無変更なので)据え置きされるが、houjin-bangou-payeesは
    **常に再生成される**こと(Task 10のcarry-over機構とTask 11のB30の
    組み合わせは、Task 10のテスト群〔fixtureはcorporations_scopeを知らない
    時期に書かれた〕には無い)。

    根拠: houjin-bangou-payeesの内容はhoujin-bangou**と**rs-systemの両方に
    依存する(支出先フィルタはrs-systemの生データから決まる)。carry-overの
    差分検出はソース単位(houjin-bangou/egov-law/rs-system)でしか効かず、
    「rs-systemは変わっていないがフィルタ生成ロジック自体が変わった」場合を
    見落とす恐れがあるため、意図的に毎回再構築する(実装コメント参照)。

    実データ(2026-08-25→2026-08-26の2リリース。4ソース全て無変更)で
    この挙動を確認済み——houjin-bangou/egov-law/rs-systemの3グラフは
    `carried_over`に載り、houjin-bangou-payeesだけが載らず、
    `corporations_all`(18,941)は2回とも独立に計算された
    (`docs/measurements-phase1.md` §5)。このテストはfixtureでその
    判定を固定する回帰防止。

    **egov-lawも必ず含める**: `_GRAPH_DEPENDENCIES["rs-system"]`は
    `("houjin-bangou", "ministry-codes", "egov-law", "rs-system")`であり、
    このリリースの`fetched_on`にegov-lawが無いと
    `_carry_over_source_date`は「依存元ソースが実行対象に含まれていない
    →不変と確認できない」として保守的にrs-system自身の据え置きも諦める
    (実データのリリースA/Bは両方egov-lawを含んでいたため、この前提を
    最初のfixture〔houjin-bangou/rs-systemのみ〕では見落としていた——
    このテストを書く過程で見つけた)。

    何があれば落ちるか: 将来、法人グラフの再構築を「安易に」carry-over
    対象へ含める変更をすると、`payees_uri`が`carried_over`に入って
    このテストが落ちる。
    """
    import tarfile

    from jgkg import build, uris
    from jgkg.config import get_settings

    monkeypatch.setenv("JGKG_ARTIFACT_DIR", str(tmp_path / "artifact"))
    get_settings.cache_clear()

    _rs_snapshot_with_one_recipient()
    lake.save(
        "egov-law", DAY, egov_law.FILENAME,
        _egov_law_jsonl([_minimal_law_record("323M60000100010", "令和三年厚生労働省令第一号")]),
    )
    fetched = {"houjin-bangou": DAY, "egov-law": DAY, "rs-system": DAY}
    out1 = Path(get_settings().artifact_dir) / DAY.isoformat()
    r1 = pipeline.run(
        fetched, out1,
        include_all_corporations=True, corporations_scope="payees",
    )
    assert r1.corporations_all == 1

    (out1 / "tdb2").mkdir()
    (out1 / "tdb2" / "x").write_bytes(b"x")
    tarball = out1 / "tdb2.tar.gz"
    with tarfile.open(tarball, "w:gz") as tf:
        tf.add(out1 / "tdb2", arcname="tdb2")
    m = build.build_manifest(
        nquads=out1 / "kg.nq", tarball=tarball, jena_version="6.2.0",
        release=DAY.isoformat(),
        sources={k: v.isoformat() for k, v in fetched.items()},
        graphs=r1.graphs, tdb2_expanded_bytes=4,
    )
    build.write_manifest(m, out1 / "manifest.json")

    r2 = pipeline.run(
        fetched, tmp_path / "out2",
        include_all_corporations=True, corporations_scope="payees",
        previous_release=DAY.isoformat(),
    )

    assert uris.graph_uri("houjin-bangou", DAY) in r2.carried_over
    assert uris.graph_uri("egov-law", DAY) in r2.carried_over
    assert uris.graph_uri("rs-system", DAY) in r2.carried_over
    payees_uri = uris.graph_uri("houjin-bangou-payees", DAY)
    assert payees_uri not in r2.carried_over, (
        "houjin-bangou-payeesがcarry-over対象になっている"
        "(このグラフは常に再生成すべき。実データ2026-08-25→08-26で確認した挙動)"
    )
    assert r2.corporations_all == 1, "2回目もフィルタ集合が独立に再計算されているはず"


def test_run_all_scope_is_the_default_and_unaffected_by_the_payees_filter(
    houjin_with_a_company, tmp_path,
):
    """corporations_scopeを省略すると既定の"all"になり、フィルタが掛からず

    法人マスタの全件(このfixtureでは2件)が書かれること(Ruling B30:
    「既定にしない。全法人モードも残す」)。
    """
    from jgkg import uris

    _rs_snapshot_with_one_recipient()

    report = pipeline.run(
        {"houjin-bangou": DAY, "rs-system": DAY}, tmp_path / "out",
        include_all_corporations=True,
    )

    assert report.corporations_scope == "all"
    assert report.corporations_all == 2, "全法人モードなのに絞り込まれている"
    assert uris.graph_uri("houjin-bangou-all", DAY) in report.graphs


# =============================================================================
# Task 11 / B28: CLI(`python -m jgkg.pipeline`)。build.sh の引数解釈がシェルの
# 外(=テストできる場所)にあることを固定する
# =============================================================================


def test_cli_accepts_multiple_sources_and_writes_report(seeded_lake, tmp_path):
    """`--source` を複数受け、レポートを out-dir に書くこと。

    **これが B28 の本題。** 以前の build.sh は位置引数1つ(取得日)しか
    受けず、その日付を houjin-bangou の取得日として決め打ちしていたため、
    egov-law / rs-system を含むリリースを実行系から作れなかった。
    """
    out = tmp_path / "out"
    laws = Path("tests/fixtures/egov_laws_page1.json").read_text(encoding="utf-8")
    import json as _json
    lines = [
        _json.dumps(law, ensure_ascii=False, sort_keys=True)
        for law in _json.loads(laws)["laws"]
    ]
    lake.save(
        "egov-law", DAY, egov_law.FILENAME,
        ("\n".join(lines) + "\n").encode("utf-8"),
    )

    assert pipeline.main([
        "--source", f"houjin-bangou={DAY.isoformat()}",
        "--source", f"egov-law={DAY.isoformat()}",
        "--out-dir", str(out),
    ]) == 0

    report = _json.loads((out / pipeline.REPORT_NAME).read_text(encoding="utf-8"))
    # リリース名はout_dirのbasename(Ruling B31。取得日から決まらない)
    assert report["release"] == "out"
    assert set(report["sources"]) == {"houjin-bangou", "ministry-codes", "egov-law"}
    assert report["law_records"] == 3, "egov-lawが実際に結線されている"
    assert (out / "kg.nq").exists()


def test_cli_rejects_unknown_source_id(tmp_path):
    """未登録のソースIDを黙って無視しないこと。

    何があれば落ちるか: `--source houjin-banogu=...`(タイプミス)が
    「そのソースを含めないリリース」として静かに成功する実装に戻したとき。
    """
    with pytest.raises(SystemExit) as exc:
        pipeline.main([
            "--source", "houjin-banogu=2026-08-01", "--out-dir", str(tmp_path / "o"),
        ])
    assert exc.value.code == 2


def test_cli_rejects_malformed_source_and_missing_source(tmp_path):
    """`=` の無い --source と、--source が1つも無い呼び出しを弾くこと。"""
    with pytest.raises(SystemExit) as exc:
        pipeline.main(["--source", "houjin-bangou", "--out-dir", str(tmp_path / "o")])
    assert exc.value.code == 2

    with pytest.raises(SystemExit) as exc:
        pipeline.main(["--out-dir", str(tmp_path / "o")])
    assert exc.value.code == 2


def test_cli_rejects_same_source_with_two_dates(tmp_path):
    """同じソースに違う日付が2回渡されたら弾くこと(後勝ちで黙って通さない)。"""
    with pytest.raises(SystemExit) as exc:
        pipeline.main([
            "--source", "houjin-bangou=2026-08-01",
            "--source", "houjin-bangou=2026-08-02",
            "--out-dir", str(tmp_path / "o"),
        ])
    assert exc.value.code == 2


def test_cli_rejects_a_date_for_a_committed_reference_table_source(tmp_path):
    """`--source ministry-codes=<日付>` を黙って受理しないこと(block-A-review 項目2)。

    **何が壊れるか(修正前)**: `_parse_source`はソースIDが`sources.SOURCES`に
    実在するかしか検査せず、`local_path`を持つ源(コミット済み参照表。現状
    ministry-codesのみ)にも任意の日付を素通りさせていた。この日付は
    `fetched_on["ministry-codes"]`としてグラフURIと
    `prov:generatedAtTime`(rdf/provenance.py)に流れ込むが、`core:recordedOn`
    は別途`sources.get_source("ministry-codes").recorded_on`から取得される
    ため、両者が食い違う——1つのグラフが自分自身について2つの矛盾する日付を
    主張する状態を作れた。A-3以降`prov:generatedAtTime`はCQ8のカットオフの
    入力にもなっているため、誤った日付が黙ってCQ8の答えを狂わせる経路になる。

    修正: `fetch.py:148-157`と同じ判定条件(`source.local_path is not None`。
    "ministry-codes"という文字列比較にしない)で`_parse_source`が拒否する。
    """
    with pytest.raises(SystemExit) as exc:
        pipeline.main([
            "--source", "ministry-codes=2020-01-01", "--out-dir", str(tmp_path / "o"),
        ])
    assert exc.value.code == 2


def test_cli_writes_report_before_the_gate_raises(lake_with_duplicate_label, tmp_path):
    """隔離で落ちる実行でも、例外の**前に**レポートが書かれていること。

    何があれば落ちるか: レポート書き出しを enforce_release_gate の後ろに
    移したとき(何が落ちたのかを人が読めなくなる。旧 build.sh が
    コメントで守っていた順序をCLIの中に移したので、ここで固定する)。
    """
    out = tmp_path / "out"
    with pytest.raises(pipeline.QuarantineNotEmptyError):
        pipeline.main([
            "--source", f"houjin-bangou={DAY.isoformat()}", "--out-dir", str(out),
        ])
    import json as _json
    report = _json.loads((out / pipeline.REPORT_NAME).read_text(encoding="utf-8"))
    assert report["graphs_quarantined"] >= 1


def test_cli_corporations_scope_defaults_to_all(houjin_with_a_company, tmp_path):
    """`--corporations-scope` を省略すると既定の"all"がrun()へそのまま渡ること

    (Ruling B30: 既定にしない。全法人モードを捨てない)。
    """
    import json as _json

    _rs_snapshot_with_one_recipient()
    out = tmp_path / "out"

    assert pipeline.main([
        "--source", f"houjin-bangou={DAY.isoformat()}",
        "--source", f"rs-system={DAY.isoformat()}",
        "--out-dir", str(out),
        "--include-all-corporations",
    ]) == 0

    report = _json.loads((out / pipeline.REPORT_NAME).read_text(encoding="utf-8"))
    assert report["corporations_scope"] == "all"
    assert report["corporations_all"] == 2


def test_cli_passes_corporations_scope_payees_through_to_run(houjin_with_a_company, tmp_path):
    """`--corporations-scope payees` がCLIからrun()まで正しく伝わること(Ruling B30)。"""
    import json as _json

    _rs_snapshot_with_one_recipient()
    out = tmp_path / "out"

    assert pipeline.main([
        "--source", f"houjin-bangou={DAY.isoformat()}",
        "--source", f"rs-system={DAY.isoformat()}",
        "--out-dir", str(out),
        "--include-all-corporations",
        "--corporations-scope", "payees",
    ]) == 0

    report = _json.loads((out / pipeline.REPORT_NAME).read_text(encoding="utf-8"))
    assert report["corporations_scope"] == "payees"
    assert report["corporations_all"] == 1


def test_cli_rejects_an_unknown_corporations_scope_value(tmp_path):
    """`--corporations-scope` に "all"/"payees" 以外を渡すとargparseが拒否すること

    (未登録ソースIDを黙って受けないtest_cli_rejects_unknown_source_idと同じ
    「タイプミスを黙って通さない」作法)。
    """
    with pytest.raises(SystemExit):
        pipeline.main([
            "--source", f"houjin-bangou={DAY.isoformat()}",
            "--out-dir", str(tmp_path / "out"),
            "--corporations-scope", "everything",
        ])
