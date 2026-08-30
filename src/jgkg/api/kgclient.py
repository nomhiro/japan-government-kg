"""データアクセスの継ぎ目(D-3ブリーフ拘束条件3)。

**リモートのSPARQLエンドポイント(本番)と、ローカルのrdflib Dataset(テスト)の
両方を叩ける形にする。** 既存の`tests/test_competency_questions_phase1.py`が
fixtureのrdflib Datasetに対して`.query()`を直接流している仕組みと同じ土台に乗る
ことで、APIのテストもFuseki(実ネットワーク)無しで書ける
——`tests/conftest.py`の`socket.socket.connect`遮断に一度も触れずに済む。

**正規化した行の形を1つに決める(`Term`/`Row`)。** rdflibの`ResultRow`
(URIRef/Literal/BNodeを直接持つ)と、SPARQL 1.1 JSON Results
(`{"type": "uri"|"literal"|"bnode", "value": ...}`の辞書)は形が違うため、
ルート側のコードがどちらのバックエンドかを意識しなくていいように、
両方をこの`Term`へ変換してから返す。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

import httpx
from rdflib import BNode, Dataset
from rdflib import Literal as RDFLiteral

#: SPARQL 1.1 JSON Resultsの`binding["type"]`と同じ3値。
TermKind = Literal["uri", "literal", "bnode"]


@dataclass(frozen=True)
class Term:
    """SPARQLの1つの束縛値。バックエンド(rdflib/リモートJSON)を問わず同じ形。"""

    value: str
    kind: TermKind
    lang: str | None = None

    @property
    def is_resource(self) -> bool:
        """リテラルではない(関係の相手になれる)かどうか。

        BNodeは実際にはこのKGでは生成されない(全エンティティが`emit`で
        materialize済みのURIを持つ。src/jgkg/rdf/emit.pyのコメント参照)ため
        本来到達しないはずの分岐だが、リモートJSONの`"type": "bnode"`を
        受け取っても`KeyError`ではなく「関係の相手として扱う」という
        安全側の挙動にする(壊し確認: test_api_kgclient.py参照)。
        """
        return self.kind in ("uri", "bnode")


#: 1行 = 変数名 → Term(未束縛はNone)。
Row = dict[str, Term | None]


class KGClient(Protocol):
    """検索・エンティティ詳細のルートが依存する、唯一のインターフェース。

    ルート側はこの`query()`しか呼ばない。バックエンドの選択(本番は
    `RemoteKGClient`・テストは`RdflibKGClient`)は`app.py`の`create_app()`が
    1回だけ行う(`app.state.kg_client`に束縛。D-3裁定——advisorレビュー:
    起動時のキャッシュ温めフックも同じ束縛済みclientを読むことで、
    テストが`TestClient(app)`を起動するだけで温め処理も実際に
    (rdflibのfixtureに対して)実行される。設定から毎回新規clientを
    作る設計だと、温め処理だけが本物のFuseki接続を試みてテストで
    `NetworkBlockedError`になる、という食い違いが起きる)。
    """

    def query(self, sparql: str) -> list[Row]: ...


def sparql_string_literal(value: str) -> str:
    """ユーザー入力をSPARQLの文字列リテラルとして安全に埋め込む。

    **ユーザー入力(検索語等)をクエリ文字列に埋め込む経路をここ1箇所に
    集約する。** バックエンドが2種類(rdflibの`initBindings`、リモートの
    生HTTP POST)あり、両者に共通するバインディング機構が無いため
    (`initBindings`はrdflib専用でSPARQL 1.1 protocolには存在しない)、
    どちらのバックエンドでも「クエリ文字列を組み立てる」段で共通に使える
    エスケープをここに置く。エスケープ漏れ(SPARQLインジェクション)は
    1箇所直せば両方直る。
    """
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def canonical_iri(base_uri: str, id_path: str) -> str:
    r"""`/entity/{id}`のパス片から、KG内の真のIRI文字列(角括弧なし)を組み立てる。

    **`id_path`は経路(FastAPIの`{id:path}`)由来の生文字列であり、信頼しない。**
    セグメントごとに`quote(..., safe="")`で再エスケープする——これは
    `src/jgkg/uris.py`がID生成時に使っているのと同じ関数・同じ`safe=""`である。

    **訂正(裁定B69。この関数=旧`sparql_iri`のdocstringの以前の誤り)**:
    以前は「正規のIDに対しては素通りするだけで実質的に変化しない(往復が
    壊れない)」と書いていたが、これは偽だった。**`quote`は素通りしない**
    ——FastAPI/Starletteは`{id:path}`ルートで`id_path`を渡す前に既に1回
    URLデコードしているため、ここでの`quote`は**そのデコードされた文字を
    再エンコードして戻している**のであって、「何もしない」のではない。
    この再エンコードがあるからこそ、クライアントが`id_path`を生のまま・
    正しくエンコードした形・デコード済み(日本語等)のどの形で渡しても、
    ここで同じ正規のIRIに収束する(堅牢さの理由)。

    **だからこそ、この関数を経由しない箇所は分岐する。** `get_entity_detail`
    (`queries.py`)は以前、応答の`id`を素の文字列結合
    (`f"{base_uri}/id/{id_path}"`)で組み立てていた——Starletteがデコード
    した文字がそこでは再エンコードされずそのまま残るため、`%`を含むIRI
    (`uris.py`の`unresolved_jurisdiction_uri`・`unresolved_ministry_uri`・
    `abolished_organ_uri`・`law_version_uri`のように名称等を`quote`する
    URI生成関数が対象——`LawRevision`・`UnresolvedReference`・
    `AbolishedGovernmentOrgan`に実在する)についてKGに存在しないIRIを
    応答の`id`として報告する欠陥になった(裁定B69。実データでの規模は
    `progress.md`参照——自分で確認していない数字なのでここには書かない)。
    **応答の`id`とSPARQLクエリの両方が
    この関数1本を通ることで、二度と分岐しないようにする**——`sparql_iri`
    はこの関数を角括弧で包むだけであり、`get_entity_detail`の`entity_uri`
    (応答の`id`に使う値)もこの関数を直接呼ぶ。

    `safe=""`のあとに残るのは`[A-Za-z0-9._~%-]`のみで、SPARQLのIRIREF文法が
    禁止する文字(`<> "{}|^\`` と空白・制御文字)は含まれ得ない。
    """
    from urllib.parse import quote

    quoted = "/".join(quote(segment, safe="") for segment in id_path.split("/"))
    return f"{base_uri}/id/{quoted}"


def sparql_iri(base_uri: str, id_path: str) -> str:
    """`canonical_iri`をSPARQLのIRIREF(`<...>`)として使える形にする。

    **角括弧を付けるだけの薄いラッパー(裁定B69)。** SPARQL用の処理を
    ここへ独自に書くと、応答側(`canonical_iri`を直接呼ぶ側)との分岐が
    再発しうる——`canonical_iri`という1本を両方が通る、という不変条件を
    この関数自身が破らないようにする。文字集合・堅牢さの理由は
    `canonical_iri`のdocstring参照。角括弧の外に出られないため、
    何が渡ってきてもクエリ構文を壊せない。
    """
    return f"<{canonical_iri(base_uri, id_path)}>"


class RdflibKGClient:
    """テスト用: rdflibのDatasetに直接クエリする(実ネットワーク無し)。

    `tests/phase1_fixture.py`の`build_dataset()`が返すDatasetをそのまま渡せる
    ——`tests/test_competency_questions_phase1.py`の`kg`フィクスチャと同じ土台。
    """

    def __init__(self, dataset: Dataset) -> None:
        self._dataset = dataset

    def query(self, sparql: str) -> list[Row]:
        result = self._dataset.query(sparql)
        variables = [str(v) for v in result.vars]
        rows: list[Row] = []
        for row in result:
            # **位置(zip)で読む。属性アクセス(`row.count`等)はrdflibの
            # ResultRowが持つメソッド名と衝突しうる**
            # (`jgkg.pipeline._expenditure_category_mismatches`のD-2での
            # 実測: SELECTの変数名`count`が`ResultRow.count()`と衝突した実例)。
            # ここは変数名が呼び出し側任せで衝突を予測できないため、
            # 常に位置アクセスにして同型の衝突を構造的に避ける
            rows.append(
                {name: _rdflib_term_to_term(term) for name, term in zip(variables, row, strict=True)}
            )
        return rows


def _rdflib_term_to_term(term: object) -> Term | None:
    if term is None:
        return None
    if isinstance(term, RDFLiteral):
        return Term(value=str(term), kind="literal", lang=term.language)
    if isinstance(term, BNode):
        return Term(value=str(term), kind="bnode")
    # URIRef、あるいは将来rdflibが返しうる他の非リテラル項。
    # 「リテラルでなければURI扱い」という安全側の既定にする
    return Term(value=str(term), kind="uri")


class RemoteKGClient:
    """本番用: リモートのFuseki SPARQLエンドポイントにHTTPで問い合わせる。

    ワイヤ形式は`scripts/run_cq.py`と同じ(`POST` + `Accept:
    application/sparql-results+json`)——既にD-1/D-2の実測で実際に使っている
    経路そのものを流用する。`client`を注入できるようにしてあるのは、
    テストで`httpx.MockTransport`を渡して実ソケットを一切開かずに
    このクラス自身を検証できるようにするため(壊し確認:
    tests/test_api_kgclient.py参照。渡さない場合は本番用の実clientを作る)。
    """

    def __init__(self, endpoint: str, client: httpx.Client | None = None) -> None:
        self._endpoint = endpoint
        self._client = client or httpx.Client(timeout=httpx.Timeout(30.0, read=300.0))

    def query(self, sparql: str) -> list[Row]:
        resp = self._client.post(
            self._endpoint,
            data={"query": sparql},
            headers={"Accept": "application/sparql-results+json"},
        )
        resp.raise_for_status()
        payload = resp.json()
        variables: list[str] = payload["head"]["vars"]
        rows: list[Row] = []
        for binding in payload["results"]["bindings"]:
            rows.append({name: _json_binding_to_term(binding.get(name)) for name in variables})
        return rows


def _json_binding_to_term(binding: dict[str, str] | None) -> Term | None:
    if binding is None:
        return None
    kind = binding["type"]
    if kind not in ("uri", "literal", "bnode"):
        # SPARQL 1.1 JSON Resultsは"typed-literal"のような追加型を歴史的に
        # 許容してきたが、Fuseki(Jena ARQ)の現行出力はここに来ない。
        # 未知の型を`literal`として扱う(値そのものは失わない)のが
        # 「無視して落とす」よりも安全側
        kind = "literal"
    return Term(value=binding["value"], kind=kind, lang=binding.get("xml:lang"))


#: SPARQLのIRIREF(`<...>`)の中に現れられない文字(Turtle/SPARQL文法)。
#: 制御文字と空白、そして `<>"{}|^` とバックスラッシュ、バッククォート。
_IRIREF_FORBIDDEN = (
    frozenset(["<", ">", '"', "{", "}", "|", "^", "`", chr(0x5C)])
    | {chr(c) for c in range(0x21)}
    | {chr(0x7F)}
)


def sparql_iri_for_canonical_uri(uri: str) -> str:
    r"""**既に正準形の**完全IRIを、SPARQLのIRIREF(`<...>`)にする。

    **`sparql_iri(base_uri, id_path)`を流用してはならない。**
    あちらは**Starletteが1回URLデコードした経路片**を受け取る前提で
    **セグメントごとに再エンコードする**——**既にパーセントエンコード済みの
    IRIから作った`id_path`を渡すと`%`が`%25`になって二重エンコードになり、
    KGのIRIと一致しなくなる。**

    **D-4の実装中に実際に踏んだ。** 近傍サブグラフの1ホップ展開が、
    SPARQLの結果として受け取った完全IRI(`.../id/org/abolished/%E5%8E%9A...`)を
    `_id_path`で剥がして`sparql_iri`に渡していたため、
    `%E5%8E%9A` が `%25E5%258E%259A` になって**辺が1本も見つからなかった**。
    **裁定B59・B69と同じ族の欠陥(同じ値を2つの規則で作る)が、
    1層深いところにあった** ——
    **`%`を含むノードをテストの入力に選んだから出た**(観察O14:
    テストの被覆はアサーションの強さだけでなく入力の選び方で決まる)。

    **したがって使い分けは1つの規則で言える**:

    - **経路パラメータ(HTTP由来。デコード済み)から作るなら`sparql_iri`**
    - **KGから受け取った完全IRIから作るならこの関数**(何もエンコードしない)

    IRIREF文法が禁じる文字が含まれていたら例外にする——KG由来のIRIなら
    起こらないが、**黙って壊れたクエリを組み立てるより大きく失敗させる**
    (`_id_path`が`ValueError`にするのと同じ作法)。
    """
    bad = sorted(_IRIREF_FORBIDDEN & set(uri))
    if bad:
        raise ValueError(f"SPARQLのIRIREFに使えない文字を含むIRI: {uri!r}(該当: {bad})")
    return f"<{uri}>"
