"""FastAPI app(`jgkg.api.app`)のHTTP面のテスト: ルーティング・上限の拒否・404・起動時の温め処理。

ここでは`RdflibKGClient`をfixtureに束縛して使う——`create_app()`がclientを
1回だけ束縛する設計(advisorレビュー: これにより起動時の温め処理も同じ
テスト用clientに対して実行され、本物のFusekiへ接続しようとしない)。

**Windows固有の既知の摩擦(実測)。** `fastapi.testclient.TestClient`は
ASGI越しの同期呼び出しをasyncioのイベントループで裏打ちする。Windowsには
`AF_UNIX`が無いため、CPython標準の`socket.socketpair()`は
loopback(127.0.0.1)TCPソケットで代用する(`Lib/socket.py`の
`_fallback_socketpair`)——asyncioのイベントループ自身の自己pipeがこれを
使い、`tests/conftest.py`の`socket.socket.connect`遮断に引っかかる
(実測)。これは外部ネットワークへの実アクセスではなく同一プロセス内の
asyncio配線であり、Linux(CIの実行環境。ubuntu-latest)では
`socket.socketpair()`が`AF_UNIX`で実装されているためそもそも発生しない
——**Windows上のこの遮断だけを狙って外す**(下の`_allow_loopback_for_asgi_testclient`。
`tests/conftest.py`のdocstring項4「テスト自身がmonkeypatchで上書きすれば
迂回できる」という明示的に許容された経路を使い、127.0.0.1以外への接続は
従来通り遮断したままにする)。

**この迂回自体はteam-leadの裁定を経ていない(要相談)。** A-2の遮断は実際の
事故(コネクタのスタブ化忘れによる政府サーバへの実アクセス)を受けて作られた
安全装置であり、1ファイルとはいえその一部を緩めるのはこのテストの著者
(私)の一存で決めてよい範囲を超えている可能性がある。**`sys.platform`で
Windows限定にしてあり**、Linux(CIの実行環境)では以下のフィクスチャは
何もせず、conftest.pyの遮断がそのまま(このファイルを追加する前と
バイト単位で同じ)効く——実害の範囲をこのローカル開発環境だけに
限定している。
"""
import socket as _socket_module
import sys

import conftest
import phase1_fixture as fx
import pytest
from fastapi.testclient import TestClient
from rdflib import Dataset

from jgkg.api.app import create_app
from jgkg.api.kgclient import RdflibKGClient
from jgkg.api.queries import ENTITY_RELATIONSHIPS_MAX_LIMIT, SEARCH_MAX_LIMIT
from jgkg.api.warmup import warm_up

BASE = "https://jgkg.norr-tech.com"

# **収集時点(conftest.pyの遮断がまだ効いていない時点)で本物のconnectを捕捉する。**
# フィクスチャの中で`socket.socket.connect`を読んでも、その時点では既に
# conftest.pyの`_block_network`(autouse)が`_blocked`へ書き換え済みである
# ため、本物を取れない
_REAL_SOCKET_CONNECT = _socket_module.socket.connect
_REAL_SOCKET_CONNECT_EX = _socket_module.socket.connect_ex
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


