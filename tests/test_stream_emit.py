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
    defaults = {
        "uri": org_uri(bangou),
        "houjin_bangou": bangou,
        "name": name,
        "kind_code": kind,
        "is_government_organ": (kind == "101"),
        "updated_on": updated_on,
    }
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


def test_dedup_treats_an_empty_updated_on_as_the_oldest_possible_value():
    """O-9: `updated_on`が空文字(不明)の行の扱いを固定する。

    特別扱いはしない(dedup_organizationsのdocstring参照) — 既定の文字列
    比較(`>=`)に委ねるだけで、次の2つが自然に得られる:
    (1) 空文字と実在の日付が競合すれば、出現順に関わらず実在の日付が勝つ
    (空文字は辞書順で常に最小)。
    (2) 重複が全件空文字なら、既存のタイブレーク規則どおり出現順で最後の
    行が勝つ。
    """
    # (1): 空文字が先に出現しても、後から来た実在の日付に負ける
    empty_first = _org(name="不明日付", updated_on="")
    dated_second = _org(name="実在日付", updated_on="2018-04-02")
    stats = stream_emit.StreamStats()
    result = list(stream_emit.dedup_organizations(lambda: iter([empty_first, dated_second]), stats))
    assert [o.name for o in result] == ["実在日付"], "空文字の日付が実在の日付に勝ってしまった"

    # (1)の逆順: 実在の日付が先に出現しても、後から来た空文字には負けない
    dated_first = _org(name="実在日付", updated_on="2018-04-02")
    empty_second = _org(name="不明日付", updated_on="")
    stats2 = stream_emit.StreamStats()
    result2 = list(
        stream_emit.dedup_organizations(lambda: iter([dated_first, empty_second]), stats2)
    )
    assert [o.name for o in result2] == ["実在日付"], "出現順が後というだけで空文字の日付が勝ってしまった"

    # (2): 全件が空文字なら、通常のタイブレーク(出現順で最後)がそのまま働く
    first_empty = _org(name="行A", updated_on="")
    second_empty = _org(name="行B", updated_on="")
    stats3 = stream_emit.StreamStats()
    result3 = list(
        stream_emit.dedup_organizations(lambda: iter([first_empty, second_empty]), stats3)
    )
    assert [o.name for o in result3] == ["行B"], "全件空文字のタイブレークが出現順の最後にならなかった"


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


def test_dedup_populates_houjin_bangou_seen_with_every_distinct_key():
    """B21(Task 10): 重複を含む入力からも、distinctな法人番号の全体集合が

    `stats.houjin_bangou_seen` に残ること(重複分は1回だけ)。**何があれば
    落ちるか**: 従来どおり`del seen`していれば`stats.houjin_bangou_seen`が
    `None`のままで落ちる。
    """
    rows = [
        _org(bangou="6000012070001", name="v1", updated_on="2015-01-01"),
        _org(bangou="6000012070001", name="v2-最新", updated_on="2021-06-01"),
        _org(bangou="2000012020001", name="総務省"),
    ]
    stats = stream_emit.StreamStats()
    list(stream_emit.dedup_organizations(lambda: iter(rows), stats))

    assert stats.houjin_bangou_seen == {6000012070001, 2000012020001}


def test_houjin_bangou_seen_is_none_when_dedup_was_never_run():
    """全法人ストリームを一度も実行していない状態(既定)を`None`で表すこと。

    空集合(`set()`)と意味的に区別する — 空集合は「実行したが0件だった」
    という別の事実になるため、フラグOFF時の既定(`StreamStats()`をそのまま
    使う場合)が誤って「0件の全法人グラフが存在する」と読めてはならない。
    """
    stats = stream_emit.StreamStats()
    assert stats.houjin_bangou_seen is None


