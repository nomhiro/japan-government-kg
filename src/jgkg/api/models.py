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
    #: **出典の3項が実際に引けたか。**
    #:
    #: 近傍サブグラフとパス探索は、探索を軽くするため出典を**必須で結合しない**
    #: (`_build_expansion_query`のdocstring: 必須にすると`prov:wasDerivedFrom`等を
    #: 持たないグラフの辺が黙って消え、連結性が壊れる)。そのため
    #: **出典が引けないグラフがありうる。**
    #:
    #: `graphs`マップからキーを落とすことはしない(消費者にキーの不在を
    #: 扱わせない)。**代わりに、引けなかったことをこのフラグで明示する。**
    #: 空文字列だけを返すと**「出典が無い」ことを黙って隠す**ことになり、
    #: 仕様§9.2「全表示要素に一次資料へのリンクと取得日時を出す」に対して
    #: UIが空のリンクを描いてしまう(このプロジェクトが繰り返し扱う
    #: 「報告が嘘をつく」欠陥型)。
    #:
    #: **タスクレビューの指摘で追加した** —— この分岐は当初テストで一度も
    #: 踏まれておらず、「実データに一度も当てていない層は緑でも未検証」
    #: (再発欠陥9)そのものだった。
    available: bool = True


class Relationship(_Envelope):
    """エンティティ詳細の関係1件。"""

    predicate: str
    #: このエンティティが主語(outgoing)か目的語(incoming)か
    #: (D-3ブリーフ「関係の向きを両方」)
    direction: str
    related: EntityRef
    #: **出典は名前付きグラフのキーで持ち、`Provenance`を埋め込まない**
    #: (D-4の裁定2。以前はここに`provenance: Provenance`を埋め込んでいた)。
    #: 実体は応答のトップレベルの`graphs`マップにある。
    #:
    #: **理由は2つ、どちらも重要度が高い**:
    #:
    #: **(1) 埋め込み形は自己矛盾を許す。** 同じ名前付きグラフ由来の2つの辺が
    #: **異なるライセンスを主張できてしまう**形になっていた。出典は
    #: **名前付きグラフの属性**であって辺の属性ではない ——
    #: 辺ごとに複製すると、複製の間で食い違える構造を作る
    #: (このプロジェクトの再発欠陥4: 自己矛盾する定義)。
    #: キー参照にすれば、**同一グラフの辺が違う出典を主張することが
    #: 構造的に不可能**になる。
    #:
    #: **(2) 外向き通信量がコストである**(設計書§6.3・決定#33:
    #: 「§9.1のAPI層の件数上限は、性能対策であると同時にコスト対策である」)。
    #: 名前付きグラフは7本、辺は近傍サブグラフ(D-4)で数百本になりうる ——
    #: 同じ4つの文字列を数百回送る意味は無い。
    graph: str


class AttributeValue(_Envelope):
    """属性の1つの値と、それを主張する名前付きグラフの一覧(裁定B82(4a))。

    **単数の`graph`ではなく`graphs: list[str]`にする理由**: 同じ値が複数の
    名前付きグラフから主張されうる(複数ソースが同じ事実を持つ場合)。
    値の行を複製すると、同じ事実を主張する別々の値が2つあるように見える
    ——1つの値に対して「それを主張しているグラフの一覧」を持つのが正確
    (`Relationship.graph`のキー参照と同じ設計の理由)。**実データで実在を
    確認済み**(2026-09-02実測。Fuseki 884,052クアッド。`org:cityName`・
    `org:houjinBangou`等が`houjin-bangou`と`houjin-bangou-payees`のように
    別の名前付きグラフから同じ値を主張する組が実在する。
    `queries.py`の`_build_attributes_query`docstring参照)。
    """

    value: str
    #: **`graphs`マップ(`EntityDetailResponse.graphs`)のキーの一覧**
    #: (`Relationship.graph`と同じ規約。ただし複数持てる点が違う)。
    #: このリストの全要素が`EntityDetailResponse.graphs`に存在することを
    #: テストで縛る(`tests/test_api_entity.py`)。
    graphs: list[str]


class GraphEdge(_Envelope):
    """近傍サブグラフ・パス探索の辺1本。

    **`Relationship`と別の型にする理由**: `Relationship`は「あるエンティティ
    から見た関係」なので`direction`(自分が主語か目的語か)を持つ。
    サブグラフの辺は**特定の視点を持たない**ので、代わりに`source`/`target`
    (どちらも完全IRI)で向きを表す。`direction`を流用すると「誰から見た
    向きなのか」が応答から読めなくなる。
    """

    #: 主語側の完全IRI
    source: str
    #: 目的語側の完全IRI
    target: str
    #: 述語のローカル名
    predicate: str
    #: `graphs`マップのキー(`Relationship.graph`と同じ正規化。D-4の裁定2)
    graph: str


