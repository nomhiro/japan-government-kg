"""起動時のキャッシュ温め(`jgkg.api.warmup`)のテスト。裁定B55対策。

ここでは`KGClient`の最小限のスパイ実装を使う(rdflib/HTTPどちらの実装にも
依存しない、`warm_up`自身のロジックの検証)。
"""
from jgkg.api.kgclient import Term
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
        return [{"c": Term(value="73919", kind="literal")}]


def test_warm_up_queries_the_expenditure_index_and_reports_elapsed_time():
    """裁定B55: cq06(budget:Expenditureの索引領域)を最初にページインする
    コストを、起動時にまとめて払う——そのクエリが実際に`budget:Expenditure`
    に触れることを確認する。
    """
    client = _SpyClient()
    elapsed = warm_up(client, BASE)
    assert elapsed is not None
    assert elapsed >= 0
    assert len(client.queries) == 1
    assert "budget:Expenditure" in client.queries[0]
    assert BASE in client.queries[0], "ベースURIを直書きせず設定から組み立てていることの確認"


def test_warm_up_swallows_errors_and_does_not_crash_startup():
    """壊し確認: Fusekiがまだ起動していない等で温めクエリが失敗しても、
    例外を外に伝えない(起動シーケンス自体は継続する)。
    """
    client = _SpyClient(fail=True)
    elapsed = warm_up(client, BASE)
    assert elapsed is None
    assert len(client.queries) == 1, "クエリを試みたことは確認する(何もしていないのではない)"