def test_dedup_seen_set_memory_budget_is_within_the_phase1_budget():
    """見積り: `dedup_organizations`を実際に呼び、ピークメモリが上限内であること。

    **F-6(レビュー指摘)**: 以前のこのテストは裸の`set[int]`だけを測定し、
    `dedup_organizations`自体を一度も呼んでいなかった(実装からの乖離 —
    intでない何かをキーにする退行や、他の場所での余分な蓄積を検出できない)。
    ここでは実際にジェネレータファクトリ(呼ぶたびに新しい`Organization`の列を
    生成する。事前に`list`化しない)を`dedup_organizations`に渡し、フルの
    実行(1パス目のint集合構築→解放→2パス目)を通したピークメモリを
    `tracemalloc`で測る。重複を1件も作らない(2パス目の`pending`が空のまま
    になる)ので、測ったピークは実質的に1パス目の`seen`が支配する。

    **サンプルは`tracemalloc.start()`の前に構築してはならない**(サンプルの
    構築コストがピークを支配してしまい、`dedup_organizations`自体ではなく
    「20万件の`Organization`をメモリに置くコスト」を測ることになる)。`source`
    をジェネレータ式のファクトリにして、`tracemalloc.start()`の**後**に
    初めて各`Organization`が生成されるようにする。**出力も`list`化しない**
    (同じ理由 — 5.8M件分を`list`で保持したら、ここでのテストの都合で
    ピークを実際より大きく見せてしまう。`stream_emit_organizations`は
    1件ずつ即座に書き出して捨てるので、実運用ではこの保持は起きない)。

    実測(このテスト実行時、`tracemalloc`で計測): サンプル20万件を実行した
    ピークメモリを5.8M件に線形外挿する。Phase 1の想定実行環境(2vCPU/8GiB。
    `organization.py`の`parse_file`docstring参照)に対して十分小さいことを
    固定する(2026-08-24, CPython 3.13.5, Windows実測: 約88.2バイト/件 →
    5.8M件で約487.7MiB。レビューが別途行った実測(200,000件・約88.6バイト/件・
    約490MiB)と同水準で、int化した法人番号だけの集合であることが裏付けられる。
    1GiBという緩い上限は実行環境差を吸収しつつ、「Organization本体を1パス目の
    setに丸ごと入れてしまう」ような桁違いの退行は確実に検出する)。
    """
    import tracemalloc

    sample_size = 200_000
    base = 6_000_000_000_000  # 13桁の法人番号レンジを模す(重複無し)

    def _source():
        return (
            _org(
                bangou=str(base + i),
                name=f"サンプル法人{i}",
                prefecture="東京都",
                city="千代田区",
            )
            for i in range(sample_size)
        )

    tracemalloc.start()
    stats = stream_emit.StreamStats()
    count = 0
    for _ in stream_emit.dedup_organizations(_source, stats):
        count += 1
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()

    assert count == sample_size, (
        "重複無しのサンプルなのに件数が減っている(テストの前提が崩れている)"
    )
    per_entry_bytes = peak / sample_size
    estimated_total_mib = per_entry_bytes * 5_800_000 / (1024**2)

    assert estimated_total_mib < 1024, (
        f"dedup_organizations実行のピークメモリが5.8M件換算で1GiBを超えた"
        f"(1件あたり{per_entry_bytes:.1f}バイト、5.8M件で{estimated_total_mib:.1f}MiB)。"
        "Organization本体を1パス目のsetに丸ごと入れてしまう等の退行の疑いがある"
    )


def test_dedup_raises_when_source_returns_a_different_row_count_on_the_second_call():
    """F-4(b): `source()`が2回とも同じ内容を返すという2パス方式の前提が

    崩れたら例外にすること。**行数の一致は「鳴子」であって内容のハッシュ
    ではない** — 同じ件数のまま内容が入れ替わるより巧妙な不一致までは
    検出できないが、そのケースはvalidate_stream側の非隣接主語再出現の検査
    (F-4b/O-8)が別途捕まえる(二段構え)。ここでは最も基本的な破れ
    (件数そのものが変わる)を固定する。
    """
    call_count = 0

    def flaky_source():
        nonlocal call_count
        call_count += 1
        rows = [_org(bangou="6000012070001"), _org(bangou="2000012020001")]
        if call_count >= 2:
            rows.append(_org(bangou="8000012050001"))  # 2回目だけ1件増える
        return iter(rows)

    stats = stream_emit.StreamStats()
    with pytest.raises(ValueError, match="件数が一致しない"):
        list(stream_emit.dedup_organizations(flaky_source, stats))


# =============================================================================
# Step 2: stream_emit_organizations
#
# rdflib の Dataset には貯めない。1行ずつ直接 out に書く。出力が
# rdflib で再パース可能なN-Quadsであること・1エンティティの全トリプルが
# 連続して書かれること・件数がStreamStatsに正しく報告されることを確認する。
# =============================================================================

GRAPH_URI = "https://jgkg.norr-tech.com/graph/houjin-bangou-all/2026-08-01"


def test_stream_emit_output_is_reparsable_nquads_with_expected_triples():
    """出力がrdflibで再パース可能なN-Quadsで、emit_organizationsと同じ述語集合を持つこと。

    emit_organizations(emit.py)がDataset経由で書く述語(rdf:type/skos:prefLabel/
    org:houjinBangou/org:organizationKindCode/org:prefectureName/org:cityName)を
    N-Quadsの行として直接書けているかを、rdflib自身に再パースさせて確認する。
    """
    import io

    from rdflib import RDF, Dataset, Literal, URIRef
    from rdflib.namespace import SKOS

    org = _org(prefecture="東京都", city="千代田区")
    out = io.StringIO()
    stats = stream_emit.stream_emit_organizations(iter([org]), GRAPH_URI, out)

    reloaded = Dataset()
    reloaded.parse(data=out.getvalue(), format="nquads")

    s = URIRef(org.uri)
    gid = URIRef(GRAPH_URI)
    org_ns = "https://jgkg.norr-tech.com/def/org#"
    assert (s, RDF.type, URIRef(org_ns + "GovernmentOrgan"), gid) in reloaded
    assert (s, SKOS.prefLabel, Literal("厚生労働省", lang="ja"), gid) in reloaded
    assert (s, URIRef(org_ns + "houjinBangou"), Literal("6000012070001"), gid) in reloaded
    assert (s, URIRef(org_ns + "organizationKindCode"), Literal("101"), gid) in reloaded
    assert (s, URIRef(org_ns + "prefectureName"), Literal("東京都", lang="ja"), gid) in reloaded
    assert (s, URIRef(org_ns + "cityName"), Literal("千代田区", lang="ja"), gid) in reloaded
    assert stats.triples == 6, "書き出したトリプル数の報告が一致しない"
    assert stats.entities == 1


