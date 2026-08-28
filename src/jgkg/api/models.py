"""API応答の「封筒」型。**LinkMLでは生成しない**(D-3ブリーフの設計2)。

仕様§9.1は「各応答はLinkML生成のPydanticモデルで型付けする」と書いているが、
これは字面のまま実装しない——**仕様の文面からの意図的な逸脱**であり、
理由をここに書く。

`site.py`は`schema/generated/*.owl.ttl`をそのまま`/def/`として公開する
(オントロジー自身を公開成果物として扱う。設計書§5.7)。`SearchResponse`や
`EntityDetailResponse`のような**API都合の型**をLinkMLの`schema/*.yaml`に
足すと、`/def/`配下に「検索結果」や「打ち切りフラグ」がオントロジーの
クラスとして公開されてしまう——政府データを記述する語彙に、API実装の
都合が紛れ込む意味論的な誤りになる。

**したがって**:
- **封筒**(結果一覧・件数・打ち切りの有無・出典等)はここに手書きのPydanticで置く
- **エンティティの中身**(属性・関係)は、`EntityDetailResponse.attributes`が
  示すとおり**汎用の述語→値の辞書**(`dict[str, list[str]]`)として返す

**訂正(このモジュールの以前の版の誤り。advisorレビューで指摘)**: 以前の
記載は「エンティティの中身は`schema/generated/*_models.py`を単一の真実源
として使い、この封筒型はそれを包むだけ」と書いていたが、**実装はそうなって
いない**——`src/jgkg/api/`のどこも`schema/generated/*_models.py`の
LinkML生成クラス(`Law`・`Organization`・`BudgetProject`等)をimportも
インスタンス化もしていない(`queries.py`のSPARQL行から直接組み立てている)。
これは文書が実装と異なる主張をしていた実例そのもの(このプロジェクトが
繰り返し扱う欠陥型6)であり、ここで訂正する。

**現状の正確な設計**: オントロジーの契約(どの型がどのプロパティを持てるか)
は**emit時点+SHACL検証ゲートで既に強制済み**(`jgkg.validate`)——KGに
到達したデータは既にLinkMLの制約を満たしている。API層はそれを**再び型付け
し直さない**。汎用の辞書にした理由は、Law/Organization/BudgetProject/
Expenditure/AbolishedGovernmentOrgan等、型ごとに異なるフィールド集合を
持つ全エンティティを**1つの応答形で**扱えるようにするため
(型ごとにLinkML生成クラスへ振り分ける判別ロジックを`/entity/{id}`に
持たせない、というトレードオフ)。**この選択は、仕様§9.1・D-3ブリーフ設計2
が想定していた形からの、ブリーフが認識していなかった追加の逸脱であり、
team-leadの裁定を経ていない**(気になる点として報告する)。完全な語彙・
型の意味論は`/def/`(site.py公開のオントロジー)で常に確認できる。

閉じたモデル(`extra="forbid"`)にするのは、`schema/generated/all_models.py`の
`ConfiguredBaseModel`と同じ理由(SHACLの閉じたシェイプと同じ規律を封筒型にも
揃える)——ただし対象は封筒(このファイルの型)のみで、エンティティの中身の
構造そのものではない。
"""
from pydantic import BaseModel, ConfigDict


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EntityRef(_Envelope):
    """一覧・関係に出す最小限のエンティティ参照。"""

    id: str
    #: `id`(完全IRI)から導出した経路形。`GET /entity/{id_path}`にそのまま
    #: 渡せる(裁定B59)。
    #:
    #: **訂正(裁定B69。「そのまま渡せる」だけでは不十分だった)**:
    #: `%`を含む`id_path`(percent-encode済みのIRIが実データに存在する型:
    #: `LawRevision`・`UnresolvedReference`・`AbolishedGovernmentOrgan`)では、
    #: B59の時点で「そのまま渡せる」は**呼び方によって結果が違っていた**
    #: (裁定B69の検証表)——`GET /entity/{id_path}`(**HTTPルート経由**)は
    #: Starletteの1回デコード+`sparql_iri`の再エンコードが噛み合って200が
    #: 返っていたが、`get_entity_detail`を**直接関数呼び出し**すると
    #: `sparql_iri`が(デコードを経ない`id_path`をさらに)二重エンコードして
    #: 0件→404になる。**しかもHTTPルート経由の200は偽物だった**:
    #: `get_entity_detail`が応答の`id`を素の文字列結合で組み立てていたため、
    #: 200は返るのにKGに存在しないIRIを`id`として報告していた(裁定B69。
    #: 404より悪い——利用者が偽の同一性を正しい答えだと信じる)。この欠陥は
    #: `get_entity_detail`側(`kgclient.canonical_iri`)で修正済みであり、
    #: **現在はHTTPルート経由で`id_path`を渡して得た`EntityDetailResponse.id`
    #: は、この`EntityRef.id`と完全に一致する**(応答の`id`とSPARQLクエリの
    #: 両方が同じ1本の関数を通るため)。
    #:
    #: **背景**: `search_entities`は`id`に完全IRIを束縛する(`queries.py`の
    #: `SearchHit(id=entity, ...)`)一方、`get_entity_detail`は
    #: `entity_uri = f"{base_uri}/id/{id_path}"`を組み立てるため**パス形**を
    #: 期待する——`id`をそのまま`/entity/{id}`に渡すと必ず0件になり、
    #: 検索結果からエンティティ詳細へ遷移できない(実データで発見。単体テストは
    #: 両エンドポイントを別々にしか検証しておらず検出できなかった)。
    #:
    #: **`id`自体は完全IRIのまま変えない**(このプロジェクトの成果物はKGで
    #: あってアプリではない。IRIはLODの同一性そのもの)。代わりに、遷移用の
    #: 経路形をこの派生フィールドとして別に持つ。
    #:
    #: **`EntityRef`に足す(`SearchHit`だけに足さない)理由**: `queries.py`は
    #: 関係の相手側も`EntityRef(id=other, ...)`で組み立てる——検索ヒットだけ
    #: 直すと、詳細ページの「関係の相手をクリックして次の詳細へ」という
    #: 1ホップ先の遷移に同じ欠陥を残してしまう。
    #:
    #: **名前を`id_path`にした理由**(`href`ではなく): `get_entity_detail`
    #: 自身のパラメータ名`id_path`と揃える。`href`(`/entity/`込みの完全な
    #: クリック可能パス)にしなかったのは、`queries.py`のモジュールdocstring
    #: が「ルート(app.py)はsearch_entities()/get_entity_detail()しか呼ばない
    #: ——HTTP層とSPARQL/ドメインロジックを分けるため」と定めており、
    #: ここでAPIのルートパス自体(`/entity/`という文字列)を知る必要が
    #: 出るとその境界を越えてしまうため。
    id_path: str
    type: str
    label: str | None


