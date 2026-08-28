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

from fastapi import FastAPI, HTTPException, Query

from jgkg.api.kgclient import KGClient, RemoteKGClient
from jgkg.api.models import EntityDetailResponse, SearchResponse
from jgkg.api.queries import (
    ENTITY_RELATIONSHIPS_DEFAULT_LIMIT,
    ENTITY_RELATIONSHIPS_MAX_LIMIT,
    SEARCH_DEFAULT_LIMIT,
    SEARCH_MAX_LIMIT,
    get_entity_detail,
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
