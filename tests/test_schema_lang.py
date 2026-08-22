"""schema_lang の正準化処理のテスト。

生成物の非決定性対策(§Task 12)で追加した `sort_rdf_lists` は許可リスト方式。
`sh:path` の連鎖パスのように順序そのものが意味を持つRDFリストを無条件に
ソートすると、生成物の意味を静かに反転させる(その後は決定性が保たれるため
テストもCIも検出できない)。ここでは許可リストの述語だけが正規化され、
未知の述語がリストを持っていたら例外になることを固定する。
"""
import pytest
from rdflib import BNode, Graph, URIRef
from rdflib.collection import Collection
from rdflib.namespace import SH

from jgkg import schema_lang

A = URIRef("http://example.test/a")
B = URIRef("http://example.test/b")
C = URIRef("http://example.test/c")
SHAPE = URIRef("http://example.test/Shape")


def test_sort_rdf_lists_normalizes_allow_listed_predicate_order():
    """sh:ignoredProperties は許可リストにあるので、順序を辞書順に正規化する。"""
    g = Graph()
    head = BNode()
    Collection(g, head, [B, A])  # 意図的に逆順で構築する
    g.add((SHAPE, SH.ignoredProperties, head))

    changed = schema_lang.sort_rdf_lists(g)

    assert changed == 1
    new_head = g.value(SHAPE, SH.ignoredProperties)
    assert list(Collection(g, new_head)) == [A, B]


def test_sort_rdf_lists_is_idempotent_when_already_sorted():
    """既に辞書順のリストは変更しない(changed==0)。"""
    g = Graph()
    head = BNode()
    Collection(g, head, [A, B])
    g.add((SHAPE, SH.ignoredProperties, head))

    changed = schema_lang.sort_rdf_lists(g)

    assert changed == 0
    assert list(Collection(g, head)) == [A, B]


def test_sort_rdf_lists_handles_longer_chains_without_false_positive():
    """3要素以上のリストでも、内部の rdf:rest ノードを誤って「未知の述語」と
    検知しない(検知すると、どんなリストも処理できなくなる)。"""
    g = Graph()
    head = BNode()
    Collection(g, head, [C, A, B])
    g.add((SHAPE, SH.ignoredProperties, head))

    changed = schema_lang.sort_rdf_lists(g)

    assert changed == 1
    new_head = g.value(SHAPE, SH.ignoredProperties)
    assert list(Collection(g, new_head)) == [A, B, C]


def test_sort_rdf_lists_raises_on_order_sensitive_predicate():
    """sh:path のような、順序に意味があるかもしれない未知の述語がリストを
    持っていたら例外にする(許可リストへの無条件追加を防ぐ安全策)。"""
    g = Graph()
    head = BNode()
    Collection(g, head, [A, B])
    g.add((SHAPE, SH.path, head))

    with pytest.raises(ValueError) as excinfo:
        schema_lang.sort_rdf_lists(g)

    assert str(SH.path) in str(excinfo.value)
