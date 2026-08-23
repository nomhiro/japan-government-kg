"""出典グラフの sha256・記録日のテスト(計画B Task 1)。

Phase 0 実装記録の型4「消費者のいない記録」への対処として、ここで足す
sourceSha256 は**書きっぱなしにしない**。レイクの実メタデータ
(houjin-bangou)・sources.py の登録値(ministry-codes)という「実際の一次資料」
と照合するテストを、形式検査(64桁16進)とは別に持つ。
"""
import datetime
from pathlib import Path

import pytest
from rdflib import Dataset, Namespace, URIRef
from zenken_rows import zipped

from jgkg import lake, pipeline
from jgkg.connectors import houjin_bangou
from jgkg.sources import get_source

DAY = datetime.date(2026, 8, 1)
# 取得して来るソースの日付だけを渡す。参照表(ministry-codes)の日付は
# sources.py の recorded_on から取られる(test_pipeline.py と同じ規約)
FETCHED = {"houjin-bangou": DAY}
BASE = "https://jgkg.norr-tech.com"
PROV_GRAPH_URI = f"{BASE}/graph/provenance"
CORE = Namespace(f"{BASE}/def/core#")


@pytest.fixture(autouse=True)
def tmp_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", BASE)
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    monkeypatch.setenv("JGKG_QUARANTINE_DIR", str(tmp_path / "quarantine"))
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def kg_dataset(tmp_path):
    """実際に pipeline.run を通した後のKG全体。

    emit.py 単体ではなく pipeline レベルにするのは、houjin-bangou の
    sha256 がレイクの Snapshot から、ministry-codes の sha256/recorded_on が
    sources.py から**実際に配線されている**ことまで確認するため
    (配線漏れは emit.py 単体のテストでは検出できない)。
    """
    content = Path("tests/fixtures/houjin_bangou_sample.csv").read_text(encoding="utf-8")
    lake.save("houjin-bangou", DAY, houjin_bangou.FILENAME, zipped(content))
    out = tmp_path / "out"
    pipeline.run(FETCHED, out)

    ds = Dataset(default_union=True)
    ds.parse(out / "kg.nq", format="nquads")
    return ds


def test_provenance_carries_sha256_and_recorded_on(kg_dataset):
    """出典グラフから一次資料のsha256に遡れること。

    何があれば落ちるか: emit 側が sha256 を書かなくなったら落ちる。
    """
    g = kg_dataset.get_graph(URIRef(PROV_GRAPH_URI))
    shas = [str(o) for o in g.objects(None, CORE.sourceSha256)]
    assert shas, "sourceSha256 が1件も無い"
    assert all(len(x) == 64 and set(x) <= set("0123456789abcdef") for x in shas)


def test_houjin_bangou_sha256_matches_the_lake_snapshot(kg_dataset):
    """houjin-bangou の sourceSha256 が、レイクの実メタデータと一致すること。

    形式検査(64桁16進)だけでは、emit側が乱数やダミー値を書いても合格してしまう
    (型2「空振りテスト」)。レイクに実際に保存された Snapshot.sha256 という
    「実際の一次資料」と照合して、初めて「遡れる」ことの証明になる。

    何があれば落ちるか: pipeline が Snapshot.sha256 以外の値(あるいは無関係な
    定数)を渡すようになったら落ちる。
    """
    snapshot = next(
        s for s in lake.list_snapshots("houjin-bangou") if s.fetched_on == DAY
    )
    graph_uri = URIRef(f"{BASE}/graph/houjin-bangou/{DAY.isoformat()}")

    g = kg_dataset.get_graph(URIRef(PROV_GRAPH_URI))
    sha = g.value(graph_uri, CORE.sourceSha256)
    assert sha is not None, "houjin-bangouのグラフに sourceSha256 が無い"
    assert str(sha) == snapshot.sha256, (
        f"emitしたsha256({sha})がレイクのSnapshot.sha256({snapshot.sha256})と一致しない"
    )


def test_ministry_codes_sha256_matches_the_registry(kg_dataset):
    """ministry-codes の sourceSha256 が、sources.py の登録値と一致すること。

    参照表はレイクにスナップショットが無いので、sources.py の記録が
    「どの版を使ったか」の唯一の証拠になる(test_reference_table_digest_matches_
    the_registry がファイル側の一致を、このテストがKG側への伝播を確認する)。
    """
    ministry = get_source("ministry-codes")
    graph_uri = URIRef(f"{BASE}/graph/ministry-codes/{ministry.recorded_on.isoformat()}")

    g = kg_dataset.get_graph(URIRef(PROV_GRAPH_URI))
    sha = g.value(graph_uri, CORE.sourceSha256)
    assert sha is not None, "ministry-codesのグラフに sourceSha256 が無い"
    assert str(sha) == ministry.sha256, (
        f"emitしたsha256({sha})が sources.py の登録値({ministry.sha256})と一致しない"
    )


