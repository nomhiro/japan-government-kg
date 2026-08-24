"""Task 11 Step 1: 縦スライスの統合テスト(fixture。CIで回る)。

設計書§1.2完了条件(B)のデータ層そのもの: **府省令 → 府省 → 事業 → 支出先法人**
と、その逆をSPARQLで辿れること。ホップごとに出典グラフ(CQ7)が付くことも
ここで固定する。

**`emit_*`の直呼びではなく`pipeline.run`を1回通す。** `tests/phase1_fixture.py`
(CQ1〜10用)はorg側だけを`pipeline.run`経由にし、law/budgetは`emit_*`を直接
呼んで合流させている(Task 9時点では結線が無かったため)。それは各CQの
「答えられるか」を見るには十分だが、**結線そのもの**——3ソースを1本の
`pipeline.run`に通したときにグラフを跨いだ参照が実際に繋がるか——は
検査できない。このファイルはそこだけを見る。したがって
`include_all_corporations=True`(rs-systemを含むリリースの必須条件。
裁定B17懸念2/B18)も本番と同じ経路で通る。

**実データの実行(Task 11 Step 3〜6)はこのテストの代わりにならない。**
実データ側は約110分かかりCIで回せないので、経路の退行検出はここに置く。
逆に、ここが通っても実データで通るとは限らない(実際に
`egov_law.fetch`の`next_offset`欠落は実データでしか出なかった)。
両方が必要である。
"""
import csv
import datetime
import io
import json
import zipfile

import pytest
from rdflib import Dataset, URIRef
from zenken_rows import zenken_row, zipped

from jgkg import lake, pipeline, uris
from jgkg.connectors import egov_law, houjin_bangou, rs_system
from jgkg.transform import rs_columns

BASE = "https://jgkg.norr-tech.com"
DAY = datetime.date(2026, 8, 1)
RS_YEAR = 2025

# --- 実在の値(R45。tests/phase1_fixture.py のdocstringが出典を持つ) --------
KOUSEIROUDOU_BANGOU = "6000012070001"          # 厚生労働省
WOLFSTYLE_BANGOU = "3010001137944"             # 株式会社ウルフスタイル(実在RS支出先)
WOLFSTYLE_NAME = "株式会社ウルフスタイル"
KOUSEIROUDOU_LAW_ID = "417M60000100021"        # 実在のRS引用に現れる法令ID
KOUSEIROUDOU_LAW_NUM = "平成十七年厚生労働省令第二十一号"

# --- 架空の値(R45: 明らかに合成と分かる形式) -------------------------------
PROJECT_ID = "999901"                          # RSの実在project_idは4桁まで
FISCAL_YEAR = "2025"

LAW_NS = URIRef(f"{BASE}/def/law#")
BUDGET_NS = f"{BASE}/def/budget#"
SKOS_PREF_LABEL = URIRef("http://www.w3.org/2004/02/skos/core#prefLabel")
PROV_DERIVED_FROM = URIRef("http://www.w3.org/ns/prov#wasDerivedFrom")
PROV_GENERATED_AT = URIRef("http://www.w3.org/ns/prov#generatedAtTime")
DCTERMS_RIGHTS = URIRef("http://purl.org/dc/terms/rights")

LAW_JURISDICTION = URIRef(f"{BASE}/def/law#jurisdiction")
BUDGET_MINISTRY = URIRef(f"{BUDGET_NS}ministry")
BUDGET_PROJECT = URIRef(f"{BUDGET_NS}project")
BUDGET_RECIPIENT = URIRef(f"{BUDGET_NS}recipient")


@pytest.fixture(autouse=True)
def tmp_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", BASE)
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    monkeypatch.setenv("JGKG_QUARANTINE_DIR", str(tmp_path / "quarantine"))
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _zip_single_csv(text: str, member: str = "data.csv") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, text)
    return buf.getvalue()


def _rs_row(group: str, values: dict[str, str]) -> list[str]:
    spec = rs_columns.RS_FILES[group]
    row = [""] * len(spec.full_header)
    for name, value in values.items():
        row[spec.col[name]] = value
    return row


def _rs_csv(group: str, rows: list[list[str]]) -> str:
    spec = rs_columns.RS_FILES[group]
    buf = io.StringIO(newline="")
    writer = csv.writer(buf)
    writer.writerow(spec.full_header)
    writer.writerows(rows)
    return buf.getvalue()