def test_stream_emit_omits_prefecture_and_city_when_absent():
    """空文字のprefecture/cityはトリプル自体を出さない(emit_organizationsと同じ作法)。"""
    import io

    from rdflib import Dataset, URIRef

    org = _org(bangou="9999999999999", kind="301", prefecture="", city="")
    out = io.StringIO()
    stats = stream_emit.stream_emit_organizations(iter([org]), GRAPH_URI, out)

    # default_union=True(名前付きグラフを跨いだ2引数クエリのため。emit.pyの
    # _new_dataset と同じ理由)。この`reloaded.objects`が本当に名前付きグラフを
    # 見ていることは、houjinBangouが実際に引ける(空にならない)ことで確認する
    # — でなければ「クエリが常に空を返すから通る」という空振りのテストになる
    reloaded = Dataset(default_union=True)
    reloaded.parse(data=out.getvalue(), format="nquads")
    s = URIRef(org.uri)
    org_ns = "https://jgkg.norr-tech.com/def/org#"
    assert list(reloaded.objects(s, URIRef(org_ns + "houjinBangou"))), (
        "クエリが名前付きグラフを見ていない(default_unionの設定を確認)"
    )
    assert list(reloaded.objects(s, URIRef(org_ns + "prefectureName"))) == []
    assert list(reloaded.objects(s, URIRef(org_ns + "cityName"))) == []
    # type/prefLabel/houjinBangou/organizationKindCode の4本だけ
    assert stats.triples == 4


def test_stream_emit_a_non_government_organ_gets_the_plain_organization_type():
    """is_government_organ=Falseは org:Organization(org:GovernmentOrganではない)であること。"""
    import io

    from rdflib import RDF, Dataset, URIRef

    org = _org(bangou="9999999999999", name="株式会社サンプル", kind="301")
    out = io.StringIO()
    stream_emit.stream_emit_organizations(iter([org]), GRAPH_URI, out)

    # default_union=True(名前付きグラフを跨いだ2引数クエリのため。emit.pyの
    # _new_dataset と同じ理由 — 無いと .objects() は既定グラフだけを見て空になる)
    reloaded = Dataset(default_union=True)
    reloaded.parse(data=out.getvalue(), format="nquads")
    s = URIRef(org.uri)
    org_ns = "https://jgkg.norr-tech.com/def/org#"
    types = set(reloaded.objects(s, RDF.type))
    assert types == {URIRef(org_ns + "Organization")}


def test_stream_emit_writes_each_entitys_triples_contiguously():
    """1エンティティの全トリプルが連続して書かれること(バッチ=全体の等価性の条件1)。

    何があれば落ちるか: 実装が全件をまず何らかの構造に集めてから主語で
    ソートし直すような実装だと、この特定の入力順そのものは崩れて別の形に
    なる(このテストは「入力順のまま連続」を固定する。決定性の要件と対)。
    複数エンティティを混ぜて、同じ主語の行が別の主語の行に割り込まれていない
    ことを確認する。
    """
    import io

    a = _org(bangou="6000012070001", name="厚生労働省", prefecture="東京都", city="千代田区")
    b = _org(bangou="2000012020001", name="総務省", prefecture="東京都", city="千代田区")
    out = io.StringIO()
    stream_emit.stream_emit_organizations(iter([a, b]), GRAPH_URI, out)

    lines = out.getvalue().splitlines()
    subjects = [line.split(" ", 1)[0] for line in lines]

    # 「連続」= 同じ主語のブロックが1つだけ(一度出た主語が途切れて後で再開しない)
    seen_blocks: list[str] = []
    for subj in subjects:
        if not seen_blocks or seen_blocks[-1] != subj:
            seen_blocks.append(subj)
    assert seen_blocks.count(f"<{org_uri('6000012070001')}>") == 1
    assert seen_blocks.count(f"<{org_uri('2000012020001')}>") == 1
    # 入力順(a→b)がそのまま出力順であること(決定性。ソートしない判断の確認)
    assert seen_blocks == [f"<{org_uri('6000012070001')}>", f"<{org_uri('2000012020001')}>"]


def test_stream_emit_entity_and_triple_counts_match_the_input():
    import io

    orgs = [
        _org(bangou="6000012070001", prefecture="東京都", city=""),
        _org(bangou="2000012020001", name="総務省", prefecture="", city=""),
        _org(bangou="8000012050001", name="財務省", prefecture="東京都", city="千代田区"),
    ]
    out = io.StringIO()
    stats = stream_emit.stream_emit_organizations(iter(orgs), GRAPH_URI, out)

    assert stats.entities == 3
    # 5本 + 4本 + 6本 = 15本
    assert stats.triples == 15
    assert len(out.getvalue().splitlines()) == 15


def test_stream_emit_raises_on_an_embedded_newline_instead_of_corrupting_the_stream():
    """名称等に生の改行が入っていたら、1行=1トリプルの前提が壊れる前に例外にする。

    **何があれば落ちるか**: rdflibの`Literal.n3()`は改行を含む文字列に対して
    複数行のトリプルクオート形式(`\"\"\"...\"\"\"`)を返すことがある
    (実測で確認)。これはTurtle/N3としては妥当だが、N-Quadsの「1行=1トリプル」
    という、validate_streamのバッチ分割が前提にしている性質を静かに破壊する。
    ここで例外にすることで、データ起因の想定外を沈黙させない(§8.2の作法)。
    """
    import io

    org = _org(name="改行\nを含む名称")
    out = io.StringIO()
    with pytest.raises(ValueError, match="改行"):
        stream_emit.stream_emit_organizations(iter([org]), GRAPH_URI, out)


