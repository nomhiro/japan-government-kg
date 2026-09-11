"""FastAPI app本体。SPARQLを外に出さず、用途別のエンドポイントだけを公開する(仕様§9.1)。

**SPARQLを直接受け取る経路を作らない。** `/search`・`/entity/{id}`・
`/neighborhood/{id}`・`/path`(仕様§9.1が定める4用途)に加えて、
E-2(裁定B92)で`/chat`を足した——`/chat`もSPARQLをクライアントから
受け取らない。LLMに渡す道具(`chat_tools.py`)は境界付きの既存4関数+
`get_ontology`(ファイル読み取り)に限られ、任意のSPARQLをLLM自身にも
書かせない(裁定B92裁定1)。**ルートの集合はこの5本で閉じている**
——`tests/test_api_app.py`の`test_no_route_accepts_a_raw_sparql_query`が
この集合を固定する。

**`create_app()`が唯一の入口。** `client`を1回だけ束縛してappを作る
(`kgclient.KGClient`のdocstring参照)。ルートも起動時の温め処理
(`warmup.warm_up`)も、同じ束縛済みclientを見る——設定から都度新しい
clientを作る設計にすると、温め処理だけが本物のFusekiへ接続しようとして
テスト(`tests/conftest.py`のネットワーク遮断)に引っかかる、という
食い違いが起きる(advisorレビューで指摘され、この形に決めた)。

**`chat_model`は省略できる(既定`None`)。** `/chat`以外の既存4ルートを
検証するテスト(`test_api_app.py`・`test_api_graph.py`等)は、チャット機能に
関心が無い——`chat_model`を渡さないと`/chat`は503(チャットは設定されて
いない)を返すだけで、他のルートの挙動には影響しない。
"""
from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import unquote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from jgkg.api.chat import (
    ChatService,
    DailyTokenBudget,
    DailyTokenBudgetExceeded,
    RateLimiter,
    RateLimitExceeded,
)
from jgkg.api.kgclient import KGClient, RemoteKGClient
from jgkg.api.llm import ChatModel
from jgkg.api.models import (
    ChatRequest,
    ChatResponse,
    EntityDetailResponse,
    NeighborhoodResponse,
    OverviewResponse,
    PathResponse,
    SearchResponse,
)
from jgkg.api.overview import build_overview
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
from jgkg.api.readiness import wait_for_triplestore_ready
from jgkg.api.warmup import warm_up
from jgkg.config import get_settings

logger = logging.getLogger(__name__)