@pytest.fixture(autouse=True)
def _allow_loopback_for_asgi_testclient(monkeypatch):
    """127.0.0.1/::1宛だけ本物のconnectを通す。他は従来通り`conftest._blocked`。

    **Windows限定。** Linux(`socket.socketpair()`がAF_UNIXで実装されており
    この摩擦がそもそも起きない)では何もパッチしない——CIの遮断挙動は
    このファイルが無かった場合と完全に同じ。
    """
    if sys.platform != "win32":
        yield
        return

    def _connect(sock, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host in _LOOPBACK_HOSTS:
            return _REAL_SOCKET_CONNECT(sock, address, *args, **kwargs)
        return conftest._blocked(sock, address, *args, **kwargs)

    def _connect_ex(sock, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host in _LOOPBACK_HOSTS:
            return _REAL_SOCKET_CONNECT_EX(sock, address, *args, **kwargs)
        return conftest._blocked(sock, address, *args, **kwargs)

    monkeypatch.setattr(_socket_module.socket, "connect", _connect)
    monkeypatch.setattr(_socket_module.socket, "connect_ex", _connect_ex)
    yield


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
def kg(tmp_path) -> Dataset:
    return fx.build_dataset(tmp_path / "out")


def _percent_encoded_entity_iris(kg: Dataset) -> set[str]:
    """fixtureの実行時グラフにある、`%`を含む`{BASE}/id/`配下のIRIを全て集める。

    **裁定B69: 「対象0件で通る空虚なテスト」を避けるための固定点。**
    `%`含みのB69系テストが実際に何を検査対象にしているかを、fixture全体の
    件数と対比して報告できるようにする(team-lead依頼(1))。主語・目的語
    どちらの位置に現れても対象にする(`UnresolvedReference`は関係の
    目的語側に現れる。`URIRef`のみを見る——リテラル値が偶然`%`を含んでも
    誤検出しない)。
    """
    from rdflib import URIRef

    prefix = f"{BASE}/id/"
    found: set[str] = set()
    for s, _p, o, _g in kg.quads((None, None, None, None)):
        for term in (s, o):
            if isinstance(term, URIRef):
                text = str(term)
                if "%" in text and text.startswith(prefix):
                    found.add(text)
    return found


class _RecordingClient:
    """`warm_up`が実際に束縛済みclientへ問い合わせることを確認するための薄いスパイ。"""

    def __init__(self, inner):
        self._inner = inner
        self.queries: list[str] = []

    def query(self, sparql: str):
        self.queries.append(sparql)
        return self._inner.query(sparql)


@pytest.fixture
def app_and_spy(kg):
    spy = _RecordingClient(RdflibKGClient(kg))
    app = create_app(spy, base_uri=BASE)
    return app, spy


# =============================================================================
# 起動時のキャッシュ温め(裁定B55対策)がテスト用clientに対して実際に走ること
# =============================================================================


def test_startup_runs_warmup_against_the_bound_client_without_hitting_network(app_and_spy):
    """advisorレビューで指摘された食い違い(設定から新規clientを作ると温め処理
    だけ本物のFusekiに繋ぎに行ってしまう)が無いことの直接的な証拠。

    `TestClient`をコンテキストマネージャとして使う(`with`)と、実際にlifespanの
    startupが走る——単に`create_app()`を呼ぶだけでは走らない。

    **裁定B60**: 温めが実際に`search_entities`(`skos:prefLabel`を全型横断で
    読むラベル領域。`ORDER BY`はLIMIT前の全件評価を強制する)を経由することを
    確認する——旧版が検査していた`budget:Expenditure`はどのエンドポイントも
    読まない領域だった。**このassertはクエリが投げられたことしか見ない**
    (`_RecordingClient`は`inner.query()`を呼ぶ**前**に記録するため、
    `CONTAINS(x, "")`が実際に例外なく成功したかどうかまでは検査しない
    ——`warm_up`は例外を握りつぶすため空文字列検索が失敗しても本テストは
    緑のままになりうる)。その成功自体は
    `test_warm_up_end_to_end_against_the_rdflib_fixture_succeeds`が別に見る。
    """
    app, spy = app_and_spy
    assert spy.queries == [], "with句に入る前から温め処理が走っている(前提が崩れている)"
    with TestClient(app):
        pass
    assert any("skos:prefLabel" in q and "ORDER BY" in q for q in spy.queries), (
        f"起動時にsearch_entitiesが実際に読むラベル領域へ触れる温めクエリが実行されていない: "
        f"{spy.queries}"
    )


def test_warm_up_end_to_end_against_the_rdflib_fixture_succeeds(kg):
    """空虚なテストにしない: 上のテストと`tests/test_api_warmup.py`は
    クエリ文字列の形(`skos:prefLabel`・`ORDER BY`)しか見ておらず、
    `warm_up`が使う空文字列検索語(`FILTER(CONTAINS(x, ""))`)が実際の
    SPARQLエンジン(rdflib。将来ARQでも)で例外にならず最後まで成功する
    ことは別に検査する必要がある——`warm_up`は例外を握りつぶすため、
    ここが壊れても他のテストは緑のままになりうる。

    本物のfixtureデータ(`RdflibKGClient(kg)`)に対して`warm_up`を実行し、
    `None`(失敗)ではないことを直接確認する。
    """
    elapsed = warm_up(RdflibKGClient(kg), BASE)
    assert elapsed is not None, "空文字列検索がRdflibKGClient経由で最後まで成功していない"


# =============================================================================
# ルーティング(検索・エンティティ詳細)
# =============================================================================


def test_get_search_returns_mixed_type_results(app_and_spy):
    app, _ = app_and_spy
    with TestClient(app) as tc:
        resp = tc.get("/search", params={"q": "厚生労働省"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    types = {hit["type"] for hit in body["results"]}
    assert "Ministry" in types
    assert "Law" in types
    assert body["truncated"] is False


def test_get_entity_detail_for_a_known_project(app_and_spy):
    app, _ = app_and_spy
    with TestClient(app) as tc:
        resp = tc.get(f"/entity/budget/2025/{fx.PROJECT_CORE}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["type"] == "BudgetProject"
    assert "Ministry" in body["relationships"]
    assert "Expenditure" in body["relationships"]


def test_get_entity_detail_404_for_unknown_id(app_and_spy):
    app, _ = app_and_spy
    with TestClient(app) as tc:
        resp = tc.get("/entity/org/0000000000000")
    assert resp.status_code == 404, resp.text


# =============================================================================
# 検索とエンティティ詳細の合成(裁定B59-(5))
# =============================================================================


def test_search_hit_id_path_composes_with_entity_detail(app_and_spy):
    """アプリレベルの合成テスト。`/entity/{id:path}`ルートコンバータ自身を
    検証対象に含めるため、関数呼び出し(search_entities/get_entity_detail)
    ではなくHTTP経由で検証する(裁定B59: 単体では真、合成では偽になった
    欠陥は単体テストでは検出できない)。

    ヒットは既知のid(厚生労働省)で選ぶ——`results[0]`のような順序依存は
    型混在のクエリでは何が先に来るか自明ではないため避ける。
    """
    app, _ = app_and_spy
    with TestClient(app) as tc:
        search_resp = tc.get("/search", params={"q": "厚生労働省"})
        assert search_resp.status_code == 200, search_resp.text
        hits = search_resp.json()["results"]
        ministry_hits = [h for h in hits if h["id"] == f"{BASE}/id/org/{fx.KOUSEIROUDOU_BANGOU}"]
        assert len(ministry_hits) == 1, f"前提(厚生労働省が1件ヒットする)が崩れている: {hits}"
        hit = ministry_hits[0]

        detail_resp = tc.get(f"/entity/{hit['id_path']}")
    assert detail_resp.status_code == 200, detail_resp.text
    assert detail_resp.json()["id"] == hit["id"], "検索ヒットとエンティティ詳細のidが一致しない"


# =============================================================================
# %を含むid_pathでの合成(裁定B69。B59直後に1フィールド隣で見つかった族)
# =============================================================================


def test_search_hit_id_path_composes_with_entity_detail_for_a_percent_encoded_id(app_and_spy):
    """裁定B69の合成テスト(検索→詳細)。

    上の`test_search_hit_id_path_composes_with_entity_detail`は`厚生労働省`
    (ASCIIの法人番号)を選んでおり、`_SEARCHABLE_TYPES`に`org:
    AbolishedGovernmentOrgan`が入っているにもかかわらず、エンコードが
    必要な`id_path`を一度も通らない——「テストの被覆は、アサーションの
    強さだけでなく入力に何を選んだかで決まる」(裁定B69)の実例。
    `OLD_KOUSEISHO_NAME`(`"厚生省"`)を選び、`%`を含む`id_path`を実際に通す
    (fixtureにデータを足す必要はない——`uris.py`が名称をpercent-encodeする
    ため、fixtureの実行時グラフは既に`%`を含むIRIを持っている)。
    """
    app, _ = app_and_spy
    with TestClient(app) as tc:
        search_resp = tc.get("/search", params={"q": fx.OLD_KOUSEISHO_NAME})
        assert search_resp.status_code == 200, search_resp.text
        hits = search_resp.json()["results"]
        abolished_hits = [h for h in hits if h["type"] == "AbolishedGovernmentOrgan"]
        assert len(abolished_hits) == 1, f"前提(厚生省が1件ヒットする)が崩れている: {hits}"
        hit = abolished_hits[0]
        # **対象件数をアサートする(検査対象0件で通る空虚なテストにしない)。**
        assert "%" in hit["id_path"], (
            f"前提(id_pathがpercent-encodeを必要とする)が崩れている: {hit}"
        )

        detail_resp = tc.get(f"/entity/{hit['id_path']}")
    assert detail_resp.status_code == 200, detail_resp.text
    assert detail_resp.json()["id"] == hit["id"], (
        "検索ヒットとエンティティ詳細のidが一致しない(裁定B69: %を含むid_pathで"
        "entity_uriを素の文字列結合にすると、Starletteのデコードを経て"
        "KGに存在しないIRIになる)"
    )


def test_relationship_related_id_path_composes_with_entity_detail_for_a_percent_encoded_id(
    app_and_spy,
):
    """裁定B69の合成テスト(詳細→関係の相手→詳細。裁定B59(2)が警告した
    「1ホップ先」の経路そのもの)。

    `law/{NO_CANDIDATE_LAW_ID}`はjurisdiction未解決(reason=NO_CANDIDATE)の
    `UnresolvedReference`(`%`を含む`id_path`)への関係を1件持つ。B59修正時は
    「`related`が`id_path`を持つこと」しか検査しておらず、「それを引いて
    同じ`id`が返ること」は検査していなかった——ここではHTTP経由で実際に
    1ホップして確認する(関数呼び出しでは`sparql_iri`が`id_path`
    (エンコード形)を二重エンコードして0件→404になるため、この欠陥は
    HTTPルート経由でしか再現しない。裁定B69の検証表参照)。
    """
    app, _ = app_and_spy
    with TestClient(app) as tc:
        detail_resp = tc.get(f"/entity/law/{fx.NO_CANDIDATE_LAW_ID}")
        assert detail_resp.status_code == 200, detail_resp.text
        detail = detail_resp.json()
        unresolved_rels = detail["relationships"].get("UnresolvedReference", [])
        assert len(unresolved_rels) == 1, (
            f"前提(UnresolvedReferenceへの関係が1件)が崩れている: {detail}"
        )
        related = unresolved_rels[0]["related"]
        # **対象件数をアサートする(検査対象0件で通る空虚なテストにしない)。**
        assert "%" in related["id_path"], (
            f"前提(related.id_pathがpercent-encodeを必要とする)が崩れている: {related}"
        )

        hop_resp = tc.get(f"/entity/{related['id_path']}")
    assert hop_resp.status_code == 200, hop_resp.text
    assert hop_resp.json()["id"] == related["id"], (
        "関係の相手側から1ホップしたエンティティ詳細のidが、relatedのidと一致しない"
        "(裁定B69)"
    )


def test_fixture_has_a_known_number_of_percent_encoded_entities(kg):
    """裁定B69: fixtureが持つ`%`含みIRIの総数を固定する(team-lead依頼(1))。

    この数(6件)は、B69系テストが実際に何件を検査対象にしているかを
    報告できるようにするための固定点である——`org/abolished/...`
    (`AbolishedGovernmentOrgan`)・`unresolved/jurisdiction/999RS.../...`
    (`UnresolvedReference`。NO_CANDIDATE)・`law/417M60000100021/...`×2
    (`LawRevision`)・`unresolved/jurisdiction/327M50000100010/...`
    (`UnresolvedReference`。OLD_MINISTRY)・`budget/.../unresolved/...`
    (未解決の支出受取先)。**この6件のうち3件を、このファイルのB69系
    テスト3本がそれぞれ1件ずつ実際に検査対象にする**(検索→詳細/詳細→
    関係の相手→詳細/直接アドレス)。fixtureが変わって件数がずれたら、
    このテスト自身がそれを知らせる(意図的な固定であり、放置してよい
    失敗ではない)。
    """
    iris = _percent_encoded_entity_iris(kg)
    assert len(iris) == 6, f"fixtureの%含みIRIの件数が想定と異なる: {sorted(iris)}"


def test_entity_detail_resolves_directly_for_a_percent_encoded_law_revision(app_and_spy, kg):
    """裁定B69の直接アドレス経路のテスト(team-lead依頼(1))。

    実KGでは、`%`を含むIRIのうち`LawRevision`が占める分が大きく
    (具体的な比率は裁定B69タスクレビュー追記(3)参照——controllerが実測した
    数字であり、ここには転記しない)、しかも関係の辺を1本も持たない
    (実KGの観察O10と同じ形)。fixtureでも同じ形が再現する——検索
    (`_SEARCHABLE_TYPES`に`law:LawRevision`は入っていない)・関係経由の
    合成テストのどちらからも到達できず、**`/entity/{id}`を直接叩く経路
    でのみ**検査できる。
    `/entity/{id:path}`は公開ルートである以上、この経路も検査対象にする
    (「通常は踏まない」は「直さなくてよい」を意味しない)。

    id_pathは手書きしない(日本語のamendment_law_numを直接埋め込むと
    transcriptionミスの危険がある)——fixtureの実行時グラフから、この
    エンティティの真のIRIをそのまま取って使う。
    """
    percent_iris = _percent_encoded_entity_iris(kg)
    law_revision_prefix = f"{BASE}/id/law/{fx.KOUSEIROUDOU_LAW_ID}/"
    law_revisions = sorted(iri for iri in percent_iris if iri.startswith(law_revision_prefix))
    assert law_revisions, (
        f"前提(KOUSEIROUDOU_LAW_IDのLawRevisionが%含みIRIとして存在する)が"
        f"崩れている: {sorted(percent_iris)}"
    )
    true_iri = law_revisions[0]
    id_path = true_iri[len(f"{BASE}/id/") :]
    assert "%" in id_path  # 対象件数をアサートする(空虚なテストにしない)

    app, _ = app_and_spy
    with TestClient(app) as tc:
        resp = tc.get(f"/entity/{id_path}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == true_iri, (
        "直接アドレスしたエンティティ詳細のidが、fixtureの真のIRIと一致しない"
        "(裁定B69)"
    )
    assert body["type"] == "LawRevision"
    assert body["relationships"] == {}, (
        "前提(LawRevisionは関係の辺を1本も持たない。実KGの観察O10と同じ形)が"
        f"崩れている: {body['relationships']}"
    )


# =============================================================================
# 上限を超えるlimitは黙って丸めず拒否する(422)
# =============================================================================


def test_search_limit_over_max_is_rejected_not_silently_clamped(app_and_spy):
    app, _ = app_and_spy
    with TestClient(app) as tc:
        resp = tc.get("/search", params={"q": "厚生労働省", "limit": SEARCH_MAX_LIMIT + 1})
    assert resp.status_code == 422, resp.text


def test_entity_detail_limit_over_max_is_rejected_not_silently_clamped(app_and_spy):
    app, _ = app_and_spy
    with TestClient(app) as tc:
        resp = tc.get(
            f"/entity/budget/2025/{fx.PROJECT_CORE}",
            params={"limit": ENTITY_RELATIONSHIPS_MAX_LIMIT + 1},
        )
    assert resp.status_code == 422, resp.text


# =============================================================================
# SPARQLを外に出さない(仕様§9.1)
# =============================================================================


def test_no_route_accepts_a_raw_sparql_query(app_and_spy):
    """このアプリのルートは`/search`と`/entity/{id}`しか無いこと自体が
    「公開SPARQLを作らない」ことの証拠になる——OpenAPIスキーマのパス一覧で確認する。
    """
    app, _ = app_and_spy
    paths = set(app.openapi()["paths"])
    assert paths == {"/search", "/entity/{entity_id}"}, paths


# =============================================================================
# Windows用ループバック限定の抜け穴(このファイル冒頭)が
# 127.0.0.1以外を今も遮断していることの確認(壊し確認)
# =============================================================================


def test_loopback_exemption_still_blocks_non_loopback_hosts():
    """壊し確認: このファイルが足した抜け穴は127.0.0.1/::1限定であり、
    それ以外の宛先(実在しないTEST-NET-1。RFC 5737)への接続は
    tests/conftest.pyと同じく`NetworkBlockedError`のままであること。
    """
    import socket

    with pytest.raises(conftest.NetworkBlockedError):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("192.0.2.1", 80))