# =============================================================================
# Step 3: validate_stream — バッチ=全体の等価性の実証
#
# 「バッチ検証の合併=全体検証」が成り立つのは、シェイプがエンティティ局所
# だから、かつ、同一主語の全トリプルが同じバッチに入っているから。前者は
# schema側の裁定(R2)で既に成立している。後者を検証するのがこのセクション:
# 正常系(主語の切れ目でのみ分割)では一致し、わざと主語を跨いで分割すると
# 一致しなくなることを示す(等価条件が装飾ではなく実質であることの証明)。
# =============================================================================


def _whole_graph_conforms(nq_path) -> bool:
    """全体一発の検証結果(比較の基準)。1ファイル=1グラフという前提で、
    validate_dataset(グラフ単位検証)にそのまま流せば「全体検証」になる。
    """
    from rdflib import Dataset

    from jgkg import validate

    ds = Dataset()
    ds.parse(nq_path, format="nquads")
    results = validate.validate_dataset(ds, _shapes_dir())
    assert results, "検証対象のグラフが無い(比較の前提が崩れている)"
    return all(r.conforms for r in results)


def _shapes_dir():
    from pathlib import Path

    return Path("schema/generated")


def test_validate_stream_batched_result_matches_the_whole_graph_result_for_a_valid_stream(tmp_path):
    """正常系: batch_size=2で細かく割っても、全体一発の結果(合格)と一致すること。

    stream_emit_organizations(dedup済み前提)の出力を使う — 実運用の経路
    そのもの。batch_size=2は各エンティティ(5〜6行)より小さいので、
    確実に複数バッチに分かれる(バッチ数>1をまず確認し、この設定が
    本当に分割を起こしていることを保証する)。
    """
    import io

    from jgkg import validate

    orgs = [
        _org(bangou="6000012070001", name="厚生労働省", prefecture="東京都", city="千代田区"),
        _org(bangou="2000012020001", name="総務省", prefecture="東京都", city="千代田区"),
        _org(bangou="8000012050001", name="財務省", prefecture="東京都", city="霞が関"),
    ]
    out = io.StringIO()
    stream_emit.stream_emit_organizations(iter(orgs), GRAPH_URI, out)

    nq_path = tmp_nq_path()
    nq_path.write_text(out.getvalue(), encoding="utf-8")

    batched = validate.validate_stream(nq_path, _shapes_dir(), tmp_path / "quarantine", batch_size=2)
    assert len(batched) > 1, "batch_size=2が分割を起こしていない(テストの前提が崩れている)"

    whole = _whole_graph_conforms(nq_path)
    assert whole, "全体一発の結果が合格のはずが不合格になっている(テストの前提が崩れている)"
    assert all(r.conforms for r in batched), "バッチ検証の結果が全体一発(合格)と一致しない"


def test_validate_stream_batched_result_matches_the_whole_graph_result_for_a_local_violation(tmp_path):
    """正常系(壊し確認込み): エンティティ局所な違反(法人番号の桁数不正)は、

    バッチに分けても分けなくても同じく検出されること。この違反は1エンティティ
    の中に閉じているため、バッチ分割の有無に結果が影響されないはず
    (エンティティ局所シェイプという前提そのものの確認)。
    """
    import io
    from pathlib import Path

    from rdflib import Literal, URIRef

    from jgkg import validate
    from jgkg.config import get_settings

    org = _org(bangou="6000012070001", name="厚生労働省")
    out = io.StringIO()
    stream_emit.stream_emit_organizations(iter([org]), GRAPH_URI, out)

    # 手作業で1エンティティ分を足す: 法人番号がsh:patternに違反する行
    # (既存テストのtest_malformed_houjin_bangou_fails_validationと同じ壊し方)
    org_ns = f"{get_settings().base_uri}/def/org#"
    bad_s = URIRef(f"{get_settings().base_uri}/id/org/9999999999999").n3()
    graph_n3 = URIRef(GRAPH_URI).n3()
    rdf_type = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
    out.write(f"{bad_s} {rdf_type} <{org_ns}Organization> {graph_n3} .\n")
    out.write(f"{bad_s} <{org_ns}houjinBangou> {Literal('BROKEN').n3()} {graph_n3} .\n")

    nq_path = tmp_nq_path()
    nq_path.write_text(out.getvalue(), encoding="utf-8")

    whole = _whole_graph_conforms(nq_path)
    assert whole is False, "違反入りのfixtureが全体検証で合格してしまっている(テストの前提が崩れている)"

    quarantine_dir = tmp_path / "quarantine"
    batched = validate.validate_stream(nq_path, _shapes_dir(), quarantine_dir, batch_size=2)
    assert not all(r.conforms for r in batched), (
        "エンティティ局所な違反がバッチ検証で検出できていない"
    )
    # B-1(裁定B23): 不合格バッチにはreport_path/violation_countが埋まり、
    # 全文が実際にディスクへ書かれていること
    failing = [r for r in batched if not r.conforms]
    assert failing, "不合格バッチが1つも無い"
    for r in failing:
        assert r.violation_count > 0, "違反件数が0のまま(_count_violationsが機能していない)"
        assert r.report_path is not None, "不合格バッチにreport_pathが埋まっていない"
        assert Path(r.report_path).read_text(encoding="utf-8"), (
            "隔離レポートのファイルが空(全文がディスクに書かれていない)"
        )
    assert quarantine_dir.exists(), "quarantine_dirが実際に作られていない"


