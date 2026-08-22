"""CQテスト。CQに答えられないオントロジーは不合格(設計書§1.2 完了条件A)。

CQが増えたらここに1件追加する。オントロジー変更のリグレッション検知の主手段。
"""
import datetime
from pathlib import Path

import pytest
from rdflib import Dataset

from jgkg import lake, pipeline
from jgkg.connectors import houjin_bangou

DAY = datetime.date(2026, 8, 1)
# 取得して来るソースの日付だけを渡す。参照表(ministry-codes)の日付は
# sources.py の recorded_on から取られる
FETCHED = {"houjin-bangou": DAY}
CQ_DIR = Path("queries/cq")


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
def kg(tmp_path):
    content = Path("tests/fixtures/houjin_bangou_sample.csv").read_bytes()
    lake.save("houjin-bangou", DAY, houjin_bangou.FILENAME, content)
    out = tmp_path / "out"
    pipeline.run(FETCHED, out)

    # default_union=True が必須。既定(False)では既定グラフが空のため、
    # GRAPH句を使わないCQクエリがすべて0件になる。本番のFusekiでも
    # tdb2:unionDefaultGraph true を設定して同じ意味論に揃える(Task 11)
    ds = Dataset(default_union=True)
    ds.parse(out / "kg.nq", format="nquads")
    return ds