class SearchHit(EntityRef):
    """検索結果の1件。`summary`だけが検索固有(エンティティ詳細には出さない)。"""

    #: 型ごとに導出する要約。1行での判断根拠は`queries.py`の
    #: `_derive_summary`のdocstringに書く(法令=法令番号、法人=所在地、
    #: 事業=年度と府省——D-3ブリーフの例をそのまま採用)
    summary: str | None


class SearchResponse(_Envelope):
    query: str
    results: list[SearchHit]
    #: 実際に採用された上限(既定値かクエリパラメータの指定値)
    limit: int
    #: **黙って切らない**(このプロジェクトが繰り返し扱ってきた「報告が嘘を
    #: つく」欠陥型そのもの)。Trueなら「limit件より先にまだ候補がある」。
    truncated: bool


class Provenance(_Envelope):
    """CQ7(`queries/cq/cq07-provenance-of-edge.rq`)と同じ3項+グラフ自身。"""

    graph: str
    source: str
    fetched_on: str
    license: str


class Relationship(_Envelope):
    """エンティティ詳細の関係1件。"""

    predicate: str
    #: このエンティティが主語(outgoing)か目的語(incoming)か
    #: (D-3ブリーフ「関係の向きを両方」)
    direction: str
    related: EntityRef
    provenance: Provenance


class EntityDetailResponse(_Envelope):
    id: str
    #: `EntityRef.id_path`と同じ導出規則・同じ理由(裁定B59)。
    #: `EntityDetailResponse`は`EntityRef`のサブクラスではないため
    #: (関係一覧・属性という別の形を持つ)、フィールドを個別に持つ——
    #: ただし導出自体は`queries.py`の`_id_path`ヘルパー1本を3箇所
    #: (`SearchHit`・`EntityRef`・ここ)全てから呼ぶことで揃える。
    id_path: str
    type: str
    label: str | None
    #: 述語(ローカル名)→値のリスト。1述語が複数値を持つことがあるため
    #: 常にlistにする(単値/多値で応答の形が変わると消費者側の分岐が増える)
    attributes: dict[str, list[str]]
    #: **関係の一覧を型別にグループ化**(D-3ブリーフ)。キーは「相手側
    #: エンティティ」の型のローカル名(例: "Law"・"Ministry"・"Expenditure")。
    #: 属性には現れない、関係固有の軸なので、属性のグループ化とは別に持つ
    relationships: dict[str, list[Relationship]]
    #: 実際に採用された上限
    relationships_limit: int
    #: **黙って切らない**(SearchResponse.truncatedと同じ理由)
    relationships_truncated: bool