def test_validate_stream_diverges_from_the_whole_graph_result_when_split_mid_subject(tmp_path):
    """**等価条件が実質であることの証明**: 主語の切れ目を無視して(=わざと

    主語を跨いで)分割すると、全体一発の結果と一致しなくなる**危険がある**こと。

    同一主語(法人番号)の`skos:prefLabel`を2つ持つデータ(sh:maxCount 1
    違反)を作るが、その2つを**連続させずに**別の主語のブロックを挟んで書く
    (「1エンティティの全トリプルを連続して書く」という条件1が破れている
    状況を人為的に再現する — dedup済みの正常な経路ではこの状態は作れない
    ため、手書きのN-Quadsで構成する)。batch_sizeを、ちょうど「主語が
    変わった直後」に流れ込むように選ぶと、同一主語の2つのブロックが別々の
    バッチに分かれる。

    **このテストの歴史(F-4b以前)**: 以前はこの分割を`validate_stream`が
    無防備に受け入れ、各バッチが単独ではprefLabelを1つしか見ないため両方が
    個別に合格し、全体一発(不合格)と結果が一致しないまま**沈黙して**
    「合格」を返していた。F-4b(主語の非隣接再出現の検出)を追加した後は、
    この状況そのものを検出して例外になる — 「結果が食い違う」のではなく
    「食い違う恐れのある入力そのもので止まる」に変わった、という違いを
    このテストで固定する。
    """
    from rdflib import URIRef

    from jgkg import validate
    from jgkg.config import get_settings

    base = get_settings().base_uri
    org_ns = f"{base}/def/org#"
    s1 = URIRef(org_uri("6000012070001")).n3()
    s2 = URIRef(org_uri("2000012020001")).n3()
    graph_n3 = URIRef(GRAPH_URI).n3()
    rdf_type = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
    pref_label = "<http://www.w3.org/2004/02/skos/core#prefLabel>"

    lines = [
        # S1の最初のブロック(4行。旧いprefLabel)
        f'{s1} {rdf_type} <{org_ns}GovernmentOrgan> {graph_n3} .\n',
        f'{s1} {pref_label} "旧名称"@ja {graph_n3} .\n',
        f'{s1} <{org_ns}houjinBangou> "6000012070001" {graph_n3} .\n',
        f'{s1} <{org_ns}organizationKindCode> "101" {graph_n3} .\n',
        # S2の4行(別法人。無関係で正常)
        f'{s2} {rdf_type} <{org_ns}GovernmentOrgan> {graph_n3} .\n',
        f'{s2} {pref_label} "総務省"@ja {graph_n3} .\n',
        f'{s2} <{org_ns}houjinBangou> "2000012020001" {graph_n3} .\n',
        f'{s2} <{org_ns}organizationKindCode> "101" {graph_n3} .\n',
        # S1が再度出現(1行。新しいprefLabel — 最初のブロックと連続していない)
        f'{s1} {pref_label} "新名称"@ja {graph_n3} .\n',
    ]
    nq_path = tmp_nq_path()
    nq_path.write_text("".join(lines), encoding="utf-8")

    whole = _whole_graph_conforms(nq_path)
    assert whole is False, (
        "全体一発ではS1のprefLabelが2つ(sh:maxCount 1違反)になるはずが合格している"
    )

    # batch_size=4: S1最初の4行で1バッチ、S2の4行で1バッチ、S1再出現の1行が
    # 最後のバッチ、という3分割になる(主語の切れ目でのみ切る実装なら、
    # 「同じ主語が別バッチに分かれる」状況そのものは入力側の問題として
    # 再現できる)
    with pytest.raises(ValueError, match="非連続で再出現"):
        validate.validate_stream(
            nq_path, _shapes_dir(), tmp_path / "quarantine", batch_size=4
        )


def test_validate_stream_raises_when_a_real_stream_lets_the_same_subject_reappear_non_adjacently(
    tmp_path,
):
    """F-4b/O-8: 手書きN-Quadsではなく**実経路**(stream_emit_organizations)で

    条件1/条件3破れを再現しても、非隣接再出現が検出されること。

    上のテスト(`test_validate_stream_diverges_...`)は手書きのN-Quadsによる
    実証だった。こちらはdedup_organizationsを意図的に経由させず(=上流の
    dedup前提が崩れた状況を模す)、同一法人番号のOrganizationを2回、
    その間に別法人を挟んでstream_emit_organizationsに流す。これにより、
    O-8(条件3が崩れた場合の実経路での実証)がF-4bのこのテストによって
    同時に閉じる — 手書きのN-Quadsではなく、実際のstream_emit_organizations
    の出力を経由していることがこのテストの要点。
    """
    import io

    from jgkg import validate

    dup_a = _org(bangou="6000012070001", name="旧名称")
    other = _org(bangou="2000012020001", name="総務省")
    dup_b = _org(bangou="6000012070001", name="新名称")  # 同じ法人番号が非隣接に再出現

    out = io.StringIO()
    stream_emit.stream_emit_organizations(iter([dup_a, other, dup_b]), GRAPH_URI, out)
    nq_path = tmp_path / "reappear.nq"
    nq_path.write_text(out.getvalue(), encoding="utf-8")

    # 各Organizationは4行(prefecture/cityを指定していないため)。batch_size=4で
    # dup_aの4行→他法人の4行→dup_bの4行、という3バッチに分かれ、dup_aの主語が
    # 3バッチ目に非隣接で再出現する
    with pytest.raises(ValueError, match="非連続で再出現"):
        validate.validate_stream(
            nq_path, _shapes_dir(), tmp_path / "quarantine", batch_size=4
        )


