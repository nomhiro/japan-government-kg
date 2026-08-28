"""起動時のキャッシュ温め。

**裁定B60(このモジュールの現版の設計)**: 温める領域は、検索
(`queries.search_entities`)が実際に走る領域——`skos:prefLabel`を
`_SEARCHABLE_TYPES`全体で横断して読む索引領域——である。**手書きのSPARQLを
ここに置かない。** `search_entities`自身を呼ぶことで、温める領域を実際の
コード経路から導出する形にする——手書きのSPARQLをここに置くのは、
このプロジェクトの再発欠陥1「導出すべき値を手書きしている」の別の衣装に
なる(結合テスト: `tests/test_api_warmup.py`が、この関数が実際に
`search_entities`を経由していること——spyしたclientに届くクエリが
`skos:prefLabel`と`ORDER BY`を含むこと——を検査し、手書きのSPARQLに
戻されたら落ちる形にしている)。

**このモジュールの旧版の誤り(裁定B59の実測がB60で確定させた)**: 以前は
ここに「支出(`budget:Expenditure`)の索引領域をページインする」という
手書きのSPARQL(旧`_warmup_query`)を置いていた。これはD-3ブリーフの
指示(cq06で観測された領域を温める)をそのまま実装した結果だったが、
**cq06が触る領域とAPIの2エンドポイントが実際に触る領域は別だった**——
`/search`・`/entity/{id}`のどちらも`budget:Expenditure`/`budget:project`/
`budget:recipientMatchCategory`を一度も問い合わせない。実測(controller。
`docs/measurements-phase1.md`・進行台帳B60参照)は、旧版の温めが短時間で
終わった一方、その直後の最初の検索が長時間かかったことを示した——
温めたはずの領域と検索が実際に触る領域が違っていたことの直接的な証拠。

**語の選び方は温める被覆に影響しない(裁定B60)**: `_build_search_query`
(`queries.py`)は`ORDER BY ?label ?entity`を持つため、LIMITの前に
FILTER済み解集合の計算が強制され、どの検索語であってもラベル領域
(`_SEARCHABLE_TYPES`全体の`skos:prefLabel`)が全走査される。**ただし
この前提は将来変わりうる**: `ORDER BY`を外すか、全文索引(Jena text/
Lucene。`queries.py`の`search_entities`docstring参照)を入れると、
この温めの被覆根拠は失われる——そのときはこのモジュールも見直しが必要。

**温めはコストを消さない、起動時に移すだけである(裁定B61)。** ラベル
領域の初回読みが遅ければ、この関数も起動時にその分だけ遅くなる——
多くのプラットフォームの起動(readiness)プローブがそれを待たず
コンテナを再起動ループに入れる恐れが残る。**「これで初回リクエストが
速くなる」とは言わない。** 正確には「エンドポイントが実際に走る領域を、
コード経路から導出して温める」までである。索引の置き場所(バインド
マウント越しか、実ローカルFSか)というプラットフォーム側の解決は
D-6の課題(進行台帳B61参照)。

**失敗しても起動を止めない(ログに警告して続行)。** Fuseki自体がまだ
起動していない/一時的に落ちている状態で温め処理が失敗しても、他の
エンドポイントの準備ができないほど深刻な障害ではない——「クラッシュか
継続か」の正確な閾値はD-5(プラットフォーム選定)のreadiness probe設計
の話であり、D-3は「土台」としてこの緩い側の挙動を選ぶ
(advisorレビュー: この判断はD-3の責務内で完結する。裁定B55当時からの
判断を継続)。
"""
import logging
import time

from jgkg.api.kgclient import KGClient
from jgkg.api.queries import search_entities

logger = logging.getLogger(__name__)

#: 温めに使う検索語。**空文字列を選んだ理由**: `queries._build_search_query`の
#: `FILTER(CONTAINS(...))`は空文字列に対して常に真になる(SPARQLの
#: `CONTAINS(x, "")`はどんな`x`に対しても真)ため、実データに特定の語
#: (例:「厚生」)が存在するという仮定を置かずに済む。**この選択は被覆に
#: 影響しない**(上のモジュールdocstring・裁定B60参照): `ORDER BY`が
#: LIMIT前の全件評価を強制するため、どの語を選んでもラベル領域は同じだけ
#: 全走査される。
_WARMUP_SEARCH_TERM = ""


def warm_up(client: KGClient, base_uri: str) -> float | None:
    """検索(`search_entities`)が実際に走る索引領域を温める(裁定B60)。

    手書きのSPARQLではなく`search_entities`自身を呼ぶ——温める領域を
    ハードコードすると、このモジュールのdocstringに書いたのと同じずれ
    (cq06の領域とAPIが実際に触る領域の混同)が再発しうる。実際のコード
    経路を1本通すことで、`/search`の実装が変わればこの温めも自動的に
    追随する。

    戻り値は所要秒数(成功時)。失敗時は`None`を返し、警告をログに残すだけで
    例外を外に伝えない(呼び出し側=startupフックを落とさない)。
    """
    started = time.monotonic()
    try:
        search_entities(client, base_uri, _WARMUP_SEARCH_TERM, 1)
    except Exception:
        logger.warning(
            "起動時のキャッシュ温めに失敗した(裁定B60対策)。"
            "検索が読むラベル領域がコールドのまま最初のリクエストを"
            "受ける可能性がある。",
            exc_info=True,
        )
        return None
    elapsed = time.monotonic() - started
    logger.info("起動時のキャッシュ温めが完了した(%.3f秒。裁定B60対策)。", elapsed)
    return elapsed
