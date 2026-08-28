"""起動時のキャッシュ温め(裁定B55を受けた追加要求)。

**team-leadの指摘(B55)**: cq06の149.875秒/175.250秒はクエリの構造ではなく
ページフォルト(コールドキャッシュ)が原因だった——`budget:Expenditure`
(73,919件)の索引領域に**最初に**触るクエリが、その領域をページインする
コストを丸ごと払う。API層がこれを何もせず放置すると、**起動直後の最初の
利用者からのリクエストが実際に175秒待たされる**(多くのサーバーレスの
既定リクエストタイムアウト30〜60秒を超える)。

**これは「クエリを速くする」話ではなく「起動時に一度払う」話である**
(team-leadの言葉。docs/measurements-phase1.md §19.5参照)。サーバーレス
プラットフォームは通常、個々のリクエストより起動(readiness)の方に
寛容な時間を許すため、コストを支払うタイミングを「最初の利用者」から
「起動シーケンス自身」へ移すのが正しい対処になる。

**advisorレビュー: クエリはここに直接書く(`queries/cq/cq06*.rq`を実行時に
読まない)。** ファイルを読む経路にすると、「デプロイ用のコンテナに
`queries/`が同梱されるか」というD-6(配備)の問題をD-3が先取りして
引き受けてしまう。B55を引用しつつ、ここで完結した1本のクエリを持つ。

**失敗しても起動を止めない(ログに警告して続行)。** Fuseki自体がまだ
起動していない/一時的に落ちている状態で温め処理が失敗しても、他の
エンドポイントの準備ができないほど深刻な障害ではない——「クラッシュか
継続か」の正確な閾値はD-5(プラットフォーム選定)のreadiness probe設計
の話であり、D-3は「土台」としてこの緩い側の挙動を選ぶ
(advisorレビュー: この判断はD-3の責務内で完結する)。
"""
import logging
import time

from jgkg.api.kgclient import KGClient

logger = logging.getLogger(__name__)


def _warmup_query(base_uri: str) -> str:
    # **cq06(新)と同じ3つの述語に触れる。** `?e a budget:Expenditure`だけだと
    # 型索引の領域しかページインしない——cq06の175.250秒は
    # `budget:project`・`budget:recipientMatchCategory`の領域も含めて
    # 初めて発生した(裁定B55)。同じ3述語に触れることで、実際に問題を
    # 起こした領域を温める(advisorレビュー指摘)
    return f"""
PREFIX budget: <{base_uri}/def/budget#>
SELECT (COUNT(*) AS ?c) WHERE {{
  ?e a budget:Expenditure ;
     budget:project ?p ;
     budget:recipientMatchCategory ?c2 .
}}
"""


def warm_up(client: KGClient, base_uri: str) -> float | None:
    """支出(budget:Expenditure)の索引領域をページインする。

    戻り値は所要秒数(成功時)。失敗時は`None`を返し、警告をログに残すだけで
    例外を外に伝えない(呼び出し側=startupフックを落とさない)。
    """
    started = time.monotonic()
    try:
        client.query(_warmup_query(base_uri))
    except Exception:
        logger.warning(
            "起動時のキャッシュ温めに失敗した(裁定B55対策)。"
            "budget:Expenditureの索引がコールドのまま最初のリクエストを"
            "受ける可能性がある。",
            exc_info=True,
        )
        return None
    elapsed = time.monotonic() - started
    logger.info("起動時のキャッシュ温めが完了した(%.3f秒。裁定B55対策)。", elapsed)
    return elapsed