def create_app(
    client: KGClient,
    base_uri: str | None = None,
    *,
    chat_model: ChatModel | None = None,
    generated_dir: Path | None = None,
    queries_dir: Path | None = None,
) -> FastAPI:
    """`client`(本番=`RemoteKGClient`、テスト=`RdflibKGClient`)を束縛してappを作る。

    `base_uri`を省略すると`get_settings().base_uri`(設定の既定値)を使う——
    `emit.py`/`queries.py`と同じ、ベースURIを直書きしない経路。

    `chat_model`(E-2。裁定B92)を省略すると`/chat`は503を返す
    (このモジュールdocstring参照)。`generated_dir`を省略すると
    `Path("schema/generated")`(`pipeline.py`の`SHAPES_DIR`と同じ既定)。

    `queries_dir`(F-2。裁定B103)を省略すると`Path("queries/cq")`
    (`scripts/run_cq.py`の`DEFAULT_QUERY_DIR`・既存CQテストの`CQ_DIR`と
    同じ既定)。`/overview`が起動時に読むCQファイルの場所である。
    """
    resolved_base_uri = base_uri or get_settings().base_uri
    resolved_generated_dir = generated_dir or Path("schema/generated")
    resolved_queries_dir = queries_dir or Path("queries/cq")
    settings = get_settings()
    chat_service = (
        ChatService(
            kg_client=client,
            base_uri=resolved_base_uri,
            generated_dir=resolved_generated_dir,
            chat_model=chat_model,
            tool_call_limit=settings.chat_tool_call_limit,
            max_completion_tokens=settings.chat_max_completion_tokens,
            rate_limiter=RateLimiter(settings.chat_rate_limit_per_minute),
            daily_budget=DailyTokenBudget(settings.chat_daily_token_budget),
            neighborhood_node_limit=settings.chat_neighborhood_node_limit,
        )
        if chat_model is not None
        else None
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # **裁定B103追記3。`warm_up`/`build_overview`の前にトリプルストアの
        # 応答を待つ(上限付き)。** ACAには同一レプリカ内のコンテナ起動順序を
        # 指定する仕組みが無く、Fusekiが先に応答できる前提が崩れると
        # 両方が接続エラーで失敗し、再試行が無いまま`/overview`が永久に503に
        # なる(実測。`readiness.py`のモジュールdocstring参照)。ここでは
        # 戻り値を分岐に使わない——上限に達しても、後続の`warm_up`/
        # `build_overview`は今までどおり自分の`try`/`except`で失敗し503に
        # 落ちる(このモジュールは「待つ」ことだけをする。裁定B84の族:
        # 「まだ準備できていない」と「集約が失敗した」の2つの503を作らない)。
        wait_for_triplestore_ready(
            client,
            settings.overview_readiness_timeout_seconds,
            settings.overview_readiness_poll_interval_seconds,
        )
        # 裁定B55対策。失敗しても起動は続ける(warmup.pyのdocstring参照)
        warm_up(client, resolved_base_uri)
        # **第1層の集約を起動時に1回だけ計算する(裁定B103)。**
        # 索引が温まった後の方が速いので`warm_up`の後に呼ぶ。
        # 失敗しても起動は続ける——`/overview`が503を返すだけで、
        # 検索やエンティティ表示は影響を受けない。
        started = time.monotonic()
        try:
            app.state.overview = build_overview(client, resolved_base_uri, resolved_queries_dir)
        except Exception:
            logger.exception("第1層の集約に失敗した。/overview は503を返す")
            app.state.overview = None
        else:
            # **成功時も所要時間をログに残す(裁定D-15)。** 失敗時は
            # `logger.exception`があるのに成功時は何も出ないと、本番で
            # 「何秒かかったか」「そもそも走ったか」が分からない——
            # 裁定B103の設計は「起動時に1回払う」に立っており、この費用が
            # 実際にいくらだったかを運用側が確認できる必要がある
            # (Task 7がこれを実測する)。
            logger.info(
                "第1層の集約が完了した(%.3f秒。裁定B103対策)。",
                time.monotonic() - started,
            )
        yield

    app = FastAPI(title="Japan Government KG API", lifespan=lifespan)
    app.state.kg_client = client
    app.state.base_uri = resolved_base_uri

    # **CORSを全オリジンに開ける(D-5で追加)。** D-3/D-4はこのAPIを実装した
    # 時点でCORSヘッダを付けていなかった——ブラウザから直接呼ぶ経路
    # (このアプリ自身がその最初の消費者)が無かったため、抜けが露見して
    # いなかった。この4本のGETエンドポイントは認証も副作用も持たない
    # 読み取り専用の公開APIであり、`site.py`の`build_headers()`が
    # `/def/*`(公開オントロジー)に対して既に採っている「公共財として
    # 公開しているのでオリジンを絞る理由が無い」という判断をそのまま
    # 適用する。D-6b(配備先。本番のAPIのドメイン)は未決だが、CORSは
    # 配備先が決まる前に必要になる(このアプリがデプロイされた別オリジンから
    # APIを呼ぶため)——D-5の表示層が実際に機能するための追加であり、
    # 「表示だけを作る」の範囲を超える判断としてD-5報告に明記する。
    #
    # **`POST`を許可リストに足す(E-2。裁定B92)。** `/chat`はJSON本文の
    # POSTであり、`Content-Type: application/json`は「単純リクエスト」に
    # 該当しないため、ブラウザは実際のリクエストの前にpreflight(`OPTIONS`)
    # を送る——`allow_methods`が`["GET"]`のままだと、preflightの応答に
    # `POST`が含まれず、ブラウザが実リクエスト自体を送らずに握りつぶす。
    # **実ブラウザでチャット画面から送信ボタンを押して初めて発覚した**
    # (コンソールに`CORS policy`エラー。裁定B93の教訓——「描画された」は
    # 「動く」ではない。自動テストは`fastapi.testclient`を使い、実ブラウザの
    # CORS preflightを経由しないため、この欠陥を検出できない)。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.get("/overview", response_model=OverviewResponse)
    def overview() -> OverviewResponse:
        """トップページ第1層(裁定B103)。起動時に1回計算した値を返すだけ
        ——リクエストごとにCQを走らせない(`overview.py`のモジュール
        docstring参照)。

        `app.state.overview`が`None`なら**503**を返す。`/chat`が
        `chat_model`未設定のときに503を返すのと同じ作法(このモジュール
        docstring参照)——起動時の集約に失敗しても、他のエンドポイントの
        起動を妨げない設計の裏返しである。

        **`getattr`で守る(レビュー要修正14)。** `app.state.overview`を
        直接読むと、`lifespan`が走っていない(`with`を付けない
        `TestClient(app)`等)状態で`AttributeError`になり、意図した503
        ではなく500が返る——既存テストは全て`with`を使うので今は表に
        出ないが、`getattr(app.state, "overview", None)`にすれば
        lifespan未実行の状態でも意図した503に収束する。
        """
        if getattr(app.state, "overview", None) is None:
            raise HTTPException(
                status_code=503, detail="第1層の集約に失敗した(起動時のログ参照)"
            )
        return app.state.overview

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

    @app.post("/chat", response_model=ChatResponse)
    def chat(chat_request: ChatRequest, http_request: Request) -> ChatResponse:
        # **会話履歴を保存しない**(仕様§6.3。`ChatRequest.history`は
        # クライアントが送ってきたものをそのまま使い、サーバの状態に残さない)
        if chat_service is None:
            raise HTTPException(
                status_code=503, detail="チャットは設定されていない(chat_modelが未設定)"
            )
        client_ip = http_request.client.host if http_request.client else "unknown"
        try:
            return chat_service.handle_chat(chat_request, client_ip)
        except RateLimitExceeded as e:
            raise HTTPException(status_code=429, detail=str(e)) from e
        except DailyTokenBudgetExceeded as e:
            raise HTTPException(status_code=429, detail=str(e)) from e

    return app


def create_production_app() -> FastAPI:
    """実行用のエントリポイント(例: `uvicorn jgkg.api.app:create_production_app --factory`)。

    設定(`config.Settings.sparql_endpoint`)から`RemoteKGClient`を組み立てる。
    **モジュールレベルの`app = ...`を置かない**——importした時点でクライアントが
    生成されるのを避け、実際に起動されるまで何も作らない(D-6の起動経路が
    確定するまで、importの副作用を持たせない判断)。

    **`AzureFoundryChatModel`もここで初めて組み立てる。** `llm.py`のimportは
    遅延させている(`azure-identity`は`AzureFoundryChatModel.__init__`が
    必要になった時点でだけimportする)ため、このモジュール自体をimportする
    だけでは`azure-identity`の有無を問わない——`scripts/export-openapi.py`
    (`app.openapi()`だけを呼ぶ。ネットワーク不要)が言う「起動しない」性質を
    ここでも保つ。
    """
    from jgkg.api.llm import AzureFoundryChatModel

    settings = get_settings()
    client = RemoteKGClient(settings.sparql_endpoint)
    chat_model = AzureFoundryChatModel(
        settings.aoai_endpoint, settings.aoai_deployment, settings.aoai_api_version
    )
    return create_app(client, base_uri=settings.base_uri, chat_model=chat_model)
