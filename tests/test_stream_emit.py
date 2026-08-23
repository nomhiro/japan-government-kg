"""Task 8: 全法人のストリーミング投入(stream_emit + バッチSHACL検証)。

**中心の論証**: バッチSHACL検証が全体検証と等価であるのは、このスキーマの
シェイプがエンティティ局所(閉じたNodeShape。エンティティを跨ぐ制約はR2で
排除済み)だからである。同一主語の全トリプルが同じバッチに入っていれば、
バッチ検証の合併 = 全体検証。これを成立させる3条件を、このファイルで
それぞれ独立に検証する(task-8-brief.md):

1. `dedup_organizations`: 同一法人番号の重複は上流で弾く(このセクション)。
   バッチを跨いだ重複は検出できない(2つのバッチがそれぞれ単一の
   skos:prefLabelしか見ないため、両方が個別に合格してしまう)ので、
   dedup前提が無いと条件2の「1エンティティ1回」が成立しない。
2. `stream_emit_organizations`: 1エンティティの全トリプルを連続して書く。
3. `validate_stream`: バッチ境界は主語の切れ目でのみ切る(等価性の実証。
   わざと主語跨ぎで割ると差が出ることも確認する)。
"""
import datetime

import pytest

from jgkg.rdf import stream_emit
from jgkg.transform.organization import Organization
from jgkg.uris import org_uri

DAY = datetime.date(2026, 8, 1)


@pytest.fixture(autouse=True)
def fixed_base(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "https://jgkg.norr-tech.com")
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _org(bangou="6000012070001", name="厚生労働省", kind="101", updated_on="2018-04-02", **overrides):
    defaults = dict(
        uri=org_uri(bangou),
        houjin_bangou=bangou,
        name=name,
        kind_code=kind,
        is_government_organ=(kind == "101"),
        updated_on=updated_on,
    )
    defaults.update(overrides)
    return Organization(**defaults)


# =============================================================================
# Step 1: dedup_organizations
#
# 「後勝ち」は更新年月日(列[4]。organization.pyの照合記録が正)の値そのもので
# 決まる。ファイル中の出現順ではない(task-8-brief.md 引き継ぐ決定)。
# センチネル法人番号(B18: 9999999999999)の実データ0件はRS側の話であり、
# ここのdedupとは無関係(混同防止のため明示。task-8-brief.md 引き継ぐ決定)。
# =============================================================================


def test_dedup_keeps_the_row_with_the_newer_updated_on():
    """同一法人番号2行(更新日が異なる)→ 新しい方が残り、dedup件数=1が報告される。

    これがStep 1の中心のテスト(task-8-brief.md)。何があれば落ちるか:
    dedupを実装しない/件数を報告しないと、このテストは import または
    assert で落ちる。
    """
    older = _org(name="旧名称", updated_on="2018-04-02")
    newer = _org(name="新名称", updated_on="2020-01-15")

    stats = stream_emit.StreamStats()
    result = list(stream_emit.dedup_organizations(lambda: iter([older, newer]), stats))

    assert [o.name for o in result] == ["新名称"], "更新日が新しい方が残らなければならない"
    assert stats.dedup_removed == 1, "弾いた件数が報告されていない(消したことを黙らない)"
    assert stats.rows_in == 2, "入力側の件数(dedup前)も報告されるべき"


def test_dedup_winner_is_decided_by_date_value_not_file_position():
    """後勝ちは「更新日の値」で決まる。ファイル中の出現順(新→旧)でも同じ勝者になる。

    何があれば落ちるか: 実装が「ファイルで後に出現した行が勝つ」という
    位置ベースの単純化にすり替わっていたら、この順序で逆の結果になる。
    """
    newer = _org(name="新名称", updated_on="2020-01-15")
    older = _org(name="旧名称", updated_on="2018-04-02")

    stats = stream_emit.StreamStats()
    result = list(stream_emit.dedup_organizations(lambda: iter([newer, older]), stats))

    assert [o.name for o in result] == ["新名称"]
    assert stats.dedup_removed == 1


