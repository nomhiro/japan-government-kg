"""全法人(581万件規模)のストリーミング投入。rdflib の Dataset を使わない。

**なぜ Dataset を使わないか**: `emit.py` の `emit_organizations` は Pydantic モデルを
一度 rdflib の `Dataset` に足してから `serialize()` する。全法人(約3,500万トリプル)
規模ではこの `Dataset` 自体が破綻する(R19/R21 の教訓、task-8-brief.md)。
ここでは N-Quads の行を1行ずつ直接テキストとして書き出す。IRI/リテラルの
エスケープだけは rdflib の `URIRef.n3()` / `Literal.n3()` を1行単位で借用する
(オブジェクトを Graph/Dataset に足さない限り、これらはメモリに何も蓄積しない)。

**バッチSHACLが全体検証と等価である条件(このモジュールの中心の論証)**:
本設計のSHACLシェイプはエンティティ局所(閉じたNodeShape。エンティティを跨ぐ
制約はR2で裁定済みに排除されている)。したがって、同一主語の全トリプルが
同じバッチに入っていれば、バッチ単位の検証結果の合併は全体検証と一致する。
これを成立させる3条件と、この関数群での担保の仕方:

1. `stream_emit_organizations` は1エンティティの全トリプルを連続して書く
   (このモジュールの実装そのもの — 1件の `Organization` を丸ごと処理してから
   次に進むループ構造で保証する)。
2. バッチ境界は主語の切れ目でのみ切る(`validate.validate_stream` 側の責務)。
3. 同一法人番号の重複はバッチを跨ぐと検出できないため、上流(`dedup_organizations`)
   で弾く。重複した2行がそれぞれ別バッチに入ると、各バッチは単独では
   `skos:prefLabel` を1つしか見ないため両方が個別に合格してしまい、
   全体でのみ見える `sh:maxCount 1` 違反を検出できない。
"""
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import IO

from rdflib import RDF, Literal, URIRef
from rdflib.namespace import SKOS

from jgkg.config import get_settings
from jgkg.transform.organization import Organization


@dataclass
class StreamStats:
    """ストリーミング投入1回分の内訳。**判定に使って捨てるのではなく報告する**

    (organization.ParseStats と同じ作法)。`dedup_organizations` が
    `rows_in`/`dedup_removed` を、`stream_emit_organizations` が
    `entities`/`triples` を埋める。呼び出し側(pipeline.py)がこれを
    `PipelineReport` に合流させる(消費者の無い記録を残さない)。
    """

    rows_in: int = 0        # dedup前に見た件数(dedup_organizations経由の入力行数)
    dedup_removed: int = 0  # 法人番号の重複により弾いた行数(残す1件は含まない)
    entities: int = 0       # 実際にN-Quadsへ書き出したエンティティ数
    triples: int = 0        # 実際に書き出したトリプル数