def test_validate_stream_raises_when_a_single_subject_run_grows_without_bound(tmp_path):
    """F-4(a): 主語が変わらないまま行数がバッファ上限を超えたら例外にすること。

    バッチ境界は「主語が変わるまで待つ」ため、上流のdedupが効かずに同一
    法人番号の行が延々と連続して書かれるような単一主語の暴走に対しては、
    batch_sizeだけでは無防備になる。B-2/F-4bとは別の退行経路をここで塞ぐ。
    """
    from rdflib import URIRef

    from jgkg import validate

    graph_n3 = URIRef(GRAPH_URI).n3()
    s = URIRef(org_uri("6000012070001")).n3()
    rdf_type = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
    org_ns = "https://jgkg.norr-tech.com/def/org#"
    line = f'{s} {rdf_type} <{org_ns}Organization> {graph_n3} .\n'

    nq_path = tmp_path / "runaway.nq"
    nq_path.write_text(line * (validate._MAX_SUBJECT_RUN + 1), encoding="utf-8")

    with pytest.raises(ValueError, match="連続している"):
        validate.validate_stream(nq_path, _shapes_dir(), tmp_path / "quarantine")


def test_validate_stream_raises_when_a_batch_declares_no_classes_due_to_base_uri_drift(tmp_path):
    """B-2(対象0件ガードの変種1): rdf:typeはあるが、その名前空間がterm_prefix

    (現在のbase_uri)と一致しないバッチも、「対象0件で合格」に退化させず
    例外にすること。

    `validate_dataset`側の同種のガード(`_assert_shapes_cover`)は`declared`
    が非空だが対象シェイプが無い場合しか捕まえない — `declared`自体が空に
    なるケースは、出典グラフ(rdf:typeを持たない)との区別がつかないため
    意図的に許容されている(test_provenance_only_graph_is_not_flagged_by_
    the_coverage_guard参照)。しかし`validate_stream`のバッチは常に
    Organizationのrdf:typeを持つはず(provenanceは`validate_stream`を
    経由しない。pipeline.py参照)なので、ここでの「対象0件」は常に異常。
    """
    from rdflib import URIRef

    from jgkg import validate

    # ドリフト検査用の別ベースURI。**IRIを文字列リテラルで直接書かない**
    # (test_validate.pyのDRIFT_BASEと同じ理由: tests/*.py 自体がjgkg.base_uri
    # の整合検査(test_base_uri.py)の対象であり、`/def/`や`/id/`を含む完全な
    # httpsリテラルを書くと「古いドメインが残っている」という誤検知になる)
    drift_base = "https://example.test/drift-kg"
    graph_n3 = URIRef(GRAPH_URI).n3()
    rdf_type = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
    # 現在のbase_uri(https://jgkg.norr-tech.com)ではない別ドメインの名前空間で
    # rdf:typeを名指しする(.envのJGKG_BASE_URIを変えたが生成物を作り直して
    # いない、という実運用の退行を模す)
    drifted_ns = f"{drift_base}/def/org#"
    s = URIRef(f"{drift_base}/id/org/6000012070001").n3()
    line = f'{s} {rdf_type} <{drifted_ns}Organization> {graph_n3} .\n'

    nq_path = tmp_path / "drift.nq"
    nq_path.write_text(line, encoding="utf-8")

    with pytest.raises(ValueError, match="自オントロジーのクラスを1つも"):
        validate.validate_stream(nq_path, _shapes_dir(), tmp_path / "quarantine")


def test_validate_stream_raises_when_a_batch_has_no_rdf_type_triples_at_all(tmp_path):
    """B-2(対象0件ガードの変種2): rdf:typeを1つも含まないバッチも同様に例外にすること。

    stream_emit_organizationsの出力は常にrdf:type行を持つため、これが
    起きるのは壊れた/手書きのN-Quadsに限られる。上のテスト(名前空間drift)
    とは異なる入力形(rdf:type自体が無い)で、同じ「対象0件ガード」に
    到達することを確認する。
    """
    from rdflib import URIRef

    from jgkg import validate
    from jgkg.config import get_settings

    org_ns = f"{get_settings().base_uri}/def/org#"
    graph_n3 = URIRef(GRAPH_URI).n3()
    s = URIRef(org_uri("6000012070001")).n3()
    line = f'{s} <{org_ns}houjinBangou> "6000012070001" {graph_n3} .\n'

    nq_path = tmp_path / "no_type.nq"
    nq_path.write_text(line, encoding="utf-8")

    with pytest.raises(ValueError, match="自オントロジーのクラスを1つも"):
        validate.validate_stream(nq_path, _shapes_dir(), tmp_path / "quarantine")