def test_houjin_bangou_sha256_ignores_a_decoy_file_in_the_same_date_dir(tmp_path):
    """同じソース×日付のレイクディレクトリに無関係なファイルが増えても、

    `houjin_bangou.FILENAME` のスナップショットだけを見ること。
    `lake.list_snapshots()` は同じディレクトリ内の全 `.meta.json` を返すため、
    ファイル名で絞らないとソート順で先に来た方のsha256を黙って拾ってしまう
    (sha256の真正性というこのタスクの主旨そのものに関わる欠陥。ミニレビューで
    指摘された)。

    何があれば落ちるか: pipeline.py の houjin_snapshot 検索から
    `s.path.name == houjin_bangou.FILENAME` の条件を外したら落ちる
    (`"a-decoy-file.txt.meta.json"` は辞書順で `"zenken.zip.meta.json"` より
    前に来るため、`list_snapshots()` の並びで先に見つかる)。
    """
    content = Path("tests/fixtures/houjin_bangou_sample.csv").read_text(encoding="utf-8")
    lake.save("houjin-bangou", DAY, houjin_bangou.FILENAME, zipped(content))
    decoy = lake.save("houjin-bangou", DAY, "a-decoy-file.txt", b"not the real snapshot")

    real_snapshot = next(
        s
        for s in lake.list_snapshots("houjin-bangou")
        if s.fetched_on == DAY and s.path.name == houjin_bangou.FILENAME
    )
    assert decoy.sha256 != real_snapshot.sha256, "テストの前提(2つの値が違う)が崩れている"

    out = tmp_path / "out"
    pipeline.run(FETCHED, out)

    ds = Dataset(default_union=True)
    ds.parse(out / "kg.nq", format="nquads")
    g = ds.get_graph(URIRef(PROV_GRAPH_URI))
    graph_uri = URIRef(f"{BASE}/graph/houjin-bangou/{DAY.isoformat()}")
    sha = g.value(graph_uri, CORE.sourceSha256)
    assert str(sha) == real_snapshot.sha256, (
        f"decoyファイルのsha256({decoy.sha256})を誤って拾っている(emit={sha})"
    )


def test_provenance_graph_accepts_multiple_sha256_without_splitting_a_single_string():
    """複数件のsha256を受け、単一文字列は1文字ずつに分解しないこと(Task 7)。

    `str` は `Iterable[str]` の一種なので、`isinstance` で分岐しないと
    単一文字列呼び出しが1文字ごとにトリプルを書く、という静かな破損になる。
    RSは1つのグラフが5本の物理ファイルから作られるため、複数件を渡す経路が
    実在する(emit_budget)。
    """
    from jgkg.rdf.provenance import provenance_graph

    g_single = provenance_graph(
        f"{BASE}/graph/rs-system/2026-08-23", "rs-system", DAY, sha256="abc123"
    )
    shas_single = {str(o) for o in g_single.objects(None, CORE.sourceSha256)}
    assert shas_single == {"abc123"}, (
        f"単一文字列が1文字ずつに分解されている: {shas_single}"
    )

    g_multi = provenance_graph(
        f"{BASE}/graph/rs-system/2026-08-23",
        "rs-system",
        DAY,
        sha256=["hash-a", "hash-b", "hash-c"],
    )
    shas_multi = {str(o) for o in g_multi.objects(None, CORE.sourceSha256)}
    assert shas_multi == {"hash-a", "hash-b", "hash-c"}


def test_recorded_on_is_present_only_for_the_reference_table(kg_dataset):
    """recordedOn は『取得の無いソース』(ministry-codes)だけが持つこと。

    houjin-bangou は取得日(prov:generatedAtTime)を持つ実在の取得イベントが
    あるので、recordedOn(取得の概念が無いソースのための代替)は不要。
    両方に付けてしまうと「取得日と記録日は別概念」(レビューMod①)という
    区別そのものが無意味になる。
    """
    ministry = get_source("ministry-codes")
    houjin_graph_uri = URIRef(f"{BASE}/graph/houjin-bangou/{DAY.isoformat()}")
    ministry_graph_uri = URIRef(
        f"{BASE}/graph/ministry-codes/{ministry.recorded_on.isoformat()}"
    )

    g = kg_dataset.get_graph(URIRef(PROV_GRAPH_URI))
    recorded = g.value(ministry_graph_uri, CORE.recordedOn)
    assert recorded is not None, "ministry-codesのグラフに recordedOn が無い"
    assert str(recorded) == ministry.recorded_on.isoformat()

    assert g.value(houjin_graph_uri, CORE.recordedOn) is None, (
        "houjin-bangou(取得日を持つソース)に recordedOn が付いている"
    )