def dedup_organizations(
    source: Callable[[], Iterator[Organization]], stats: StreamStats
) -> Iterator[Organization]:
    """法人番号の重複を「後勝ち」(更新年月日が新しい方)で解消する。

    **なぜ`source`が呼び出し可能(2回呼べるもの)であって`Iterator`そのものでは
    ないか**: 「後勝ち」は更新年月日の値そのもので決まり、ファイル中の出現順
    ではない。単一パスの途中で「この法人番号はまだ重複するかもしれない」を
    判定できないため、勝者を確定するには全件を見る必要がある。しかし
    5.8M件の`Organization`(名称・住所などの文字列を持つ)を1件残らず
    メモリに保持するのはR19/R21が禁じる全件蓄積そのものなので、代わりに
    **2パス**で処理し、大きい方の構造(1パス目の`seen`)を軽量(int化した
    法人番号のみ)に留める:

    - 1パス目: `source()`を最後まで読み、法人番号(int化)だけで
      「重複しているキー」の集合`duplicated`を作る。ここで唯一大きくなる
      のは全件分の`seen`(集合)だが、法人番号のintだけなので約5.8M件でも
      ~500MB程度(このモジュールのテスト`test_dedup_seen_set_memory_budget_
      is_within_the_phase1_budget`で実測して見積もる)。**この`seen`は
      1パス目の終わりで使い終わるので明示的に破棄する。**
    - 2パス目: `source()`をもう一度読む。`duplicated`に無いキーは
      重複が無いと確定しているので即座にyieldする(バッファしない)。
      `duplicated`にあるキーだけを小さい辞書`pending`に保持し、
      より新しい`updated_on`が来るたびに勝者を更新する。`pending`のサイズは
      「実際に重複していたキーの数」に留まり、全件数(5.8M)には比例しない
      (実データでの重複はB18のセンチネルのような例外的な行に限られる想定)。
      ストリーム終端で`pending`の勝者をまとめてyieldする。

    **タイブレーク**: `updated_on`が完全に同値の場合は、出現順で後に来た方を
    勝者にする(`>=`比較)。これにより結果は`source()`の反復順序に対して
    決定的になる(setの反復順序には依存しない — `pending`はdictなので
    挿入順を保つ)。

    **`updated_on`が空文字(不明)の行の扱い(O-9)**: 特別扱いをせず、
    他のあらゆる値と同じ文字列比較(`>=`)に委ねる。空文字はISO日付文字列
    より辞書順で必ず小さい(`"" < "2018-04-02"`)ため、この既定の比較だけで
    次の2つの振る舞いが自然に得られる: (1) 空文字と実在の日付が競合すれば
    出現順に関わらず**実在の日付が勝つ**(空文字は実質的に「最古」として
    振る舞う — `Organization.updated_on`のdocstringに既にある注記の通り)。
    (2) 重複が**全件**空文字なら、上のタイブレーク規則がそのまま適用され
    出現順で最後の行が勝つ。空文字を`None`扱いで特別分岐させたり、
    行自体を棄却したりはしない — 全件CSVの実データでは`updated_on`が
    空になることは想定していない(列[4]は必須項目)が、想定外の値が来ても
    決定的な結果を返すことを優先する。

    **RSのセンチネル(B18: houjin_bangou="9999999999999")との無関係の明示**:
    ここでの「重複」は法人番号が実際に一致する行同士の重複であり、RS側の
    支出先センチネル(識別不能な支出先を表す合成法人番号)とは無関係の概念。
    実データ(zenken.zip)にセンチネル値は出現しない(実測0件。task-8-brief.md
    引き継ぐ決定)ため、このdedupがセンチネルを特別扱いする必要も無い。

    `stats.rows_in`/`stats.dedup_removed`は2パス目でのみ加算する(1パス目では
    `stats`に触れない)。呼び出し側が`source`のクロージャに`ParseStats`等の
    別の蓄積オブジェクトを閉じ込めて2回呼び出す構成にすると、そちらは
    2回分加算されてしまう点に注意(pipeline.py側の結線で踏まないよう、
    そちら側にも同じ注意をコメントで残す)。
    """
    seen: set[int] = set()
    duplicated: set[int] = set()
    pass1_count = 0
    for org in source():
        pass1_count += 1
        key = int(org.houjin_bangou)
        if key in seen:
            duplicated.add(key)
        else:
            seen.add(key)
    del seen  # 大きい構造は使い終わったら即解放する(2パス目には持ち越さない)

    pending: dict[int, Organization] = {}
    dup_occurrences = 0
    pass2_count = 0
    for org in source():
        pass2_count += 1
        stats.rows_in += 1
        key = int(org.houjin_bangou)
        if key not in duplicated:
            yield org
            continue
        dup_occurrences += 1
        current = pending.get(key)
        if current is None or org.updated_on >= current.updated_on:
            pending[key] = org

    # **F-4(b): source()が2回とも同じ内容を返すという2パス方式の前提を検査する。**
    # 行数の一致は鳴子であって内容のハッシュではない — 同じ件数のまま内容が
    # 入れ替わる、より巧妙な不一致(TOCTOU)まではここでは検出できないが、
    # そのケースはvalidate_stream側の非隣接主語再出現の検査が別途捕まえる
    # (二段構え)。ここでは最も基本的な破れ(件数そのものが変わる)を固定する。
    # 2パス目の途中でこの不一致を検出することはできない(1パス目の総数は
    # 2パス目が終わるまで意味を持たない)ため、両方のループを終えた後で
    # まとめて検査する
    if pass2_count != pass1_count:
        raise ValueError(
            f"dedup_organizationsの1パス目({pass1_count}件)と2パス目"
            f"({pass2_count}件)で件数が一致しない。source()が呼び出しごとに"
            "異なる内容を返している疑いがある — 2パス方式はsource()が2回とも"
            "同じ内容を返すことを前提にしている(このモジュールのdocstring"
            "参照)。件数が食い違うと、1パス目のduplicated判定が2パス目の"
            "実データと食い違い、同一主語が非隣接に複数回yieldされる恐れがある"
        )

    stats.dedup_removed += dup_occurrences - len(pending)
    yield from pending.values()


def _org_ns() -> str:
    return f"{get_settings().base_uri}/def/org#"


