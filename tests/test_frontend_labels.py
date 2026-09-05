"""`jgkg.frontend_labels`(裁定B78の表示名をフロントエンド向けに抜き出す)のテスト。"""
from pathlib import Path

from jgkg.frontend_labels import extract_labels

#: **実際のベースURIを使う(`https://example.test/...`にしない)。**
#: `jgkg.base_uri.find_inconsistencies`は`/def/`等、設計書§4.2のURI
#: パターンを持つ文字列を見つけたら、それが許可された外部ホスト
#: (`example.test`等)であっても「古いドメインの残骸」として無条件に
#: 検出する(パスの形そのものが「これは我々のIRIのはず」という強い
#: シグナルだからで、ホストの許可リストより優先される)。テスト固有の
#: ダミードメインではなく実際のベースURIを使えば、この検査に正しく
#: 一致し、`uv run python -m jgkg.base_uri --check`が偽陽性を出さない
#: (`tests/test_site_verify.py`の既存の合成グラフも同じ理由で実URIを使う)。
_TTL = """
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <https://jgkg.norr-tech.com/def/core#> .

ex:Law a owl:Class ;
    dcterms:title "法令"@ja ;
    skos:definition "根拠となる法律・政令等" .

ex:basisLaw a owl:ObjectProperty ;
    dcterms:title "根拠法令"@ja .

ex:budgetAmount a owl:DatatypeProperty ;
    dcterms:title "予算額"@ja .

# クラスでも述語でもない主語(オントロジー自身)。titleがあっても対象外。
<https://jgkg.norr-tech.com/def/core.owl.ttl> a owl:Ontology ;
    dcterms:title "テスト用オントロジー"@ja .

# titleが無いクラス。抜けても無害(空の名前空間問い合わせと同じ)。
ex:UntranslatedThing a owl:Class ;
    skos:definition "まだ表示名が無い" .

# 裁定B82(4b): 列挙型の許容値。述語IRI→(rdfs:range)→列挙型IRI→
# (rdfs:subClassOfの逆向き)→許容値IRIの経路をテストする。
ex:recipientMatchCategory a owl:ObjectProperty ;
    dcterms:title "支払先の照合区分"@ja ;
    rdfs:range ex:RecipientMatchCategoryEnum .

<https://jgkg.norr-tech.com/def/core#RecipientMatchCategoryEnum/resolved> a owl:Class ;
    rdfs:subClassOf ex:RecipientMatchCategoryEnum ;
    dcterms:title "特定できた"@ja .

# titleが無い許容値。抜けても無害(enumValuesのキー自体が現れない。他の
# クラス/述語と同じ「titleが無ければ現れない」方針をenumValuesにも適用)。
<https://jgkg.norr-tech.com/def/core#RecipientMatchCategoryEnum/bundled> a owl:Class ;
    rdfs:subClassOf ex:RecipientMatchCategoryEnum .

# 通常の継承関係(列挙型ではない)。titleを持つがローカル名に"/"を含まない
# ——ここがenumValuesとtypesを分けるフィルタの主張の核心(区別を誤ると
# 通常のサブクラスまでenumValuesに、あるいは許容値がtypesに紛れ込む)。
ex:recipient a owl:ObjectProperty ;
    rdfs:range ex:Agent .

ex:Organization a owl:Class ;
    dcterms:title "組織"@ja ;
    rdfs:subClassOf ex:Agent .
"""


def _write(tmp_path: Path) -> Path:
    p = tmp_path / "core.owl.ttl"
    p.write_text(_TTL, encoding="utf-8")
    return p


def test_extract_labels_separates_classes_and_properties(tmp_path):
    labels = extract_labels(_write(tmp_path))
    assert labels["types"] == {"Law": "法令", "Organization": "組織"}
    assert labels["predicates"] == {
        "basisLaw": "根拠法令",
        "budgetAmount": "予算額",
        "recipientMatchCategory": "支払先の照合区分",
    }


def test_extract_labels_excludes_the_ontology_subject_itself(tmp_path):
    """`owl:Ontology`(ファイル自身のIRI)は`dcterms:title`を持つが、

    `_local_name`(queries.py)が返す型名・述語名の対象ではないので除く。
    何があれば落ちるか: 型フィルタを外すと、"types"に
    "https://jgkg.norr-tech.com/def/core.owl.ttl"のようなURL全体がキーとして
    紛れ込む(そのIRIは"#"を含まないため`rsplit("#")`でも防げるが、
    型フィルタ自体が効いていることをここで固定する)。
    """
    labels = extract_labels(_write(tmp_path))
    assert "テスト用オントロジー" not in labels["types"].values()
    assert "テスト用オントロジー" not in labels["predicates"].values()


def test_extract_labels_omits_classes_without_a_title(tmp_path):
    """表示名がまだ無い用語(裁定B78の対象外)は、キー自体が現れないこと

    ——空文字列や`None`を持たせない(消費者に「キーがあるが空」という
    余分な分岐を作らせない)。
    """
    labels = extract_labels(_write(tmp_path))
    assert "UntranslatedThing" not in labels["types"]


# =============================================================================
# 列挙型の許容値の表示名(裁定B82(4b))
# =============================================================================


