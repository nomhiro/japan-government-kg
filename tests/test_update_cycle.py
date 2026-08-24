"""Task 10: 更新の一巡(差分検出・置換・アトミック切替・鮮度)。設計書§1.2(C)の器。

2世代の固定スナップショットで訂正・削除・据え置きの3態を検証する(§10)。
アトミック切替(serve.sh)はDocker実機で別途確認する(task-10-report.md)。
"""
import datetime
import tarfile
from pathlib import Path

import pytest
from rdflib import Dataset, URIRef
from rdflib.namespace import SKOS
from zenken_rows import zenken_row, zipped

from jgkg import build, lake, pipeline, uris
from jgkg.config import get_settings
from jgkg.connectors import houjin_bangou

DAY1 = datetime.date(2026, 7, 1)
DAY2 = datetime.date(2026, 8, 1)

NUM_A = "6000012070001"
NUM_B = "2000012020001"

# 世代1と世代2で完全に同一のバイト列(「据え置き」判定の対象)
UNCHANGED_HOUJIN_BANGOU_BYTES = zipped(zenken_row(houjin_bangou=NUM_A, name="厚生労働省"))


@pytest.fixture(autouse=True)
def tmp_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "https://jgkg.norr-tech.com")
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    monkeypatch.setenv("JGKG_ARTIFACT_DIR", str(tmp_path / "artifact"))
    monkeypatch.setenv("JGKG_QUARANTINE_DIR", str(tmp_path / "quarantine"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _artifact_dir(release: datetime.date) -> Path:
    """build.sh と同じ規約(`data/artifact/{release}`)。previous_release は

    このディレクトリの kg.nq を指す(pipeline.run のInterfaces)。
    """
    return Path(get_settings().artifact_dir) / release.isoformat()


def _load(path: Path) -> Dataset:
    ds = Dataset(default_union=True)
    ds.parse(path, format="nquads")
    return ds


def _write_fake_manifest(out_dir: Path, release: str) -> None:
    """build.sh が作るのと同じ形の最小限のtarball+manifestを書く(検証済み実行の代用)。

    `test_failed_validation_keeps_previous_release` が「前リリースの成果物が
    実在する」という前提を作るためだけに使う(carry-over機構そのものは
    kg.nqしか読まないので、他のテストはこれを呼ばない)。
    """
    (out_dir / "tdb2").mkdir(parents=True, exist_ok=True)
    (out_dir / "tdb2" / "nodes.dat").write_bytes(b"fake")
    tarball = out_dir / "tdb2.tar.gz"
    with tarfile.open(tarball, "w:gz") as tf:
        tf.add(out_dir / "tdb2", arcname="tdb2")
    m = build.build_manifest(
        nquads=out_dir / "kg.nq",
        tarball=tarball,
        jena_version="6.2.0",
        release=release,
        sources={"houjin-bangou": release},
        graphs=[],
    )
    build.write_manifest(m, out_dir / "manifest.json")


# =============================================================================
# Step 1: 訂正・削除が置換として反映されること(carry-overを使わない基本形)
# =============================================================================


def _two_generations_with_correction_and_deletion() -> None:
    lake.save(
        "houjin-bangou", DAY1, houjin_bangou.FILENAME,
        zipped(
            zenken_row(houjin_bangou=NUM_A, name="X")
            + zenken_row(houjin_bangou=NUM_B, name="B", seq="2")
        ),
    )
    lake.save(
        "houjin-bangou", DAY2, houjin_bangou.FILENAME,
        zipped(zenken_row(houjin_bangou=NUM_A, name="Y")),
    )


def test_replacement_reflects_correction_and_deletion():
    """訂正(名称変更)が新値だけになり、削除(行消滅)が消えること。

    世代1: A(名称X)とB / 世代2: A(名称Y。訂正)のみ(Bは削除)。

    何があれば落ちるか: 置換でなく追記に退化したら旧値が残って落ちる。
    """
    _two_generations_with_correction_and_deletion()
    pipeline.run({"houjin-bangou": DAY1}, _artifact_dir(DAY1))
    pipeline.run({"houjin-bangou": DAY2}, _artifact_dir(DAY2))

    ds = _load(_artifact_dir(DAY2) / "kg.nq")
    uri_a = URIRef(uris.org_uri(NUM_A))
    uri_b = URIRef(uris.org_uri(NUM_B))
    labels_of_a = {str(o) for o in ds.objects(uri_a, SKOS.prefLabel)}
    assert labels_of_a == {"Y"}, "訂正の旧値が残っている(追記に退化)"
    assert (uri_b, None, None) not in ds, "削除が反映されていない"


def test_replacement_reflects_correction_and_deletion_even_with_previous_release_given():
    """`previous_release`を渡しても、houjin-bangou自体が変化していれば

    carry-overは働かず、通常どおり置換されること(据え置き判定が
    「変わっていないのに変わったと誤認する」方向の誤りを防ぐ)。
    """
    _two_generations_with_correction_and_deletion()
    pipeline.run({"houjin-bangou": DAY1}, _artifact_dir(DAY1))
    r2 = pipeline.run(
        {"houjin-bangou": DAY2}, _artifact_dir(DAY2), previous_release=DAY1
    )

    assert r2.carried_over == [], "内容が変わったソースが据え置きされてしまった"
    ds = _load(_artifact_dir(DAY2) / "kg.nq")
    uri_a = URIRef(uris.org_uri(NUM_A))
    uri_b = URIRef(uris.org_uri(NUM_B))
    assert {str(o) for o in ds.objects(uri_a, SKOS.prefLabel)} == {"Y"}
    assert (uri_b, None, None) not in ds


# =============================================================================
# Step 2: 差分検出(sha256一致)によるcarry-over
# =============================================================================


def test_unchanged_source_is_carried_over():
    """sha256が同じソースは再生成されず、carried_over に前リリースの

    グラフURIが載ること。

    何があれば落ちるか: 差分検出を外すと carried_over が空になり落ちる。
    """
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    pipeline.run({"houjin-bangou": DAY1}, _artifact_dir(DAY1))

    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    r2 = pipeline.run(
        {"houjin-bangou": DAY2}, _artifact_dir(DAY2), previous_release=DAY1
    )

    assert uris.graph_uri("houjin-bangou", DAY1) in r2.carried_over


def test_carried_over_graph_keeps_its_original_content_and_date():
    """据え置きグラフの内容が実際に引き継がれ(空のグラフURIだけを名乗る、

    という誤りにならない)、日付がDAY1のままであること(DAY2に再スタンプ
    しない)。
    """
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    pipeline.run({"houjin-bangou": DAY1}, _artifact_dir(DAY1))

    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    r2 = pipeline.run(
        {"houjin-bangou": DAY2}, _artifact_dir(DAY2), previous_release=DAY1
    )

    ds = _load(_artifact_dir(DAY2) / "kg.nq")
    carried_uri = URIRef(uris.graph_uri("houjin-bangou", DAY1))
    assert len(ds.graph(carried_uri)) > 0, "据え置きグラフの中身が空になっている"
    uri_a = URIRef(uris.org_uri(NUM_A))
    assert {str(o) for o in ds.objects(uri_a, SKOS.prefLabel)} == {"厚生労働省"}
    # DAY2の日付のhoujin-bangouグラフは作られない(据え置きは再スタンプしない)
    restamped_uri = URIRef(uris.graph_uri("houjin-bangou", DAY2))
    assert len(ds.graph(restamped_uri)) == 0, "据え置きなのにDAY2の日付で再生成されている"
    # report.sources にも旧日付(DAY1)が載る(「実際に入っているもの」原則)
    assert r2.sources["houjin-bangou"] == DAY1.isoformat()


def test_carry_over_is_not_used_when_previous_release_is_omitted():
    """`previous_release`を渡さない既定の呼び出しでは、carry-overを一切使わないこと

    (既存の全呼び出し元の振る舞いに影響しないための後方互換性)。
    """
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    pipeline.run({"houjin-bangou": DAY1}, _artifact_dir(DAY1))

    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    r2 = pipeline.run({"houjin-bangou": DAY2}, _artifact_dir(DAY2))

    assert r2.carried_over == []
    assert r2.sources["houjin-bangou"] == DAY2.isoformat()


def test_carry_over_raises_when_the_previous_release_artifact_is_missing():
    """`previous_release`が指す成果物(kg.nq)が実在しなければ、黙って据え置きを

    諦めるのではなく例外にすること(呼び出し側の「前リリースが存在する」
    という主張と矛盾するため)。
    """
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    # DAY1のリリースそのものは作らない(kg.nqが存在しない状態を模す)

    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    with pytest.raises(FileNotFoundError, match="前リリース"):
        pipeline.run(
            {"houjin-bangou": DAY2}, _artifact_dir(DAY2), previous_release=DAY1
        )


def test_carry_over_falls_back_to_regeneration_when_the_previous_graph_is_absent():
    """前リリースの成果物(kg.nq)は実在するが、該当グラフが無い

    (例: 隔離されていた)場合は、据え置きを諦めて通常どおり再生成すること
    (黙って空にしない。このタスクで踏みやすい欠陥の型2)。
    """
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    # DAY1のリリースは作るが、houjin-bangouのグラフを含まない空のkg.nqにする
    # (「前リリースは存在するが該当グラフが無い」を直接作る)
    out1 = _artifact_dir(DAY1)
    out1.mkdir(parents=True)
    (out1 / "kg.nq").write_text("", encoding="utf-8")

    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    r2 = pipeline.run(
        {"houjin-bangou": DAY2}, _artifact_dir(DAY2), previous_release=DAY1
    )

    assert r2.carried_over == [], "前リリースに該当グラフが無いのに据え置きした"
    assert r2.sources["houjin-bangou"] == DAY2.isoformat()
    ds = _load(_artifact_dir(DAY2) / "kg.nq")
    uri_a = URIRef(uris.org_uri(NUM_A))
    assert {str(o) for o in ds.objects(uri_a, SKOS.prefLabel)} == {"厚生労働省"}, (
        "再生成されたはずのグラフに内容が無い"
    )


def test_carry_over_ignores_unrelated_graphs_present_in_the_previous_kg_nq():
    """前リリースのkg.nqに、carry-over対象ではない別グラフ(全法人グラフ相当)

    が混在していても、(a) 本来の据え置き対象(houjin-bangou)は正しく機能し、
    (b) その無関係なグラフの内容は新リリースに復活しないこと。

    advisorレビュー指摘: 前リリースのkg.nqを丸ごとrdflibの`Dataset`にロード
    する実装だと、RS入りの前リリースに実際に含まれるhoujin-bangou-all
    (約3,500万行。`run()`の`include_all_corporations`処理がkg.nqの末尾に
    そのまま連結する)を読み込んでメモリが破綻する(R19/R21)。修正後は
    対象グラフだけを1パスの行フィルタで拾うため規模に強いが、**この規模を
    テストで再現するのは重すぎる**。代わりに、対象外のグラフが混在した
    小さいkg.nqで、carry-overの結線そのもの(a)と、無関係な内容が新
    リリースに残らないこと(b)を直接固定する。

    **何があれば落ちるか(壊し確認済み)**: (a)は、`run()`内の抽出呼び出し
    (`_extract_graphs_from_kg_nq`の呼び出し)を外すと落ちる(carry-overの
    結線が本当に効いているかを確認する)。(b)は現在の実装では`run()`側が
    グラフURIを指定した個別取得(`carried_graphs.get(exact_uri)`)しか
    しないため、`_extract_graphs_from_kg_nq`単体のフィルタを壊しても
    (a)(b)いずれも失敗しない(=多重の防御になっている。実際に3パターン
    壊して確認した)。それでも(b)は、将来`run()`側が`carried_graphs`を
    キー指定せず丸ごと使う書き方に変わった場合の回帰を検知する——導入前は
    どのテストも保証していなかった性質という点に変わりはない。
    """
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    out1 = _artifact_dir(DAY1)
    pipeline.run({"houjin-bangou": DAY1}, out1)

    # 前リリースのkg.nqに、carry-over対象外の別グラフ(全法人グラフ相当)を
    # 手動で追記する。run()が実際に行っている追記(houjin-bangou-all.nqを
    # kg.nqの末尾にそのまま連結する)を模す
    unrelated_graph = uris.graph_uri("houjin-bangou-all", DAY1)
    unrelated_org = uris.org_uri("9000000000001")
    with (out1 / "kg.nq").open("a", encoding="utf-8", newline="\n") as f:
        f.write(f'<{unrelated_org}> <{SKOS.prefLabel}> "無関係法人" <{unrelated_graph}> .\n')

    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    r2 = pipeline.run(
        {"houjin-bangou": DAY2}, _artifact_dir(DAY2), previous_release=DAY1
    )

    # (a) 本来の据え置き対象は無関係グラフの混在に関わらず正しく機能する
    assert uris.graph_uri("houjin-bangou", DAY1) in r2.carried_over
    ds = _load(_artifact_dir(DAY2) / "kg.nq")
    uri_a = URIRef(uris.org_uri(NUM_A))
    assert {str(o) for o in ds.objects(uri_a, SKOS.prefLabel)} == {"厚生労働省"}

    # (b) 無関係グラフの内容は新リリースに復活しない(carry-over対象の
    # 範囲を超えて何でも引き継ぐ実装になっていないことの確認)。
    # **グラフを指定せず主語で見る**(`ds.graph(URIRef(unrelated_graph))`
    # だけだと、無関係な内容が誤って別のグラフURI——例えばhoujin-bangou自身
    # の据え置きグラフ——に取り込まれて残るような壊れ方を見逃す)
    assert (URIRef(unrelated_org), None, None) not in ds, (
        "carry-over対象外のグラフの内容が(どのグラフかを問わず)新リリースに残っている"
    )
    assert len(ds.graph(URIRef(unrelated_graph))) == 0, (
        "carry-over対象外のグラフが新リリースに復活している"
    )


# =============================================================================
# 依存関係つきcarry-over(advisorレビュー指摘: 自ソースのsha256だけでは
# 不健全。他ソースへの依存を経由して変化が伝播することを固定する)
# =============================================================================


def test_carry_over_declines_for_egov_law_when_houjin_bangou_changed():
    """egov-lawグラフ自身のバイト列は不変でも、依存元(houjin-bangou)が

    変化していれば据え置きしないこと。egov-lawのjurisdiction解決は
    houjin-bangou由来のministriesに依存するため、houjin-bangouの変化が
    jurisdiction解決結果を変える可能性がある(自ソースのsha256だけを見る
    判定は不健全というadvisorレビュー指摘の再現)。
    """
    from jgkg.connectors import egov_law

    law_bytes = _egov_laws_jsonl()
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    lake.save("egov-law", DAY1, egov_law.FILENAME, law_bytes)
    pipeline.run({"houjin-bangou": DAY1, "egov-law": DAY1}, _artifact_dir(DAY1))

    # houjin-bangouは変化させる。egov-lawは同一バイト列のまま
    lake.save(
        "houjin-bangou", DAY2, houjin_bangou.FILENAME,
        zipped(zenken_row(houjin_bangou=NUM_A, name="変更後の名称")),
    )
    lake.save("egov-law", DAY2, egov_law.FILENAME, law_bytes)
    r2 = pipeline.run(
        {"houjin-bangou": DAY2, "egov-law": DAY2},
        _artifact_dir(DAY2),
        previous_release=DAY1,
    )

    assert uris.graph_uri("egov-law", DAY1) not in r2.carried_over, (
        "依存元(houjin-bangou)が変化したのにegov-lawが据え置きされた"
    )
    assert r2.sources["egov-law"] == DAY2.isoformat()


def _egov_laws_jsonl() -> bytes:
    import json

    law = {
        "law_info": {
            "law_id": "323M60000100010",
            "law_num": "昭和二十三年厚生省令第十号",
            "law_num_type": "MinisterialOrdinance",
            "law_type": "MinisterialOrdinance",
            "promulgation_date": "1948-01-01",
        },
        "revision_info": None,
        "current_revision_info": {
            "law_title": "テスト用の省令", "abbrev": None, "repeal_status": "None",
        },
    }
    return (json.dumps(law, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


# =============================================================================
# Step 3(検証ゲート): 検証に失敗したら成果物が作られず、前リリースが残ること(§6.4)
# =============================================================================


def run_and_gate(fetched_on, out_dir, **kwargs):
    """build.sh の要点(run→enforce_release_gate)だけを再現する薄いヘルパー。"""
    report = pipeline.run(fetched_on, out_dir, **kwargs)
    pipeline.enforce_release_gate(report)
    return report


def test_failed_validation_keeps_previous_release():
    """世代2が検証に落ちたら成果物が作られず、世代1が残ること(§6.4)。

    何があれば落ちるか: 隔離ゲートを exit 0 に緩めると落ちる(C2の再発検知)。
    """
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    out1 = _artifact_dir(DAY1)
    pipeline.run({"houjin-bangou": DAY1}, out1)
    _write_fake_manifest(out1, DAY1.isoformat())

    lake.save(
        "houjin-bangou", DAY2, houjin_bangou.FILENAME,
        zipped(zenken_row(name="重複1") + zenken_row(name="重複2", seq="2")),
    )
    with pytest.raises(pipeline.QuarantineNotEmptyError):
        run_and_gate({"houjin-bangou": DAY2}, _artifact_dir(DAY2))

    assert (out1 / "manifest.json").exists(), "前リリースの成果物が失われている"
