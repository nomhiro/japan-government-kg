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
    for org in source():
        key = int(org.houjin_bangou)
        if key in seen:
            duplicated.add(key)
        else:
            seen.add(key)
    del seen  # 大きい構造は使い終わったら即解放する(2パス目には持ち越さない)

    pending: dict[int, Organization] = {}
    dup_occurrences = 0
    for org in source():
        stats.rows_in += 1
        key = int(org.houjin_bangou)
        if key not in duplicated:
            yield org
            continue
        dup_occurrences += 1
        current = pending.get(key)
        if current is None or org.updated_on >= current.updated_on:
            pending[key] = org

    stats.dedup_removed += dup_occurrences - len(pending)
    yield from pending.values()
