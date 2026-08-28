"""データアクセスの継ぎ目(`jgkg.api.kgclient`)のテスト。

**RemoteKGClientは`httpx.MockTransport`で検証する**(実ソケットを一切開かない
——`tests/conftest.py`の遮断に触れずに、リモート側の実装だけを確認できる)。
`RdflibKGClient`は`tests/phase1_fixture.py`のfixtureと同じ土台で確認する。
"""
import httpx
import pytest
from rdflib import RDF, BNode, Dataset, Literal, URIRef

from jgkg.api.kgclient import (
    RdflibKGClient,
    RemoteKGClient,
    canonical_iri,
    sparql_iri,
    sparql_string_literal,
)

BASE = "https://jgkg.norr-tech.com"


# =============================================================================
# sparql_string_literal: エスケープ(ユーザー入力の埋め込みが安全であること)
# =============================================================================


def test_sparql_string_literal_escapes_quotes_and_backslashes():
    assert sparql_string_literal('a"b\\c') == '"a\\"b\\\\c"'


def test_sparql_string_literal_neutralizes_an_injection_attempt():
    """引用符を閉じてクエリ構文へ脱出しようとする入力が、1本のリテラルの
    中身として無害化されること(壊し確認: エスケープを外すとこのテストが
    実際に別のトリプルを見せてしまう形で落ちる)。
    """
    ds = Dataset(default_union=True)
    g = ds.graph(URIRef(f"{BASE}/graph/probe"))
    g.add((URIRef(f"{BASE}/id/org/1"), RDF.type, URIRef(f"{BASE}/def/org#Organization")))
    g.add((URIRef(f"{BASE}/id/org/1"), URIRef("http://www.w3.org/2004/02/skos/core#prefLabel"), Literal("正規の名前")))
    g.add((URIRef(f"{BASE}/id/org/2"), URIRef("http://www.w3.org/2004/02/skos/core#prefLabel"), Literal("秘密の名前")))

    injected = '"} UNION { ?entity <http://www.w3.org/2004/02/skos/core#prefLabel> ?label . FILTER(true'
    query = f"""
    PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
    SELECT ?label WHERE {{
      ?entity skos:prefLabel ?label .
      FILTER(CONTAINS(?label, {sparql_string_literal(injected)}))
    }}
    """
    client = RdflibKGClient(ds)
    rows = client.query(query)
    assert rows == [], f"注入が構文として解釈された(エスケープが機能していない): {rows}"


# =============================================================================
# sparql_iri: パス片からのIRI組み立て(uris.pyのquoteと同じ経路)
# =============================================================================


def test_sparql_iri_round_trips_a_normal_id():
    assert sparql_iri(BASE, "org/1234567890123") == f"<{BASE}/id/org/1234567890123>"


def test_sparql_iri_percent_encodes_characters_that_would_break_iriref_syntax():
    """`<``>`・空白のようなIRIREF構文を壊す文字が、クエリ内で角括弧の外へ
    出られないこと(壊し確認: quoteを外すとこのテストが構文エラーで落ちる
    ——SPARQL自体が拒否するので実害は「クラッシュしない」ことの確認になる)。
    """
    hostile = 'org/1> ?x ?y . SELECT ?leak WHERE { ?leak ?p "pwned'
    iri = sparql_iri(BASE, hostile)
    assert "<" not in iri[1:-1], iri
    assert ">" not in iri[1:-1], iri
    assert " " not in iri, iri

    ds = Dataset(default_union=True)
    client = RdflibKGClient(ds)
    # 構文エラーにならず、単に0件で返ることを確認する(クラッシュしない)
    rows = client.query(f"SELECT ?p ?o WHERE {{ {iri} ?p ?o }}")
    assert rows == []


# =============================================================================
# canonical_iri: 角括弧なしの真のIRI文字列(裁定B69)
# =============================================================================


def test_canonical_iri_round_trips_a_normal_id():
    assert canonical_iri(BASE, "org/1234567890123") == f"{BASE}/id/org/1234567890123"


def test_sparql_iri_is_canonical_iri_wrapped_in_brackets():
    """`sparql_iri`の出力が`canonical_iri`を角括弧で包んだ値と常に一致すること。

    **この検査の限界(誇張しない)**: 出力の一致だけを見るため、
    `sparql_iri`が`canonical_iri`を呼ばずに同じロジック(`quote(...,
    safe="")`)を独自に再実装しても、出力が偶然一致する限りこのテストは
    検出できない。検出できるのは、2つの実装が実際に**分岐した**場合
    (異なる`safe=`集合を使う等)だけである——「1本の関数を両方が通る」
    という構造そのものを縛るテストは、下の
    `test_sparql_iri_actually_calls_canonical_iri`が別に持つ。
    """
    for id_path in ("org/1234567890123", "unresolved/jurisdiction/999RS0000000099/ダミー機関"):
        assert sparql_iri(BASE, id_path) == f"<{canonical_iri(BASE, id_path)}>"