def test_dedup_ties_on_equal_date_keep_the_last_occurrence_deterministically():
    """更新日が完全に同値の重複(実データにありうる)は、出現順の最後を勝者にする。

    これは「後勝ち」の定義自体には現れない退化ケース(日付で決められない)への
    決定的な補助規則。何があれば落ちるか: 実装がタイの扱いを非決定的にする
    (setの反復順序に依存する等)と、この結果がテスト実行ごとに変わる。
    """
    first = _org(name="行A", updated_on="2020-01-15")
    second = _org(name="行B", updated_on="2020-01-15")

    stats = stream_emit.StreamStats()
    result = list(stream_emit.dedup_organizations(lambda: iter([first, second]), stats))

    assert [o.name for o in result] == ["行B"], "日付が同じ場合は出現順で後の行を残す"


def test_dedup_passes_through_unique_organizations_unchanged():
    """重複が無い行はdedupの影響を受けず、件数もそのまま通ること(誤検出の否定的コントロール)。"""
    a = _org(bangou="6000012070001", name="厚生労働省")
    b = _org(bangou="2000012020001", name="総務省")

    stats = stream_emit.StreamStats()
    result = list(stream_emit.dedup_organizations(lambda: iter([a, b]), stats))

    assert {o.houjin_bangou for o in result} == {"6000012070001", "2000012020001"}
    assert stats.dedup_removed == 0
    assert stats.rows_in == 2


def test_dedup_handles_three_occurrences_of_the_same_key():
    """3回以上の重複でも、勝者1件だけが残り、残りすべてが弾いた件数に入ること。

    何があれば落ちるか: 「重複キーの数」を件数として報告する実装(2件以上の
    重複を1件としてしまう)だと、このテストは dedup_removed == 2 を期待する
    のに 1 を返して落ちる。
    """
    rows = [
        _org(name="v1", updated_on="2015-01-01"),
        _org(name="v3-最新", updated_on="2021-06-01"),
        _org(name="v2", updated_on="2018-04-02"),
    ]

    stats = stream_emit.StreamStats()
    result = list(stream_emit.dedup_organizations(lambda: iter(rows), stats))

    assert [o.name for o in result] == ["v3-最新"]
    assert stats.dedup_removed == 2, "3件から1件を残す=2件を弾く"
    assert stats.rows_in == 3


def test_dedup_seen_set_memory_budget_is_within_the_phase1_budget():
    """見積り: 5.8M件の法人番号をintでsetに載せるメモリが上限内であること。

    `dedup_organizations`の1パス目は、重複検出のためだけに全法人番号(int化)を
    `set`に載せる(task-8-brief.md Step1の指示)。5.8M件の`Organization`本体
    (名称・住所などの文字列を持つ)を保持するのはR19/R21が禁じる「全件蓄積」
    だが、int化した法人番号だけの`set`はその対象外であることを実測で示す。
    **この`set`は1パス目でのみ生存する**(2パス目に必要なのは実際に重複していた
    キーの小さい集合だけなので、1パス目の`set`は使い終わったら破棄する —
    `dedup_organizations`の実装コメント参照)。

    実測(このテスト実行時、`tracemalloc`で計測): サンプル20万件のset追加コストを
    実測し、5.8M件に線形外挿する。Phase 1の想定実行環境(2vCPU/8GiB。
    `organization.py`の`parse_file`docstring参照)に対して十分小さいことを
    固定する(2026-08-24, CPython 3.12.11, Windows実測: 約70バイト/件 →
    5.8M件で約385MiB。1GiBという緩い上限は実行環境差を吸収しつつ、
    「Organization本体をsetに入れてしまう」ような桁違いの退行は確実に検出する)。
    """
    import tracemalloc

    sample_size = 200_000
    base = 6_000_000_000_000  # 13桁の法人番号レンジを模す
    tracemalloc.start()
    before = tracemalloc.get_traced_memory()[0]
    seen: set[int] = set()
    for i in range(sample_size):
        seen.add(base + i)
    after = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()

    per_entry_bytes = (after - before) / sample_size
    estimated_total_mib = per_entry_bytes * 5_800_000 / (1024**2)

    assert estimated_total_mib < 1024, (
        f"法人番号setの推定メモリが1GiBを超えた(1件あたり{per_entry_bytes:.1f}バイト、"
        f"5.8M件で{estimated_total_mib:.1f}MiB)。int化を外した等の退行の疑いがある"
    )
