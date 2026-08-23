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


# =============================================================================
# 裁定B4: 自名前空間へのsh:classを除去してreference-classes.jsonへ移す
# =============================================================================

BASE = "http://example.test"
JURISDICTION = URIRef(f"{BASE}/def/law#jurisdiction")
ORGANIZATION = URIRef(f"{BASE}/def/org#Organization")


def test_extract_reference_classes_strips_self_namespace_class_and_records_it():
    g = Graph()
    shape = BNode()
    g.add((shape, SH.path, JURISDICTION))
    g.add((shape, SH["class"], ORGANIZATION))
    g.add((shape, SH.nodeKind, SH.IRI))

    entries = schema_lang.extract_reference_classes(g, BASE)

    assert entries == [
        {"path": str(JURISDICTION), "expected_class": str(ORGANIZATION)}
    ]
    assert (shape, SH["class"], ORGANIZATION) not in g, "sh:classが除去されていない"
    assert (shape, SH.nodeKind, SH.IRI) in g, (
        "sh:nodeKindは値がIRIであることの検証として残すべきなのに消えている"
    )
    assert (shape, SH.path, JURISDICTION) in g, "sh:pathまで消してしまっている"


def test_extract_reference_classes_leaves_external_vocabulary_untouched():
    """自分のベースURI配下でないクラスへの sh:class は対象外(将来 prov: 等を
    参照するようになったとき、無条件に全部剥がして検証を失わないため)。

    テスト用ダミーホストは `example.test`(RFC 2606予約名。
    `jgkg.base_uri` の許可リストにあるので、この行自体がベースURI一致検査を
    通る)を使う。"""
    g = Graph()
    shape = BNode()
    path = URIRef(f"{BASE}/def/law#author")
    external = URIRef("http://example.test/external-vocab#Agent")
    g.add((shape, SH.path, path))
    g.add((shape, SH["class"], external))

    entries = schema_lang.extract_reference_classes(g, BASE)

    assert entries == []
    assert (shape, SH["class"], external) in g, "外部語彙へのsh:classまで消してしまった"


def test_extract_reference_classes_dedupes_pairs_repeated_across_shapes():
    """同じ (path, expected_class) の対が複数のNodeShapeに現れても1件にまとめる。

    `core:involves_agent` → `core:Agent` は複数のクラス(Event等)のNodeShapeに
    現れる実例がある。ファイル内で2回出ても reference-classes.json には1件だけ
    書くべきで、単純にリストへ append すると重複が残る。
    """
    g = Graph()
    involves_agent = URIRef(f"{BASE}/def/core#involves_agent")
    agent = URIRef(f"{BASE}/def/core#Agent")
    for _ in range(2):
        shape = BNode()
        g.add((shape, SH.path, involves_agent))
        g.add((shape, SH["class"], agent))

    entries = schema_lang.extract_reference_classes(g, BASE)

    assert entries == [{"path": str(involves_agent), "expected_class": str(agent)}]


def test_extract_reference_classes_sorts_entries_by_path():
    g = Graph()
    b_shape, a_shape = BNode(), BNode()
    b_path = URIRef(f"{BASE}/def/law#zzz")
    a_path = URIRef(f"{BASE}/def/law#aaa")
    cls = ORGANIZATION
    g.add((b_shape, SH.path, b_path))
    g.add((b_shape, SH["class"], cls))
    g.add((a_shape, SH.path, a_path))
    g.add((a_shape, SH["class"], cls))

    entries = schema_lang.extract_reference_classes(g, BASE)

    assert [e["path"] for e in entries] == [str(a_path), str(b_path)]


def test_extract_reference_classes_raises_when_sh_class_has_no_sh_path():
    """`sh:path`の無い`sh:class`は想定していない形なので、黙って無視せず例外にする
    (抽出漏れが静かに残ることを防ぐ、設計書§8.2と同じ思想)。"""
    g = Graph()
    shape = BNode()
    g.add((shape, SH["class"], ORGANIZATION))

    with pytest.raises(ValueError, match="sh:path"):
        schema_lang.extract_reference_classes(g, BASE)
