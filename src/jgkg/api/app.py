"""FastAPI app本体。SPARQLを外に出さず、用途別のエンドポイントだけを公開する(仕様§9.1)。

**SPARQLを受け取る経路を作らない。** `/search`・`/entity/{id}`以外のルートは
無い——D-3ブリーフが明示的に禁じている「公開SPARQL」をここに作り込まない
ことを、ルート定義がこの2本だけであることそのもので示す。

**`create_app()`が唯一の入口。** `client`を1回だけ束縛してappを作る
(`kgclient.KGClient`のdocstring参照)。ルートも起動時の温め処理
(`warmup.warm_up`)も、同じ束縛済みclientを見る——設定から都度新しい
clientを作る設計にすると、温め処理だけが本物のFusekiへ接続しようとして
テスト(`tests/conftest.py`のネットワーク遮断)に引っかかる、という
食い違いが起きる(advisorレビューで指摘され、この形に決めた)。
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Query

from jgkg.api.kgclient import KGClient, RemoteKGClient
from jgkg.api.models import (
    EntityDetailResponse,
    NeighborhoodResponse,
    PathResponse,
    SearchResponse,
)
from jgkg.api.queries import (
    ENTITY_RELATIONSHIPS_DEFAULT_LIMIT,
    ENTITY_RELATIONSHIPS_MAX_LIMIT,
    NEIGHBORHOOD_DEFAULT_DEPTH,
    NEIGHBORHOOD_DEFAULT_EDGE_LIMIT,
    NEIGHBORHOOD_DEFAULT_FANOUT_LIMIT,
    NEIGHBORHOOD_DEFAULT_NODE_LIMIT,
    NEIGHBORHOOD_MAX_DEPTH,
    NEIGHBORHOOD_MAX_EDGE_LIMIT,
    NEIGHBORHOOD_MAX_FANOUT_LIMIT,
    NEIGHBORHOOD_MAX_NODE_LIMIT,
    PATH_DEFAULT_FANOUT_LIMIT,
    PATH_DEFAULT_MAX_DEPTH,
    PATH_DEFAULT_VISIT_BUDGET,
    PATH_MAX_FANOUT_LIMIT,
    PATH_MAX_MAX_DEPTH,
    PATH_MAX_VISIT_BUDGET,
    SEARCH_DEFAULT_LIMIT,
    SEARCH_MAX_LIMIT,
    find_path,
    get_entity_detail,
    get_neighborhood,
    search_entities,
)
from jgkg.api.warmup import warm_up
from jgkg.config import get_settings


def create_app(client: KGClient, base_uri: str | None = None) -> FastAPI:
    """`client`(本番=`RemoteKGClient`、テスト=`RdflibKGClient`)を束縛してappを作る。

    `base_uri`を省略すると`get_settings().base_uri`(設定の既定値)を使う——
    `emit.py`/`queries.py`と同じ、ベースURIを直書きしない経路。
    """
    resolved_base_uri = base_uri or get_settings().base_uri

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # 裁定B55対策。失敗しても起動は続ける(warmup.pyのdocstring参照)
        warm_up(client, resolved_base_uri)
        yield

    app = FastAPI(title="Japan Government KG API", lifespan=lifespan)
    app.state.kg_client = client
    app.state.base_uri = resolved_base_uri

    @app.get("/search", response_model=SearchResponse)
    def search(
        q: str = Query(
            ..., min_length=1, max_length=200, description="検索語(部分一致・大文字小文字を無視)"
        ),
        limit: int = Query(
            SEARCH_DEFAULT_LIMIT,
            ge=1,
            le=SEARCH_MAX_LIMIT,
            description=f"既定{SEARCH_DEFAULT_LIMIT}・最大{SEARCH_MAX_LIMIT}。"
            "超過は422で拒否する(黙って丸めない。queries.pyのコメント参照)",
        ),
    ) -> SearchResponse:
        return search_entities(client, resolved_base_uri, q, limit)

    @app.get("/entity/{entity_id:path}", response_model=EntityDetailResponse)
    def entity_detail(
        entity_id: str,
        limit: int = Query(
            ENTITY_RELATIONSHIPS_DEFAULT_LIMIT,
            ge=1,
            le=ENTITY_RELATIONSHIPS_MAX_LIMIT,
            description=f"関係一覧の既定{ENTITY_RELATIONSHIPS_DEFAULT_LIMIT}・"
            f"最大{ENTITY_RELATIONSHIPS_MAX_LIMIT}。超過は422で拒否する",
        ),
    ) -> EntityDetailResponse:
        result = get_entity_detail(client, resolved_base_uri, entity_id, limit)
        if result is None:
            raise HTTPException(status_code=404, detail="エンティティが見つからない")
        return result

    @app.get("/neighborhood/{entity_id:path}", response_model=NeighborhoodResponse)
    def neighborhood(
        entity_id: str,
        depth: int = Query(
            NEIGHBORHOOD_DEFAULT_DEPTH,
            ge=1,
            le=NEIGHBORHOOD_MAX_DEPTH,
            description=f"深さ。既定{NEIGHBORHOOD_DEFAULT_DEPTH}・"
            f"最大{NEIGHBORHOOD_MAX_DEPTH}(仕様§9.1が「深さ1-2」と定めている)。"
            "超過は422で拒否する(黙って丸めない)",
        ),
        node_limit: int = Query(
            NEIGHBORHOOD_DEFAULT_NODE_LIMIT,
            ge=1,
            le=NEIGHBORHOOD_MAX_NODE_LIMIT,
            description=f"総ノード数の上限。既定{NEIGHBORHOOD_DEFAULT_NODE_LIMIT}・"
            f"最大{NEIGHBORHOOD_MAX_NODE_LIMIT}",
        ),
        edge_limit: int = Query(
            NEIGHBORHOOD_DEFAULT_EDGE_LIMIT,
            ge=1,
            le=NEIGHBORHOOD_MAX_EDGE_LIMIT,
            description=f"総エッジ数の上限。既定{NEIGHBORHOOD_DEFAULT_EDGE_LIMIT}・"
            f"最大{NEIGHBORHOOD_MAX_EDGE_LIMIT}",
        ),
        fanout_limit: int = Query(
            NEIGHBORHOOD_DEFAULT_FANOUT_LIMIT,
            ge=1,
            le=NEIGHBORHOOD_MAX_FANOUT_LIMIT,
            description="**1ノードあたりの分岐数の上限。** 総数の上限だけでは"
            "ハブ1個が予算を食い潰し、他の方向が1つも見えなくなる"
            f"(既定{NEIGHBORHOOD_DEFAULT_FANOUT_LIMIT}・"
            f"最大{NEIGHBORHOOD_MAX_FANOUT_LIMIT})",
        ),
    ) -> NeighborhoodResponse:
        result = get_neighborhood(
            client, resolved_base_uri, entity_id, depth, node_limit, edge_limit, fanout_limit
        )
        if result is None:
            raise HTTPException(status_code=404, detail="エンティティが見つからない")
        return result

    @app.get("/path", response_model=PathResponse)
    def path(
        # `from`はPythonの予約語なのでaliasで受ける
        from_id: str = Query(
            ..., alias="from", min_length=1, description="始点の`id_path`(`/entity/`と同じ形)"
        ),
        to_id: str = Query(
            ..., alias="to", min_length=1, description="終点の`id_path`(`/entity/`と同じ形)"
        ),
        max_depth: int = Query(
            PATH_DEFAULT_MAX_DEPTH,
            ge=1,
            le=PATH_MAX_MAX_DEPTH,
            description=f"探索の深さ。既定{PATH_DEFAULT_MAX_DEPTH}"
            "(法令→府省→事業→支出→法人の縦スライスが4ホップ)・"
            f"最大{PATH_MAX_MAX_DEPTH}。超過は422で拒否する",
        ),
        visit_budget: int = Query(
            PATH_DEFAULT_VISIT_BUDGET,
            ge=2,
            le=PATH_MAX_VISIT_BUDGET,
            description=f"訪問ノード数の予算。既定{PATH_DEFAULT_VISIT_BUDGET}・"
            f"最大{PATH_MAX_VISIT_BUDGET}。**使い切ったら`budget_exhausted`が真になり、"
            "`found=false`は「無い」ではなく「見つからなかった」を意味する**",
        ),
        fanout_limit: int = Query(
            PATH_DEFAULT_FANOUT_LIMIT,
            ge=1,
            le=PATH_MAX_FANOUT_LIMIT,
            description=f"1ノードあたりの分岐数の上限。既定{PATH_DEFAULT_FANOUT_LIMIT}・"
            f"最大{PATH_MAX_FANOUT_LIMIT}。**これが効くと探索は不完全になり"
            "`exhaustive`は真になれない**",
        ),
    ) -> PathResponse:
        # **クエリパラメータとパスセグメントでは、ハンドラに届く形が違う。**
        # controllerが実測(2026-08-30):
        #
        #   /p/{x:path} に生のまま補間        -> ハンドラは 20260101_令和 (デコード済み)
        #   /p/{x:path} に正しくエンコード    -> ハンドラは 20260101_令和 (同じ。二重デコード)
        #   /q?v= を params= で渡す           -> ハンドラは 20260101_%E4%BB%A4... (正準形のまま)
        #   /q?v= をURLに直接埋める           -> ハンドラは 20260101_令和 (デコード済み)
        #
        # **パスパラメータは二重にデコードされ、クエリパラメータは一重である。**
        # `canonical_iri`(kgclient.py)は「Starletteがデコードした形」を
        # 受け取って再エンコードする設計なので、正準形のまま届くクエリ経由では
        # **二重エンコードになって一致しない**(実際に `%` を含むノードで
        # 404になった。裁定B59・B69と同じ族が3層目に出た)。
        #
        # **ここで`unquote`を1回かけてパス経由と同じ形に正規化する。**
        # 下流は既存の1つの規則(`canonical_iri`)のままにできる ——
        # 経路ごとに別の組み立て方を持たせると、それこそがB59/B69の欠陥である。
        # 既に生のまま届いた場合(日本語)は`unquote`が何もしないので、
        # **どちらの送り方でも同じIRIに収束する。**
        result = find_path(
            client,
            resolved_base_uri,
            unquote(from_id),
            unquote(to_id),
            max_depth,
            visit_budget,
            fanout_limit,
        )
        if result is None:
            raise HTTPException(
                status_code=404, detail="始点または終点のエンティティが見つからない"
            )
        return result

    return app


def create_production_app() -> FastAPI:
    """実行用のエントリポイント(例: `uvicorn jgkg.api.app:create_production_app --factory`)。

    設定(`config.Settings.sparql_endpoint`)から`RemoteKGClient`を組み立てる。
    **モジュールレベルの`app = ...`を置かない**——importした時点でクライアントが
    生成されるのを避け、実際に起動されるまで何も作らない(D-6の起動経路が
    確定するまで、importの副作用を持たせない判断)。
    """
    settings = get_settings()
    client = RemoteKGClient(settings.sparql_endpoint)
    return create_app(client, base_uri=settings.base_uri)
