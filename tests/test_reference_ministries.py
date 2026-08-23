"""府省名簿(data/reference/ministry-codes.csv)の拡張(計画B Task 5)。

3行(総務省/財務省/厚生労働省、コード付き)から、RS(行政事業レビューシステム)
実データの所管府省庁名23件 + 法令経路3機関の26行(名称主キー、裁定B12)へ
拡張したことの検証。

`sources.py` の sha256/recorded_on が実ファイルと一致することは、既に
`tests/test_pipeline.py::test_reference_table_digest_matches_the_registry`
が担保している(ブリーフ task-5-brief.md Step 2 の注記どおり、重複させない)。
"""
from pathlib import Path

from jgkg.transform.law import (
    LawRecord,
    UnresolvedJurisdiction,
    derive_jurisdiction,
    to_ministry_reference,
)
from jgkg.transform.ministry import Ministry, build, load_reference
from jgkg.transform.old_ministries import DEFAULT_PATH as OLD_MINISTRIES_PATH
from jgkg.transform.old_ministries import load_old_ministries
from jgkg.transform.organization import Organization

REFERENCE_PATH = Path("data/reference/ministry-codes.csv")

# 実在の対応(2026-08-23、data/lake/houjin-bangou/2026-08-23/zenken.zip の
# 実測で確認。tests/zenken_rows.py / test_transform_law.py と同じ値)。
# 既存fixtureを再利用する(R45: 新しい実在値を増やさない)
SOUMU_BANGOU = "2000012020001"

# 観察6の3機関の実在の法人番号(2026-08-23、同じzenken全件データの実測)。
# 参照表(data/reference/ministry-codes.csv)自身がこの3機関を法令経路の
# 追加行として持つので、ここでの合成Organizationは「実在する機関を指す、
# 実在の法人番号を持つ」ものになる(R45: 以前はこのタスクのネットワーク
# 制約(GIF配下のみ)で確認できず合成値を使っていたが、その後stat.go.jpの
# 調査中に許可が広がり、最終的にはRSの結合とは無関係に houjin-bangou の
# 実データを直接検索して確認できた)
JINJIIN_BANGOU = "2000012010002"
KAIKEI_KENSAIN_BANGOU = "6000012150001"
KOKKA_KOUAN_IINKAI_BANGOU = "7000012010022"


def test_reference_covers_current_ministries():
    """参照表が最低限の現行府省を含むこと(何があれば落ちるか: 行の欠落)。

    ブリーフ(task-5-brief.md Step 2)が指定する最小集合。1府11省2庁相当
    (デジタル庁・復興庁を含む)。**RSの所管府省名として現れる機関を網羅する**
    という Interfaces の要求の下限をここで固定する(裁定B12で名簿の出典は
    RS実データそのものになった)。
    """
    names = {n for _, n in load_reference(REFERENCE_PATH)}
    for required in [
        "内閣府", "総務省", "法務省", "外務省", "財務省", "文部科学省",
        "厚生労働省", "農林水産省", "経済産業省", "国土交通省",
        "環境省", "防衛省", "デジタル庁", "復興庁",
    ]:
        assert required in names, f"{required} が参照表に無い"


def test_reference_has_no_verified_current_code():
    """全行 ministry_code が None であること(裁定B12)。

    現行コードを安定して確認できる一次資料が見つかっていない(GIFはコード
    自体を持たず、統計局「利用機関コード」は5桁で旧来の013/017/020のいずれ
    とも不一致・内容も陳腐化していた)。**分からない値を書くより、無い方が
    公共財として正しい**という判断を、参照表の実データで固定する。
    """
    reference = load_reference(REFERENCE_PATH)
    assert len(reference) == 26
    assert all(code is None for code, _ in reference), (
        "現行コードの一次資料が無いのに ministry_code を持つ行がある"
    )


def _org(bangou: str, name: str) -> Organization:
    """テスト用のOrganization(国の機関)。呼び出し側は実在の法人番号を渡す(R45)。"""
    return Organization(
        uri=f"https://jgkg.norr-tech.com/id/org/{bangou}",
        houjin_bangou=bangou,
        name=name,
        kind_code="101",
        is_government_organ=True,
    )


def _law_record(law_id: str, law_num: str) -> LawRecord:
    return LawRecord(
        law_id=law_id,
        law_num=law_num,
        law_num_type="MinisterialOrdinance",
        law_type="MinisterialOrdinance",
        law_title="テスト用の題名",
        abbrev=[],
        promulgation_date="2020-01-01",
        repeal_status="None",
        revisions=[],
    )


