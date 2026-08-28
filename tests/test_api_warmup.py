"""起動時のキャッシュ温め(`jgkg.api.warmup`)のテスト。裁定B60対策。

ここでは`KGClient`の最小限のスパイ実装を使う(rdflib/HTTPどちらの実装にも
依存しない、`warm_up`自身のロジックの検証)。`search_entities`が要求する
変数(`entity`・`type`・`label`等)を一切束縛しない空の結果を返すだけで
十分——`search_entities`は0件の結果を素通しする(`tests/test_api_search.py`
の`test_search_no_match_returns_empty_results_not_error`と同じ前提)ため、
このスパイは「`warm_up`が実際にどのSPARQLをclientに渡したか」だけを
記録すればよい。
"""
from jgkg.api.warmup import warm_up

BASE = "https://jgkg.norr-tech.com"


class _SpyClient:
    def __init__(self, *, fail: bool = False):
        self.queries: list[str] = []
        self._fail = fail

    def query(self, sparql: str):
        self.queries.append(sparql)
        if self._fail:
            raise RuntimeError("Fusekiに接続できない(テスト用の故意の失敗)")
        return []


def test_warm_up_runs_search_entities_and_reports_elapsed_time():
    """裁定B60: 温める領域は検索(`search_entities`)が実際に走る領域——
    `skos:prefLabel`を全型横断で読むラベル領域——である。`warm_up`が
    手書きのSPARQL(旧`_warmup_query`。`budget:Expenditure`を温めていたが
    どのエンドポイントもその領域を読まない)ではなく`search_entities`
    自身を経由することを、そのクエリが実際に持つ特徴(`skos:prefLabel`・
    `ORDER BY`)で検査する——**手書きのSPARQLに戻されたら落ちる形**
    (`ORDER BY`はLIMIT前の全件評価を強制する`_build_search_query`固有の
    構造で、旧`_warmup_query`には無かった)。
    """
    client = _SpyClient()
    elapsed = warm_up(client, BASE)
    assert elapsed is not None
    assert elapsed >= 0
    assert len(client.queries) == 1
    query = client.queries[0]
    assert "skos:prefLabel" in query, (
        f"search_entitiesが実際に読む述語に触れていない(手書きのSPARQLに戻っている疑い): {query}"
    )
    assert "ORDER BY" in query, (
        f"search_entities固有の全件評価(ORDER BY)を経由していない: {query}"
    )
    assert "budget:Expenditure" not in query, (
        "旧版(裁定B59以前)が温めていた支出領域はどのエンドポイントも読まない"
        "(裁定B60)。手書きのSPARQLが残っている疑い"
    )
    assert BASE in query, "ベースURIを直書きせず設定から組み立てていることの確認"


def test_warm_up_swallows_errors_and_does_not_crash_startup():
    """壊し確認: Fusekiがまだ起動していない等で温めクエリが失敗しても、
    例外を外に伝えない(起動シーケンス自体は継続する)。
    """
    client = _SpyClient(fail=True)
    elapsed = warm_up(client, BASE)
    assert elapsed is None
    assert len(client.queries) == 1, "クエリを試みたことは確認する(何もしていないのではない)"