class NeighborhoodResponse(_Envelope):
    """近傍サブグラフ(仕様§9.1「指定ノードから深さ1-2のノード/エッジ」)。

    **既知の限界(観察O10)**: `LawRevision`(実データで9,550件)は
    **グラフの辺を1本も持たない** —— 法令への結びつきは`lawId`という
    リテラルとIRIのパスに埋まった法令IDだけで、辺として存在しない。
    **したがって法令の近傍に改正は一度も現れない。**
    利用者が「この法令の近傍にはこれしか無い」と読むのは誤りである
    (辺を足すのはPhase 2の課題)。**黙っていないためにここに書く**
    (このプロジェクトの再発欠陥6: 報告が嘘をつく)。
    """

    center: EntityRef
    #: 実際に採用された深さ(1 または 2)
    depth: int
    #: 中心を含む(重複しない)ノードの一覧
    nodes: list[EntityRef]
    edges: list[GraphEdge]
    graphs: dict[str, Provenance]
    #: 実際に採用された上限
    node_limit: int
    edge_limit: int
    #: **1ノードあたりの分岐数の上限。** 総数の上限だけでは足りない ——
    #: ハブ(数千の辺を持つ府省など)1個の隣接が上限を食い潰し、他の方向が
    #: 1つも見えなくなる。利用者には「そこには何も無い」と見える
    fanout_limit: int
    #: **黙って切らない**(SearchResponse.truncatedと同じ理由)
    nodes_truncated: bool
    edges_truncated: bool
    #: **分岐数の上限で隣接を切られたノードのIRI。** boolではなく一覧にする
    #: —— 「どのノードの先がまだあるのか」が分かる方が、利用者が次に何を
    #: 展開すべきか判断できる
    fanout_truncated_nodes: list[str]


class PathResponse(_Envelope):
    """パス探索(仕様§9.1「2エンティティ間の経路(法令↔法人など)」)。

    **`found=False`の読み方を応答の形で強制する。**
    「max_depth以内に経路が無かった」と「経路が存在しない」は違う ——
    空の結果だけを返すと利用者は後者だと読む(このプロジェクトが繰り返し
    重い欠陥として扱ってきた「報告が嘘をつく」型)。`exhaustive`が真で
    初めて後者を意味する。
    """

    start: EntityRef
    goal: EntityRef
    #: 見つかった経路の`start`から`goal`までのノード列。見つからなければ空
    nodes: list[EntityRef]
    #: `nodes`を順に繋ぐ辺(`len(nodes) - 1`本)。向きは`source`/`target`が持つ
    #: —— **経路は辺の向きに逆らって進むことがある**(下の`undirected`参照)
    edges: list[GraphEdge]
    graphs: dict[str, Provenance]
    found: bool
    #: 実際に採用された上限
    max_depth: int
    #: **訪問ノード数の予算。** hairball防止をAPI側で保証する(仕様§9.1)
    visit_budget: int
    #: 実際に訪問したノード数
    visited: int
    #: 実際に探索が到達した深さ
    searched_depth: int
    #: **予算を使い切った。** 真なら「見つからなかった」であって「無い」ではない
    budget_exhausted: bool
    #: **max_depthに達して打ち切った。** 同上
    depth_limited: bool
    #: **1ノードあたりの分岐数の上限**(近傍サブグラフと同じ理由。ハブで
    #: 探索が破綻するのを防ぐ)
    fanout_limit: int
    #: **分岐数の上限で隣接を切ったノードがあった。**
    #: 真なら探索は不完全であり、`exhaustive`は真になれない ——
    #: **切ったのに「尽くした」と言うのは嘘である**
    fanout_truncated: bool
    #: **探索を尽くした**(予算内・深さ内で到達可能な全ノードを見た)。
    #: **`found=False`かつ`exhaustive=True`のときだけ「経路は存在しない」を
    #: 意味する** —— ただし「この深さ・この予算の中では」という限定は残る
    exhaustive: bool
    #: **辺の向きを無視して探索した**ことを明示する。実データでは
    #: `UnresolvedReference`が出る辺771本・入る辺0本、`Expenditure`の
    #: `project`は法令↔法人の経路にとって「逆向き」——**向きを守って
    #: 探索するとほとんど何も見つからない**(controller実測)。
    #: 常に`true`だが、応答に出すことで消費者が向きを誤解しないようにする
    undirected: bool


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
    #: 常にlistにする(単値/多値で応答の形が変わると消費者側の分岐が増える)。
    #:
    #: **訂正(裁定B82(4a)。以前は`dict[str, list[str]]`で出典が無かった)**:
    #: 以前のこの型は値を素の`str`で持っており、どの名前付きグラフ由来かが
    #: 分からなかった——`relationships`には出典が付くのに`attributes`には
    #: 付かない、仕様§9.2「全表示要素に一次資料へのリンクと取得日時を出す」
    #: の未達だった(D-5の実装者が発見)。**値を`AttributeValue`
    #: (値+出典グラフキーの一覧)にすることで直した。**
    attributes: dict[str, list[AttributeValue]]
    #: **関係の一覧を型別にグループ化**(D-3ブリーフ)。キーは「相手側
    #: エンティティ」の型のローカル名(例: "Law"・"Ministry"・"Expenditure")。
    #: 属性には現れない、関係固有の軸なので、属性のグループ化とは別に持つ
    relationships: dict[str, list[Relationship]]
    #: **名前付きグラフのキー → その出典**(D-4の裁定2で正規化した)。
    #: `Relationship.graph` はこのマップのキーである。
    #:
    #: **この応答に現れるすべての `Relationship.graph` がここに存在することを
    #: 保証する**(消費者はキーの不在を扱わなくてよい)——
    #: 保証はテストで縛る(`tests/test_api_entity.py`)。
    graphs: dict[str, Provenance]
    #: 実際に採用された上限
    relationships_limit: int
    #: **黙って切らない**(SearchResponse.truncatedと同じ理由)
    relationships_truncated: bool