def test_sparql_iri_actually_calls_canonical_iri(monkeypatch):
    """「導出は1本」という不変条件を、出力比較ではなく呼び出しそのもので縛る
    (team-lead依頼(2))。

    **なぜ必要か**: 上のテストは出力の一致しか見ないため、`sparql_iri`が
    `canonical_iri`を呼ばずに同じロジックを再実装しても検出できない
    (このプロジェクトで「導出は1本」という同じ不変条件が、裁定B59→B69で
    1フィールド隣で2回破れた実績がある——コードレビューだけに頼らず、
    構造そのものをテストで固定する)。

    `jgkg.api.kgclient`モジュールの`canonical_iri`をspyに差し替え、
    `sparql_iri`の呼び出しがそのspyを実際に経由すること・戻り値が
    そのspyの戻り値に依存していることを検査する。**壊し確認**:
    `sparql_iri`を独自に`quote`し直す実装(`canonical_iri`を呼ばない)に
    戻すと、spyが一度も呼ばれず・戻り値もsentinelを含まないため、この
    テストは確実に落ちる(検証済み。task-B69-report.md参照)。
    """
    import jgkg.api.kgclient as kgclient_module

    calls: list[tuple[str, str]] = []

    def _spy_canonical_iri(base_uri: str, id_path: str) -> str:
        calls.append((base_uri, id_path))
        return "SENTINEL-CANONICAL-IRI"

    monkeypatch.setattr(kgclient_module, "canonical_iri", _spy_canonical_iri)

    result = sparql_iri(BASE, "org/1234567890123")

    assert calls == [(BASE, "org/1234567890123")], (
        "sparql_iriがcanonical_iriを実際に呼んでいない"
    )
    assert result == "<SENTINEL-CANONICAL-IRI>", (
        "sparql_iriの結果がcanonical_iriの戻り値に依存していない——"
        "独自にquoteをやり直す実装に戻っている疑いがある"
    )


def test_canonical_iri_recovers_the_true_iri_after_one_starlette_style_decode():
    """裁定B69の核心を最小再現する単体テスト。

    FastAPI/Starletteは`/entity/{id:path}`でURLデコードを1回行う——
    `canonical_iri`はそのデコードされた文字を`quote(..., safe="")`で
    再エンコードし、元のIRIに戻す(だからこそ、クライアントがid_pathを
    生のまま・正しくエンコードした形・デコード済みのどれで渡しても収束する)。

    **`get_entity_detail`が応答の`id`を旧版のように素の文字列結合
    (`f"{base_uri}/id/{id_path}"`)で作ると、この再エンコードを経ないため
    分岐する**——これが裁定B69そのもの(下の最後のassertで対比する)。
    """
    from urllib.parse import quote, unquote

    name = "厚生省"
    true_iri = f"{BASE}/id/org/abolished/{quote(name, safe='')}"
    id_path_as_stored = f"org/abolished/{quote(name, safe='')}"

    # Starletteが{id:path}で1回デコードした後に残る、生の(percent-encode
    # されていない)文字列を模す
    decoded_id_path = unquote(id_path_as_stored)
    assert decoded_id_path == "org/abolished/厚生省"

    assert canonical_iri(BASE, decoded_id_path) == true_iri, (
        "canonical_iriがStarletteのデコードを再エンコードして戻せていない"
    )
    # 対比: 素の文字列結合(裁定B69で置き換えた旧実装)は分岐する
    assert f"{BASE}/id/{decoded_id_path}" != true_iri


# =============================================================================
# RdflibKGClient: 正規化(literal/uri/未束縛/bnode)
# =============================================================================


@pytest.fixture
def sample_dataset() -> Dataset:
    ds = Dataset(default_union=True)
    g = ds.graph(URIRef(f"{BASE}/graph/probe"))
    g.add((URIRef(f"{BASE}/id/org/1"), RDF.type, URIRef(f"{BASE}/def/org#Organization")))
    g.add(
        (
            URIRef(f"{BASE}/id/org/1"),
            URIRef("http://www.w3.org/2004/02/skos/core#prefLabel"),
            Literal("株式会社テスト", lang="ja"),
        )
    )
    return ds