@pytest.fixture
def kg_with_unresolved(tmp_path, monkeypatch):
    """CQ P0-5を、未解決が実際に存在する状態で検証するためのfixture。

    通常のfixture(参照表3府省がすべて突合される)では未解決が0件になり、
    「クエリが例外にならず空リストを返す」という常に真の確認しかできない
    (`test_cq_p0_05_unresolved_count` 参照)。ここでは参照表に候補の無い
    府省コードを1件追加し、`pipeline.run` を通した実際のパイプライン出力に
    対してクエリを流し、件数が正しく返ることを確認する。
    """
    content = Path("tests/fixtures/houjin_bangou_sample.csv").read_bytes()
    lake.save("houjin-bangou", DAY, houjin_bangou.FILENAME, content)

    reference_path = tmp_path / "ministry-codes-with-unresolved.csv"
    reference_path.write_text(
        "ministry_code,name\n020,厚生労働省\n999,存在しない省\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pipeline, "MINISTRY_REFERENCE", reference_path)

    out = tmp_path / "out"
    report = pipeline.run(FETCHED, out)
    # 未解決が実際に1件作られていること、かつSHACL検証で隔離されていないことを
    # ここで確認する。これが崩れていると、下のCQテストは「未解決を計測できて
    # いない」のか「未解決グラフがそもそも隔離された」のか区別できず誤診断になる
    assert report.unmatched_ministries == 1, "未解決を1件作るfixtureの前提が崩れている"
    assert report.graphs_quarantined == 0, "未解決を含むグラフが検証で隔離されてしまった"

    ds = Dataset(default_union=True)
    ds.parse(out / "kg.nq", format="nquads")
    return ds


@pytest.fixture
def kg_without_houjin_bangou(kg):
    """法人番号を持たない Organization を1件注入したKG。

    CQ P0-6 の正のコントロール用。`houjinBangou` は Ruling 2 で `required` を
    外しているのでSHACLは通ってしまう。つまりこの状態は**実際に起こりうる**。
    """
    from rdflib import RDF, URIRef

    from jgkg.config import get_settings
    from jgkg.rdf import emit

    base = get_settings().base_uri
    subject = f"{base}/id/org/9999999999999"
    data = kg.graph(URIRef(f"{base}/graph/houjin-bangou/{DAY.isoformat()}"))
    assert len(data) > 0, "注入先のデータグラフが空である"
    data.add((URIRef(subject), RDF.type, emit.NS["org"]["Organization"]))
    return kg, subject


def _query(ds: Dataset, name: str):
    return list(ds.query((CQ_DIR / name).read_text(encoding="utf-8")))


def _positive_control(ds: Dataset, name: str, drop: str):
    """CQクエリから否定条件の行を外した「正のコントロール」を流す。

    否定形のアサート(「違反が無いこと」)は**対象が0件でも合格する**。空のKG、
    名前空間のずれ、union意味論の無効化のいずれでも、CQは静かに0件を返して
    合格してしまう(レビューI5の実測では壊れ方4通りのうち3通りで合格した)。

    **PREFIX宣言をCQファイルそのものから取ることが要点。** テスト側で名前空間を
    書き直すと、名前空間がずれたときにコントロールも一緒にずれてしまい、
    ずれを検出できなくなる(それが C1 で起きたことである)。
    """
    text = (CQ_DIR / name).read_text(encoding="utf-8")
    stripped = "\n".join(ln for ln in text.splitlines() if drop not in ln)
    assert stripped != text, f"{name} に {drop!r} の行が無い。クエリの前提が変わっている"
    return list(ds.query(stripped))


def test_cq_p0_01_organization_lookup(kg):
    rows = _query(kg, "p0-01-organization-lookup.rq")
    assert rows, "CQ P0-1 に答えられない"
    assert str(rows[0][0]) == "厚生労働省"


def test_cq_p0_02_ministry_list(kg):
    rows = _query(kg, "p0-02-ministry-list.rq")
    assert rows, "CQ P0-2 に答えられない"
    codes = {str(r[3]) for r in rows}
    assert "020" in codes


def test_cq_p0_03_provenance_of_edge(kg):
    """出典を辿れることはCQの一つ。ここが通らなければ原則7が守れていない。

    クエリに ORDER BY が無いので `rows[0]` を当てにしない。法人番号を持つ
    グラフは法人番号グラフだけなので、全行がその取得日を答えるべきである。
    """
    rows = _query(kg, "p0-03-provenance-of-edge.rq")
    assert rows, "CQ P0-3 に答えられない(グラフの出典が辿れない)"
    for graph, _source, fetched_on, license_ in rows:
        assert "graph/houjin-bangou/" in str(graph), graph
        assert str(fetched_on).startswith("2026-08-01"), (graph, fetched_on)
        assert str(license_)


def test_cq_p0_04_release_freshness(kg):
    """各ソースについて「いつ時点か」を答えられること。

    **ソースごとに違う日付が返ることまで見る。** 以前は法人番号の取得日を
    府省参照表にも流用していたため、このCQは2ソースのうち1つについて根拠の
    無い日付を答えていた(レビューI2)。参照表には取得日が存在しないので、
    リポジトリに記録した日を答える。

    **何があれば落ちるか**: 参照表の日付が法人番号の取得日に戻ったら落ちる。
    ソースが1つでも欠けたら落ちる。
    """
    from jgkg.sources import get_source

    rows = _query(kg, "p0-04-release-freshness.rq")
    assert rows, "CQ P0-4 に答えられない(鮮度が問えない)"

    by_source = {str(name): str(date) for name, date in rows}
    houjin = get_source("houjin-bangou")
    ministry = get_source("ministry-codes")
    assert by_source == {
        houjin.name: "2026-08-01",
        ministry.name: ministry.recorded_on.isoformat(),
    }, by_source


def test_cq_p0_05_unresolved_count(kg):
    """未解決が0件でもクエリ自体は成立すること。件数を問える構造が要件。"""
    rows = _query(kg, "p0-05-unresolved-count.rq")
    assert isinstance(rows, list)


def test_cq_p0_05_unresolved_count_reports_actual_unresolved(kg_with_unresolved):
    """0件で成立するだけでは「件数を問える」ことの確認にならない(空振り)。

    実際に未解決を1件作った上でクエリを流し、正しい理由と件数が返ることまで
    確認する。ここが崩れると、正常系が常に0件のこのCQは静かに壊れたまま
    残り続ける。
    """
    rows = _query(kg_with_unresolved, "p0-05-unresolved-count.rq")
    assert rows, "未解決を1件作ったのにCQ P0-5が0件を返した"
    by_reason = {str(reason): int(count) for reason, count in rows}
    # 参照表の "999,存在しない省" はデータ側に候補が無いので NO_CANDIDATE になる
    assert by_reason == {"NO_CANDIDATE": 1}


CQ_P0_06 = "p0-06-organizations-without-houjin-bangou.rq"


def test_cq_p0_06_every_organization_has_houjin_bangou(kg):
    """法人番号を持たないOrganizationが存在しないこと。

    SHACLでは担保できない制約をここで見る。グラフをソース別に分けているため
    1エンティティの記述が複数グラフに分かれ、グラフ単位のSHACL検証では
    グラフを跨いだ必須制約を検証できない。設計書の判断に対する代償措置。

    **正のコントロールを先に主張する。** これが無いと、空のKG・名前空間のずれ・
    union意味論の無効化のいずれでも「違反0件」で合格してしまう。
    """
    control = _positive_control(kg, CQ_P0_06, drop="FILTER NOT EXISTS")
    assert len(control) >= 3, (
        f"同じPREFIXでOrganizationを1件も引けない。CQ P0-6 の『違反0件』は"
        f" 空振りである(名前空間のずれ・union無効・KGが空のいずれか): {control}"
    )

    rows = _query(kg, CQ_P0_06)
    assert rows == [], f"法人番号を持たないOrganizationがある: {rows}"


def test_cq_p0_06_detects_an_organization_without_houjin_bangou(kg_without_houjin_bangou):
    """法人番号を持たないOrganizationを1件注入したら、実際に1行返ること。

    **何があれば落ちるか**: クエリの名前空間がデータとずれたら落ちる。
    `VALUES ?type` から型が欠けたら落ちる。`FILTER NOT EXISTS` の条件が
    壊れたら落ちる。Ruling 2(houjinBangou の required を外す)の代償措置が
    実際に機能していることの唯一の証拠。
    """
    ds, injected = kg_without_houjin_bangou
    rows = _query(ds, CQ_P0_06)
    assert [str(r[0]) for r in rows] == [injected], (
        f"注入した {injected} が検出されない: {rows}"
    )