def test_extract_labels_resolves_enum_permissible_values_via_rdfs_range_and_subclassof(tmp_path):
    """述語IRI→(rdfs:range)→列挙型IRI→(rdfs:subClassOfの逆向き)→許容値IRI

    の経路で`enumValues`が引けること。キーは述語のローカル名
    (`recipientMatchCategory`)、値は許容値のローカル名(`resolved`)。
    """
    labels = extract_labels(_write(tmp_path))
    assert labels["enumValues"] == {"recipientMatchCategory": {"resolved": "特定できた"}}


def test_extract_labels_omits_enum_permissible_values_without_a_title(tmp_path):
    """`bundled`(fixtureでtitleを持たせていない許容値)がキーとして現れないこと

    ——`types`/`predicates`と同じ「titleが無ければ現れない」方針。
    """
    labels = extract_labels(_write(tmp_path))
    assert "bundled" not in labels["enumValues"]["recipientMatchCategory"]


def test_extract_labels_does_not_treat_ordinary_subclassing_as_enum_values(tmp_path):
    """通常の継承(`ex:Organization rdfs:subClassOf ex:Agent`)を

    列挙型の許容値と誤認しないこと。`ex:recipient`は`ex:Agent`を範囲に
    持つが、`ex:Agent`のサブクラスは列挙値の形(ローカル名に"/"を含む)を
    していないので、`enumValues`に"recipient"キーが現れてはならない。

    何があれば落ちるか: `_enum_value_labels`が許容値IRIの形("/"を含む)を
    確認せずに`rdfs:subClassOf`を辿ると、`Organization`(通常のクラス)が
    "recipient"の許容値として紛れ込む。
    """
    labels = extract_labels(_write(tmp_path))
    assert "recipient" not in labels["enumValues"]


def test_extract_labels_excludes_enum_permissible_values_from_types(tmp_path):
    """列挙型の許容値(`a owl:Class`。裁定B66)は"types"に入らないこと。

    何があれば落ちるか: "types"のフィルタから"/"の除外を外すと、
    "RecipientMatchCategoryEnum/resolved"のような、`queries.py`の
    `_local_name`が絶対に返さない形のキーが"types"に紛れ込む
    (実際にこの欠陥を作って確認した——修正前は`types=17`件になった)。
    """
    labels = extract_labels(_write(tmp_path))
    assert not any("/" in key for key in labels["types"])
    assert "RecipientMatchCategoryEnum/resolved" not in labels["types"]


def test_extract_labels_matches_the_local_name_derivation_used_by_the_api():
    """実際の生成物(`schema/generated/all.owl.ttl`)に対して、

    `queries.py`の`_local_name`("#"で切る)と同じキーが取れることを確認する
    ——手書きの対応表ではなく、同じ切り出し方で両者が必ず一致することの
    実データでの確認。
    """
    repo_root = Path(__file__).resolve().parent.parent
    all_owl = repo_root / "schema" / "generated" / "all.owl.ttl"
    labels = extract_labels(all_owl)
    # D-3が実際に返す型・述語のうち代表的なもの(queries.pyのローカル名と
    # 同じ文字列)が引けることを確認する。
    assert labels["types"]["BudgetProject"] == "予算事業"
    assert labels["types"]["LawRevision"] == "法令の改正版"
    assert labels["predicates"]["basisLaw"] == "根拠法令"
    assert labels["predicates"]["jurisdiction"] == "所管府省"


def test_extract_labels_enum_values_from_real_data_has_exactly_the_two_predicates_and_eight_values():
    """実際の生成物に対して、`enumValues`が「1件以上」ではなく件数まで一致すること(裁定B82(4b))。

    **件数の由来**: `RecipientMatchCategoryEnum`/`UnresolvedReasonEnum`の
    許容値はそれぞれ`schema/budget.yaml`/`schema/core.yaml`に4件ずつ
    定義されている(このテストを書くにあたって数え直して確認した——
    controllerのブリーフが挙げた「8件」を転記していない)。

    「1件以上」で通る検査にしない理由: 対象の述語・列挙型が両方とも
    1個のときに、実装が片方しか処理しないバグや、値を1つ取り落とす
    バグがあっても「1件以上」は素通りする。件数を厳密に固定することで、
    どちらの欠陥も検出できる。
    """
    repo_root = Path(__file__).resolve().parent.parent
    all_owl = repo_root / "schema" / "generated" / "all.owl.ttl"
    labels = extract_labels(all_owl)

    assert set(labels["enumValues"]) == {"recipientMatchCategory", "unresolved_reason"}
    assert len(labels["enumValues"]["recipientMatchCategory"]) == 4
    assert len(labels["enumValues"]["unresolved_reason"]) == 4
    total = sum(len(v) for v in labels["enumValues"].values())
    assert total == 8, f"許容値の表示名は合計8件のはずが{total}件だった: {labels['enumValues']}"

    # 代表値。ブリーフの例をそのまま採用した2件(2026-09-05付ブリーフ)
    assert labels["enumValues"]["recipientMatchCategory"]["resolved"] == "法人番号で特定できた"
    assert labels["enumValues"]["unresolved_reason"]["AMBIGUOUS"] == "候補が複数あって決められない"