def test_rdflib_kgclient_normalizes_uri_and_literal(sample_dataset):
    client = RdflibKGClient(sample_dataset)
    rows = client.query(
        f"""
        PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
        SELECT ?type ?label WHERE {{
          <{BASE}/id/org/1> a ?type ; skos:prefLabel ?label .
        }}
        """
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["type"].kind == "uri"
    assert row["type"].value == f"{BASE}/def/org#Organization"
    assert row["label"].kind == "literal"
    assert row["label"].value == "株式会社テスト"
    assert row["label"].lang == "ja"


def test_rdflib_kgclient_unbound_optional_is_none(sample_dataset):
    """**`?type`も一緒にSELECTする(`?x`単独では検査できない)。**
    rdflibは、SELECT対象の変数が**全て**未束縛になる行を実際に消してしまう
    (実測——`SELECT ?x`だけだとこの行自体が0件になる。本番のクエリは
    常に1つ以上の必須パターン由来の変数[エンティティ自身のURI等]を
    一緒にSELECTしているため実害は無いが、このテストも同じ形にしないと
    「?xがNoneになること」ではなく別の現象を検査してしまう)。
    """
    client = RdflibKGClient(sample_dataset)
    rows = client.query(
        f"""
        SELECT ?type ?x WHERE {{
          <{BASE}/id/org/1> a ?type .
          OPTIONAL {{ <{BASE}/id/org/1> <{BASE}/def/org#doesNotExist> ?x }}
        }}
        """
    )
    assert len(rows) == 1
    assert rows[0]["x"] is None


def test_rdflib_kgclient_does_not_crash_on_bnode_subject():
    """このKGはBNodeを生成しない(emit.pyが全エンティティにURIを与える)が、
    仮に紛れ込んでもクラッシュせず`kind="bnode"`として正規化されること。
    """
    ds = Dataset(default_union=True)
    g = ds.graph(URIRef(f"{BASE}/graph/probe"))
    bnode = BNode()
    g.add((bnode, URIRef(f"{BASE}/def/core#amount_jpy"), Literal(100)))
    client = RdflibKGClient(ds)
    rows = client.query(f"SELECT ?s WHERE {{ ?s <{BASE}/def/core#amount_jpy> 100 }}")
    assert len(rows) == 1
    assert rows[0]["s"].kind == "bnode"
    assert rows[0]["s"].is_resource


# =============================================================================
# RemoteKGClient: httpx.MockTransportで実ソケット無しに検証する
# =============================================================================


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_remote_kgclient_posts_the_query_and_normalizes_json_results():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read().decode("utf-8")
        captured["accept"] = request.headers.get("accept")
        payload = {
            "head": {"vars": ["entity", "label"]},
            "results": {
                "bindings": [
                    {
                        "entity": {"type": "uri", "value": f"{BASE}/id/org/1"},
                        "label": {"type": "literal", "value": "テスト", "xml:lang": "ja"},
                    }
                ]
            },
        }
        return httpx.Response(200, json=payload)

    client = RemoteKGClient("http://localhost:3030/kg/sparql", client=_mock_client(handler))
    rows = client.query("SELECT ?entity ?label WHERE { ?entity <p> ?label }")

    assert captured["url"] == "http://localhost:3030/kg/sparql"
    assert "query=" in captured["body"]
    assert captured["accept"] == "application/sparql-results+json"
    assert len(rows) == 1
    assert rows[0]["entity"].kind == "uri"
    assert rows[0]["entity"].value == f"{BASE}/id/org/1"
    assert rows[0]["label"].kind == "literal"
    assert rows[0]["label"].lang == "ja"


def test_remote_kgclient_handles_bnode_binding_type_without_keyerror():
    """壊し確認: `type: "bnode"`をリテラル/URIどちらの分岐にも無い専用の
    `kind`として正規化できること(advisorレビュー指摘——ここを実装しないと
    `binding["type"]`の分岐から漏れてKeyError/誤分類になる)。
    """

    def handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "head": {"vars": ["s"]},
            "results": {"bindings": [{"s": {"type": "bnode", "value": "b0"}}]},
        }
        return httpx.Response(200, json=payload)

    client = RemoteKGClient("http://localhost:3030/kg/sparql", client=_mock_client(handler))
    rows = client.query("SELECT ?s WHERE { ?s ?p ?o }")

    assert rows == [{"s": rows[0]["s"]}]  # KeyErrorにならず1行返る
    assert rows[0]["s"].kind == "bnode"
    assert rows[0]["s"].value == "b0"


def test_remote_kgclient_unbound_variable_is_none():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "head": {"vars": ["s", "optional"]},
            "results": {"bindings": [{"s": {"type": "uri", "value": f"{BASE}/id/org/1"}}]},
        }
        return httpx.Response(200, json=payload)

    client = RemoteKGClient("http://localhost:3030/kg/sparql", client=_mock_client(handler))
    rows = client.query("SELECT ?s ?optional WHERE { ?s ?p ?o . OPTIONAL { ?s ?p2 ?optional } }")

    assert rows[0]["optional"] is None