def _n3_line(*terms: str) -> str:
    """N-Quadsの1行を組み立てる。**改行を含む項があれば例外にする。**

    rdflib の `Literal.n3()` は、値に生の改行が含まれると Turtle/N3 の
    三重引用符による複数行リテラル形式(値の改行をエスケープせずそのまま
    埋め込む表現)を返すことがある(実測で確認済み: 改行を含む文字列に
    `Literal(...).n3()` を呼ぶと、閉じ引用符が3文字連続する複数行の文字列に
    なる — Pythonオブジェクトとしては1個のstrだが、書き出すと実際に複数の
    物理行になる)。これはN-Quads(1行=1トリプル)の文法ではなく、
    `validate_stream` の「行単位でバッチに切る」実装が前提にする不変条件を
    静かに破る。データにこの想定外が来たら、沈黙して壊れたストリームを
    書くのではなく、ここで例外にする(§8.2「沈黙させない」)。
    """
    line = " ".join(terms) + " .\n"
    if "\n" in line[:-1] or "\r" in line:
        raise ValueError(
            f"N-Quadsの1行に想定外の改行が入り込んだ(生データに改行文字がある疑い): {line!r}"
        )
    return line


def _organization_lines(org: Organization, graph_n3: str) -> Iterator[str]:
    """1件の`Organization`が持つ全トリプルをN-Quadsの行として順に返す。

    `emit.emit_organizations`(Dataset経由)と**同じ述語集合・同じ条件**を
    保つ(GovernmentOrgan/Organizationの型選択、prefecture/cityは値がある
    ときだけ)。ここで1件のOrganizationの行を全部返し切ってから
    `stream_emit_organizations`が次のOrganizationに進むループ構造そのものが、
    「1エンティティの全トリプルを連続して書く」(等価性の条件1)を保証する。
    """
    s = URIRef(org.uri).n3()
    ns = _org_ns()
    most_specific = "GovernmentOrgan" if org.is_government_organ else "Organization"

    yield _n3_line(s, RDF.type.n3(), URIRef(ns + most_specific).n3(), graph_n3)
    yield _n3_line(s, SKOS.prefLabel.n3(), Literal(org.name, lang="ja").n3(), graph_n3)
    yield _n3_line(s, URIRef(ns + "houjinBangou").n3(), Literal(org.houjin_bangou).n3(), graph_n3)
    yield _n3_line(
        s, URIRef(ns + "organizationKindCode").n3(), Literal(org.kind_code).n3(), graph_n3
    )
    if org.prefecture:
        yield _n3_line(
            s, URIRef(ns + "prefectureName").n3(), Literal(org.prefecture, lang="ja").n3(), graph_n3
        )
    if org.city:
        yield _n3_line(
            s, URIRef(ns + "cityName").n3(), Literal(org.city, lang="ja").n3(), graph_n3
        )


def stream_emit_organizations(
    orgs: Iterator[Organization], graph_uri: str, out: IO[str], stats: StreamStats | None = None
) -> StreamStats:
    """`orgs` を`graph_uri`という名前付きグラフのN-Quadsとして`out`に直接書く。

    **rdflib の Dataset/Graph に貯めない**(全法人規模でメモリが破綻する。
    モジュールdocstring参照)。IRI/リテラルのエスケープだけ`URIRef.n3()`/
    `Literal.n3()`を1行単位で借用する(`_organization_lines`)。

    1件の`Organization`ごとに、その全トリプルを続けて`out.write()`してから
    次の`Organization`に進む(このループ構造そのものが「1エンティティの
    全トリプルを連続して書く」という、バッチ=全体の等価性の条件1を満たす)。

    **`orgs`の入力順をそのまま出力順にする(ソートしない)。** (F-7)
    ソートしない判断の理由は2つ: (1) 5.8M件をソートするコストは
    条件1(1エンティティ連続)を満たすために本質的には不要 — 入力順の
    まま書けば条件1は保たれる。ソートは「バッチ境界を主語で揃える」ための
    唯一の手段ではない(validate.validate_streamが行単位で主語の切れ目を
    見て動的にバッチを切るので、事前に主語順へソートしておく必要は無い)。
    (2) グラフの同一性はトリプル集合として比較されるものであり(RDFに
    行順の意味論は無い)、N-Quadsファイル内の行順そのものに検証結果を
    左右する意味は無い — 唯一意味を持つのは「1エンティティの範囲が
    連続していること」で、それは入力順を保つだけで満たされる。
    この判断はテストで固定する(決定性の要件。
    test_stream_emit_writes_each_entitys_triples_contiguously参照)。

    `stats`を渡すと(渡さなければ内部で新規に作る)、`entities`/`triples`を
    この呼び出し分だけ加算して返す。`dedup_organizations`と同じ`StreamStats`
    を渡せば、dedupの`rows_in`/`dedup_removed`と合流した1つの報告になる
    (pipeline.py の結線)。
    """
    st = stats if stats is not None else StreamStats()
    graph_n3 = URIRef(graph_uri).n3()

    for org in orgs:
        for line in _organization_lines(org, graph_n3):
            out.write(line)
            st.triples += 1
        st.entities += 1
    return st
