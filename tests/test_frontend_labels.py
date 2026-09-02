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
"""


def _write(tmp_path: Path) -> Path:
    p = tmp_path / "core.owl.ttl"
    p.write_text(_TTL, encoding="utf-8")
    return p


def test_extract_labels_separates_classes_and_properties(tmp_path):
    labels = extract_labels(_write(tmp_path))
    assert labels["types"] == {"Law": "法令"}
    assert labels["predicates"] == {"basisLaw": "根拠法令", "budgetAmount": "予算額"}


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