def _seed_lake() -> None:
    """3ソースすべてを、互いに解決し合える最小構成でレイクに置く。"""
    # houjin-bangou: 府省(法人種別101)1件 + 支出先の民間法人(301)1件
    lake.save(
        "houjin-bangou", DAY, houjin_bangou.FILENAME,
        zipped(
            zenken_row(houjin_bangou=KOUSEIROUDOU_BANGOU, name="厚生労働省", kind="101")
            + zenken_row(
                houjin_bangou=WOLFSTYLE_BANGOU, name=WOLFSTYLE_NAME, kind="301", seq="2"
            )
        ),
    )

    # egov-law: 府省令1本。法令番号から「厚生労働省」を導出できる形(経路1)
    law = {
        "law_info": {
            "law_id": KOUSEIROUDOU_LAW_ID,
            "law_num": KOUSEIROUDOU_LAW_NUM,
            "law_num_type": "MinisterialOrdinance",
            "law_type": "MinisterialOrdinance",
            "promulgation_date": "2005-03-07",
        },
        "revision_info": None,
        "current_revision_info": {
            "law_title": "縦スライス試験用府省令",
            "abbrev": None,
            "repeal_status": "None",
        },
    }
    lake.save(
        "egov-law", DAY, egov_law.FILENAME,
        (json.dumps(law, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
    )

    # rs-system: 1事業(所管=厚生労働省・根拠法令=同じ府省令)+ 1支出
    # (支出先=法人番号直結)。**必須4グループ**(`rs.REQUIRED_GROUPS`)を揃える
    groups = {
        "project_summary": [
            _rs_row("project_summary", {
                "project_id": PROJECT_ID,
                "fiscal_year": FISCAL_YEAR,
                "project_name": "縦スライス試験事業",
                "ministry_name": "厚生労働省",
            }),
        ],
        "policy_measure_laws_and_regulations": [
            _rs_row("policy_measure_laws_and_regulations", {
                "project_id": PROJECT_ID,
                "fiscal_year": FISCAL_YEAR,
                "basis_law_id": KOUSEIROUDOU_LAW_ID,
                "basis_law_number": KOUSEIROUDOU_LAW_NUM,
                "basis_law_text": "縦スライス試験用府省令",
            }),
        ],
        "budget_summary": [
            _rs_row("budget_summary", {
                "project_id": PROJECT_ID,
                "budget_fiscal_year": FISCAL_YEAR,
                "budget_amount": "1000",
                "executed_amount": "0",
            }),
            # 前年度(分母)。B24(6)の比の観測が計算できる形にする
            _rs_row("budget_summary", {
                "project_id": PROJECT_ID,
                "budget_fiscal_year": "2024",
                "budget_amount": "900",
                "executed_amount": "1000",
            }),
        ],
        "payee_payment_information": [
            _rs_row("payee_payment_information", {
                "project_id": PROJECT_ID,
                "fiscal_year": FISCAL_YEAR,
                "recipient_name": WOLFSTYLE_NAME,
                "recipient_houjin_bangou": WOLFSTYLE_BANGOU,
                "expenditure_amount": "1000",
                "recipient_other_flag": "FALSE",
            }),
        ],
    }
    for group, rows in groups.items():
        lake.save(
            "rs-system", DAY, rs_system.filename_for(group, RS_YEAR),
            _zip_single_csv(_rs_csv(group, rows)),
        )


@pytest.fixture
def phase1_kg(tmp_path) -> Dataset:
    """3ソースを1本の`pipeline.run`に通して作った、実際の成果物(kg.nq)。"""
    _seed_lake()
    out = tmp_path / "out"
    report = pipeline.run(
        {"houjin-bangou": DAY, "egov-law": DAY, "rs-system": DAY},
        out,
        include_all_corporations=True,
    )
    # 縦スライスが成立する前提そのもの。ここが崩れていたら後続のホップの
    # アサートは「無いものを無いと言っている」だけになる
    assert report.graphs_quarantined == 0, "縦スライスのfixtureが隔離された"
    assert report.reference_violations == [], report.reference_violations
    assert report.law_jurisdiction_resolved == 1, "経路1(法令→府省)が解決していない"
    assert report.budget_ministries_resolved == 1, "事業→府省が解決していない"
    assert report.budget_recipients_resolved_by_houjin_bangou == 1, (
        "支出→支出先法人が法人番号で解決していない"
    )

    ds = Dataset(default_union=True)
    ds.parse(out / "kg.nq", format="nquads")
    return ds


def _graphs_containing(ds: Dataset, triple) -> list[URIRef]:
    """そのトリプルを実際に含む名前付きグラフの一覧(default_unionを迂回する)。"""
    s, p, o = triple
    return [
        URIRef(str(g.identifier))
        for g in ds.graphs()
        if str(g.identifier) != "urn:x-rdflib:default" and (s, p, o) in g
    ]


def _assert_hop_has_provenance(ds: Dataset, triple, label: str) -> URIRef:
    """そのホップが、出典3点(元ソース・取得日・ライセンス)を持つグラフに載っていること。

    CQ7が実データに対して行う確認を、ホップ単位でfixtureに固定する。
    **「どこかのグラフにある」では足りない** — 出典の無いグラフに入っていたら
    原則7(出典を持たない事実をKGに入れない)違反であり、CQ7が答えられない。
    """
    graphs = _graphs_containing(ds, triple)
    assert graphs, f"{label} のトリプルがどのグラフにも無い: {triple}"
    for g in graphs:
        assert (g, PROV_DERIVED_FROM, None) in ds, f"{label}: {g} に prov:wasDerivedFrom が無い"
        assert (g, PROV_GENERATED_AT, None) in ds, f"{label}: {g} に prov:generatedAtTime が無い"
        assert (g, DCTERMS_RIGHTS, None) in ds, f"{label}: {g} に dcterms:rights が無い"
    return graphs[0]


def test_vertical_slice_roundtrip(phase1_kg):
    """府省令 → 府省 → 事業 → 支出先法人 と、その逆をSPARQLで辿れること(§1.2 B のデータ層)。

    ホップごとに出典グラフ(CQ7)が付くこともここで固定する。

    何があれば落ちるか: いずれかのホップの述語・URI規約・グラフ分割が変わり、
    グラフを跨いだ結合が切れたとき(単体テストは各ソースのグラフを個別に
    見るため、跨ぎの切断はここでしか落ちない)。
    """
    ds = phase1_kg

    # --- 順方向: 府省令 → 府省 → 事業 → 支出 → 支出先法人 --------------------
    forward = list(ds.query(f"""
        PREFIX budget: <{BUDGET_NS}>
        PREFIX law:    <{BASE}/def/law#>
        PREFIX skos:   <http://www.w3.org/2004/02/skos/core#>
        SELECT ?law ?ministry ?ministryName ?project ?expenditure ?recipient ?recipientName
        WHERE {{
          ?law law:jurisdiction ?ministry .
          ?ministry skos:prefLabel ?ministryName .
          ?project budget:ministry ?ministry .
          ?expenditure budget:project ?project ;
                       budget:recipient ?recipient .
          ?recipient skos:prefLabel ?recipientName .
        }}
    """))
    assert len(forward) == 1, f"順方向の経路が1本に確定しない: {forward}"
    row = forward[0]
    assert str(row.law) == uris.law_uri(KOUSEIROUDOU_LAW_ID)
    assert str(row.ministry) == f"{BASE}/id/org/{KOUSEIROUDOU_BANGOU}"
    assert str(row.ministryName) == "厚生労働省"
    assert str(row.project) == uris.budget_uri(FISCAL_YEAR, PROJECT_ID)
    assert str(row.recipient) == f"{BASE}/id/org/{WOLFSTYLE_BANGOU}"
    assert str(row.recipientName) == WOLFSTYLE_NAME

    # --- 逆方向: 支出先法人 → 支出 → 事業 → 府省 → 府省令 --------------------
    # CQ4と同じ向き。**プロパティパスに畳まない**(どのホップで切れたかが
    # 分からなくなるため。CQ4のコメントと同じ理由)
    backward = list(ds.query(f"""
        PREFIX budget: <{BUDGET_NS}>
        PREFIX law:    <{BASE}/def/law#>
        SELECT ?law WHERE {{
          ?expenditure budget:recipient <{BASE}/id/org/{WOLFSTYLE_BANGOU}> ;
                       budget:project ?project .
          ?project budget:ministry ?ministry .
          ?law law:jurisdiction ?ministry .
        }}
    """))
    assert [str(r.law) for r in backward] == [uris.law_uri(KOUSEIROUDOU_LAW_ID)], (
        f"逆方向で府省令に行き着かない: {backward}"
    )

    # --- ホップごとの出典(CQ7) --------------------------------------------
    law_uri = URIRef(uris.law_uri(KOUSEIROUDOU_LAW_ID))
    ministry_uri = URIRef(f"{BASE}/id/org/{KOUSEIROUDOU_BANGOU}")
    project_uri = URIRef(uris.budget_uri(FISCAL_YEAR, PROJECT_ID))
    recipient_uri = URIRef(f"{BASE}/id/org/{WOLFSTYLE_BANGOU}")

    law_graph = _assert_hop_has_provenance(
        ds, (law_uri, LAW_JURISDICTION, ministry_uri), "府省令→府省"
    )
    budget_graph = _assert_hop_has_provenance(
        ds, (project_uri, BUDGET_MINISTRY, ministry_uri), "事業→府省"
    )
    _assert_hop_has_provenance(
        ds, (None, BUDGET_RECIPIENT, recipient_uri), "支出→支出先法人"
    )

    # **ホップが別々のソースのグラフに載っていること。** 全部が1つのグラフに
    # 入っていたら「グラフを跨いで辿れる」ことの証明になっていない
    assert str(law_graph) == uris.graph_uri("egov-law", DAY)
    assert str(budget_graph) == uris.graph_uri("rs-system", DAY)


def test_recipient_organization_lives_in_the_all_corporations_graph(phase1_kg):
    """支出先の民間法人は、848件規模の国の機関グラフではなく全法人グラフに居ること。

    **これが縦スライスが全法人フラグを必須にする理由そのもの**(裁定B17懸念2)。
    支出先が国の機関グラフに居るなら、そもそも全法人を投入する必要が無い。

    何があれば落ちるか: 全法人ストリームの出力がkg.nqに追記されなくなったとき
    (追記はrdflibのDatasetを経由しない別経路なので、他のテストでは落ちない)。
    """
    recipient_uri = URIRef(f"{BASE}/id/org/{WOLFSTYLE_BANGOU}")
    ministry_uri = URIRef(f"{BASE}/id/org/{KOUSEIROUDOU_BANGOU}")

    recipient_graphs = {
        str(g) for g in _graphs_containing(
            phase1_kg, (recipient_uri, SKOS_PREF_LABEL, None)
        )
    }
    all_corp_graph = uris.graph_uri("houjin-bangou-all", DAY)
    assert recipient_graphs == {all_corp_graph}, (
        f"支出先法人が全法人グラフだけに居るはずが {recipient_graphs}"
    )

    # 対照: 府省は両方のグラフに居る(国の機関グラフにも、全法人にも)。
    # ここを固定しないと、上のアサートが「全法人グラフしか無い」だけの
    # 状態(=国の機関グラフが消えた退行)を通してしまう
    ministry_graphs = {
        str(g) for g in _graphs_containing(
            phase1_kg, (ministry_uri, SKOS_PREF_LABEL, None)
        )
    }
    assert ministry_graphs == {uris.graph_uri("houjin-bangou", DAY), all_corp_graph}, (
        f"府省のグラフ構成が想定と違う: {ministry_graphs}"
    )


def test_all_hops_survive_a_round_trip_through_nquads_on_disk(phase1_kg, tmp_path):
    """kg.nqに書いて読み直したあとでも経路が辿れること(N-Quadsの往復)。

    何があれば落ちるか: グラフ名の書き出し・読み込みが非対称になったとき
    (`phase1_kg`自体が既にkg.nqの読み直しなので、ここではもう一往復させて
    「1回目だけ通る」形の欠陥を排除する)。
    """
    path = tmp_path / "roundtrip.nq"
    phase1_kg.serialize(destination=str(path), format="nquads")

    again = Dataset(default_union=True)
    again.parse(path, format="nquads")

    assert next(iter(again.query(f"""
        PREFIX budget: <{BUDGET_NS}>
        PREFIX law:    <{BASE}/def/law#>
        ASK {{
          ?e budget:recipient <{BASE}/id/org/{WOLFSTYLE_BANGOU}> ; budget:project ?p .
          ?p budget:ministry ?m .
          ?l law:jurisdiction ?m .
        }}
    """))) is True

    assert {str(g.identifier) for g in again.graphs() if len(g) > 0} == {
        str(g.identifier) for g in phase1_kg.graphs() if len(g) > 0
    }, "往復でグラフ集合が変わった"