def test_validate_stream_never_cuts_a_single_contiguous_subject_block_even_past_batch_size(tmp_path):
    """`validate_stream`自身の責務(条件2)を単独で固定する。

    上のテスト(`test_validate_stream_diverges_...`)は**入力側**が条件1
    (1エンティティ連続)を破っている場合の実証だった。こちらは**入力は
    連続している**(1エンティティのブロックが途切れず並んでいる)のに、
    `validate_stream`が`batch_size`だけで機械的に切ってしまうと同じ種類の
    見落としが起きることを、`validate_stream`単体の壊し確認として固定する。

    何があれば落ちるか: バッチ判定が`len(buffer) >= batch_size`だけになり
    「主語が変わったか」を見なくなると、1つの連続ブロック(5行、同一主語に
    2つのprefLabelを含む)が`batch_size=2`でブロックの途中で切られ、
    2つのprefLabelが別バッチに分かれて見落とされる。
    """
    from rdflib import URIRef

    from jgkg import validate
    from jgkg.config import get_settings

    base = get_settings().base_uri
    org_ns = f"{base}/def/org#"
    s1 = URIRef(org_uri("6000012070001")).n3()
    graph_n3 = URIRef(GRAPH_URI).n3()
    rdf_type = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
    pref_label = "<http://www.w3.org/2004/02/skos/core#prefLabel>"

    # 1つの連続ブロック(5行、途切れていない)。dedupが効かずに同じ法人番号の
    # 2行分がそのまま連続して書かれてしまった、という想定のfixture
    lines = [
        f'{s1} {rdf_type} <{org_ns}GovernmentOrgan> {graph_n3} .\n',
        f'{s1} {pref_label} "旧名称"@ja {graph_n3} .\n',
        f'{s1} <{org_ns}houjinBangou> "6000012070001" {graph_n3} .\n',
        f'{s1} <{org_ns}organizationKindCode> "101" {graph_n3} .\n',
        f'{s1} {pref_label} "新名称"@ja {graph_n3} .\n',  # 同じ主語のまま2つ目のprefLabel
    ]
    nq_path = tmp_nq_path()
    nq_path.write_text("".join(lines), encoding="utf-8")

    whole = _whole_graph_conforms(nq_path)
    assert whole is False, "全体一発ではprefLabelが2つでsh:maxCount 1違反になるはず"

    # batch_size=2: 連続ブロックの5行に対して十分小さい。主語の切れ目でしか
    # 切らない実装なら、主語が最後まで変わらないこのファイルは1バッチのまま
    # (=全体一発と同じグラフ)になり、結果は一致するはず
    batched = validate.validate_stream(
        nq_path, _shapes_dir(), tmp_path / "quarantine", batch_size=2
    )
    assert len(batched) == 1, (
        "1つの連続ブロックが複数バッチに分かれた"
        "(主語が変わっていないのにbatch_sizeだけで切っている疑いがある)"
    )
    assert all(r.conforms for r in batched) == whole, (
        "1エンティティの連続ブロックをbatch_size未満で切ってしまい、"
        "全体一発の結果と一致しなくなっている"
    )


def test_validate_stream_gives_a_clear_error_for_a_blank_line_instead_of_unpacking_failure(
    tmp_path,
):
    """O-12: ファイル中に空行が混入していたら、原因の分かるメッセージで落ちること。

    何があれば落ちるか: `_split_nquads_line`のガードを外すと、
    `body.rsplit(" ", 2)`が3要素を返せず`ValueError: not enough values to
    unpack`という、空行が原因だと分からないメッセージに戻る。
    """
    import io

    from jgkg import validate

    org = _org()
    out = io.StringIO()
    stream_emit.stream_emit_organizations(iter([org]), GRAPH_URI, out)
    text = out.getvalue() + "\n"  # 末尾に空行を1本混入させる

    nq_path = tmp_path / "blank_line.nq"
    nq_path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="想定外の空行"):
        validate.validate_stream(nq_path, _shapes_dir(), tmp_path / "quarantine")


def test_validate_stream_raises_instead_of_treating_an_empty_file_as_conforming(tmp_path):
    """空ファイル(0バッチ)を「合格」として返さないこと(§8.2の作法)。

    何があれば落ちるか: `results=[]`をそのまま返す実装だと、呼び出し側が
    `all(r.conforms for r in results)`のような判定をすれば空振りで真になり、
    「対象0件で合格」という、このモジュールが`_assert_shapes_cover`等で
    繰り返し防いでいる退化と同じ形になる。pipeline.py経路では
    `total_organizations == 0`の既存ガードが先に落ちるため実際には
    到達しないが、`validate_stream`は単体でも呼べる関数なので、ここでも
    独立に防ぐ。
    """
    from jgkg import validate

    nq_path = tmp_nq_path()
    nq_path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="1件も検証できなかった"):
        validate.validate_stream(nq_path, _shapes_dir(), tmp_path / "quarantine")