def _build_reference(extra_orgs: list[Organization]) -> dict[str, list[Ministry]]:
    """実際にコミットした参照表 + 与えたOrganizationからreferenceを組み立てる。"""
    reference_rows = load_reference(REFERENCE_PATH)
    ministries, _unmatched = build(extra_orgs, reference_rows)
    return to_ministry_reference(ministries)


# =============================================================================
# 前のタスクから引き継いだ完了条件(Task 4レビューの観察6):
# 参照表拡張後、人事院・会計検査院・国家公安委員会がOBSOLETE_ORGANIZATIONと
# 誤称されなくなること。
#
# `tests/test_transform_law.py::test_derive_jurisdiction_classifies_unlisted_organ_shaped_name_as_obsolete_organization`
# が `reference={}` で固定した「Before」(Task 4時点、3行の参照表)に対する
# 「After」をここで示す。法令番号は同ファイルの CASES と同じ実在の値(R45)。
# =============================================================================


def test_derive_jurisdiction_resolves_jinjiin_after_reference_expansion():
    """人事院がOBSOLETE_ORGANIZATIONと誤称されなくなること(観察6)。

    test_transform_law.py の同名シナリオ(reference={})と同じ法令番号
    ("人事院規則一―四")を使い、参照表が拡張された後は resolved になる
    ことだけが違いであるように書く(分類ロジック自体はTask 4から変えて
    いないことの証拠にするため)。法人番号は実在の値(2026-08-23、zenken
    全件データの実測)。
    """
    reference = _build_reference([_org(JINJIIN_BANGOU, "人事院")])
    record = _law_record("999RS0000000001", "人事院規則一―四")

    result = derive_jurisdiction(record, reference, old_ministries=set())

    assert result.resolved == [JINJIIN_BANGOU]
    assert result.unresolved == [], f"人事院がまだ未解決: {result.unresolved}"


def test_derive_jurisdiction_resolves_kaikei_kensain_while_okurasho_stays_old_ministry():
    """会計検査院がOBSOLETE_ORGANIZATIONと誤称されなくなること(観察6)。

    共管相手の大蔵省(2001年の中央省庁再編で廃止)が引き続きOLD_MINISTRYの
    ままであること(誤ってresolvedにも別のOBSOLETE_ORGANIZATIONにもならない
    こと)も合わせて固定する。法令番号は test_transform_law.py の
    extract_ministry_names のテストと同じ実在の値(R45)。会計検査院の法人番号も
    実在の値(2026-08-23、zenken全件データの実測)。
    """
    reference = _build_reference([_org(KAIKEI_KENSAIN_BANGOU, "会計検査院")])
    old_ministries = load_old_ministries(OLD_MINISTRIES_PATH)
    record = _law_record("999XX0000000010", "平成十二年会計検査院・大蔵省令第一号")

    result = derive_jurisdiction(record, reference, old_ministries=old_ministries)

    assert result.resolved == [KAIKEI_KENSAIN_BANGOU]
    assert result.unresolved == [UnresolvedJurisdiction(name="大蔵省", reason="OLD_MINISTRY")]


def test_derive_jurisdiction_resolves_kokka_kouan_iinkai_and_soumusho_jointly():
    """国家公安委員会がOBSOLETE_ORGANIZATIONと誤称されなくなること(観察6)。

    共管相手の総務省(現存。拡張前の3行にも入っていた)も引き続き resolved
    であることを合わせて固定する(参照表の拡張が既存の突合を壊していない
    ことの確認)。法令番号は test_transform_law.py の
    extract_ministry_names のテストと同じ実在の値(R45)。国家公安委員会の
    法人番号も実在の値であり、警察庁とは別の法人番号を持つ独立した機関
    (2026-08-23、zenken全件データの実測。国家公安委員会=法人番号
    7000012010022、警察庁=8000012130001。stat.go.jpの旧「利用機関コード」が
    両者を1つの複合コードで表していたのとは異なり、法人番号ベースでは
    別個体である)。
    """
    reference = _build_reference(
        [_org(KOKKA_KOUAN_IINKAI_BANGOU, "国家公安委員会"), _org(SOUMU_BANGOU, "総務省")]
    )
    record = _law_record("999XX0000000011", "昭和四十七年国家公安委員会・総務省令第一号")

    result = derive_jurisdiction(record, reference, old_ministries=set())

    assert result.resolved == [KOKKA_KOUAN_IINKAI_BANGOU, SOUMU_BANGOU]
    assert result.unresolved == []
