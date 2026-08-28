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
- **エンティティの中身**(属性・型)は`schema/generated/*_models.py`
  (LinkML生成、`schema/generated/all_models.py`)を単一の真実源として使う
  ——ここがオントロジーとの契約。このファイルの型はそれを**包む**だけで、
  中身の構造を独自に再定義しない
- **封筒**(結果一覧・件数・打ち切りの有無・出典等)はここに手書きのPydanticで置く

閉じたモデル(`extra="forbid"`)にするのは、`schema/generated/all_models.py`の
`ConfiguredBaseModel`と同じ理由(SHACLの閉じたシェイプと同じ規律をAPI応答にも
揃える)。
"""
from pydantic import BaseModel, ConfigDict


class _Envelope(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EntityRef(_Envelope):
    """一覧・関係に出す最小限のエンティティ参照。"""

    id: str
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