# =============================================================================
# B-1(裁定B23): validate_streamの結果がバッチの違反件数に比例して肥大しないこと。
#
# 8GiB想定構成での実測(レビュー指摘)により、以前の実装は不合格バッチの
# report_text(pyshaclの全文)をそのままResultsに積んでおり、581万件規模で
# メモリが破綻した。ここでは違反200件・2,000件という2つの規模で、
# report_textの長さが**同じ**固定上限に収まることを示す(件数に比例して
# 伸びていないことの直接証拠)。全文が消えていないこと(ディスクに書かれた
# report_pathのファイルを開けば全件見える)も同時に確認する。
# =============================================================================


def _broken_org(i: int) -> Organization:
    """sh:pattern違反(法人番号が不正)を持つOrganizationを、一意なURIで作る。

    `_org()`は`uri`と`houjin_bangou`を同じ値から作るため使えない(それだと
    `org_uri()`の検証自体で例外になる)。ここではURIだけ有効な連番にし、
    houjin_bangouは意図的に不正な値のままにする(既存テストと同じ壊し方)。
    """
    valid_for_uri = str(6_000_000_000_000 + i)
    return Organization(
        uri=org_uri(valid_for_uri),
        houjin_bangou="BROKEN",
        name=f"テスト法人{i}",
        kind_code="301",
        is_government_organ=False,
    )


def _validate_stream_report_for_n_violations(n: int, tmp_path):
    """N件の系統的違反を実経路(stream_emit_organizations)で流し、1バッチで検証する。"""
    import io

    from jgkg import validate

    out = io.StringIO()
    stream_emit.stream_emit_organizations((_broken_org(i) for i in range(n)), GRAPH_URI, out)
    nq_path = tmp_path / "broken.nq"
    nq_path.write_text(out.getvalue(), encoding="utf-8")

    # batch_sizeをNより十分大きくし、N件全部を1バッチにまとめる
    # (1バッチの違反件数が増えてもreport_textが伸びないことを見るのが目的
    # なので、複数バッチに分かれてはならない)
    results = validate.validate_stream(
        nq_path, _shapes_dir(), tmp_path / "quarantine", batch_size=10_000
    )
    assert len(results) == 1, "意図せず複数バッチに分かれた(テストの前提が崩れている)"
    return results[0]


def test_validate_stream_keeps_the_result_summary_bounded_at_200_violations(tmp_path):
    """B-1(裁定B23): 200件の系統的違反でも、report_textが小さい定数に収まること。"""
    from pathlib import Path

    result = _validate_stream_report_for_n_violations(200, tmp_path)

    assert result.conforms is False
    assert result.violation_count == 200, "違反件数が厳密に一致しない"
    assert len(result.report_text) < 3000, (
        f"要約がO(1)でない疑いがある(200件でreport_textが{len(result.report_text)}文字)"
    )
    assert result.report_path is not None, "不合格バッチにreport_pathが埋まっていない"
    full = Path(result.report_path).read_text(encoding="utf-8")
    assert full.count("Constraint Violation") == 200, (
        "全文には200件分の違反がすべて書かれているはず"
        "(要約だけが短いのであって、全文まで欠落してはならない)"
    )


def test_validate_stream_keeps_the_result_summary_bounded_at_2000_violations(tmp_path):
    """B-1(裁定B23): 違反が10倍(2,000件)になっても、report_textの上限は変わらないこと。

    これが本題: 200件と2,000件で**同じ**上限(3,000文字)に収まることを示すのが、
    「バッチの違反件数に比例してメモリが伸びない」ことの直接証拠になる
    (ブロッカーB-1が実測で指摘した、8GiB想定構成での破綻の再現と解消)。
    """
    from pathlib import Path

    result = _validate_stream_report_for_n_violations(2000, tmp_path)

    assert result.conforms is False
    assert result.violation_count == 2000, "違反件数が厳密に一致しない"
    assert len(result.report_text) < 3000, (
        f"要約がO(1)でない疑いがある(2,000件でreport_textが{len(result.report_text)}文字。"
        "200件のときと同じ上限に収まっていない=件数に比例して伸びている)"
    )
    assert result.report_path is not None, "不合格バッチにreport_pathが埋まっていない"
    full = Path(result.report_path).read_text(encoding="utf-8")
    assert full.count("Constraint Violation") == 2000


def tmp_nq_path():
    """テスト用の一時N-Quadsファイルパス(pytestのtmp_pathを使わない軽量版)。

    このファイル内の複数テストで使うヘルパーなので、pytestのtmp_path
    フィクスチャを都度引き渡す代わりに使う。**O-12: 以前は共有ディレクトリに
    手作りの連番でファイルを作っていた** — モジュールレベルのカウンタは
    並行実行(pytest-xdist等の複数プロセス)では各プロセスが別々に0から
    数えるため、同じ名前(`batch-1.nq`等)が競合する余地があった。
    `tempfile.mkstemp`はOSレベルでアトミックに一意な名前を確保するので、
    この競合を構造的に無くす。
    """
    import os
    import tempfile
    from pathlib import Path

    fd, path = tempfile.mkstemp(suffix=".nq", prefix="jgkg-test-stream-emit-")
    os.close(fd)  # 呼び出し側(各テスト)が自分でopen/write_textするので、
    # ここでmkstempが開いたファイルディスクリプタは要らない
    return Path(path)
