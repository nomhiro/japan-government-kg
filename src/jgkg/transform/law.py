"""法令番号からの府省導出(経路1)。設計書§7.2。

**決定的な文字列処理のみ。LLMも曖昧照合(名寄せ)も使わない。** 法令番号は
e-Gov法令APIが管理する構造化された文字列であり、揺れを許容する必要が無い
(§7.2「経路1は決定的」)。

`law_num_type`(APIが返す分類ラベル)は信用しない。実データで太政官布告が
`CabinetOrder` に分類されている例を確認済み(`connectors/egov_law.py` 参照)。
ここでは `law_num` の文字列そのものだけを正として分類する。
"""
import json
import re
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from jgkg.transform.ministry import Ministry

# =============================================================================
# 抽出: 法令番号の文字列 → 府省(等)名のリスト
# =============================================================================

_ERA = "令和|平成|昭和|大正|明治"
# 「元」(元年)を含む。無いと「令和元年○○省令」のような表記が年を認識できず
# 経路1の対象から静かに消える(レビュー指摘1)
_KANJI_NUM = r"[〇一二三四五六七八九十百千元]+"

# (元号)(漢数字)年(X)令第…号 の X を取り出す。共管(総理府・大蔵省令 等)は
# X の中に「・」を含む。X が本当に府省(等)の名称かどうかは、この場では
# 判定せず(貪欲/非貪欲の選び方だけで済ませず)、抽出したあとに
# `_looks_like_government_organ` で1区分ずつ検査する。これにより
# 「政令」の X="政"、「省令」という語自体、のような偽陽性を、
# 末尾の形(…省/…府/…庁/…院/…委員会、または「人事院」「閣」そのもの)で弾ける。
# 末尾は `号第…号の二` のような分岐番号にも備える(レビュー指摘2-2。
# 「の」+漢数字の繰り返しを許す)
_ORDINANCE_RE = re.compile(rf"^(?:{_ERA}){_KANJI_NUM}年(.+?)令第.+号(?:の{_KANJI_NUM})*$")

# 先頭の元号年接頭辞(あれば)だけを剥がすための式。「規則」を伴う本体の
# パターンとは別に持つ理由は下記 `extract_ministry_names` のコメント参照
_ERA_YEAR_PREFIX_RE = re.compile(rf"^(?:{_ERA}){_KANJI_NUM}年")

# 元号年接頭辞を剥がした**あとの**文字列に対して「(機関名)規則…」を取る
# (人事院規則・会計検査院規則 等。先頭の機関名をそのまま1件として返す)
_RULE_RE = re.compile(r"^(.+?)規則")

# 政府機関(等)の名称らしい形。「省/府/庁」だけでは国家公安委員会・会計検査院
# のような合議体・検査機関を機関名と認識できず、共管の一部にこれらが混ざると
# 共管全体(解決できる区分まで)が抽出失敗になっていた(レビュー指摘2-1)。
# B7(旧省庁→OLD_MINISTRY/OBSOLETE_ORGANIZATION/NO_CANDIDATEの3分類)の
# 「政府機関の形」判定もこの関数を共有する
_GOVERNMENT_ORGAN_SUFFIX_RE = re.compile(r".+(?:省|府|庁|院|委員会)$")
_MINISTRY_LITERAL_SEGMENTS = frozenset({"人事院", "閣"})


def _looks_like_government_organ(segment: str) -> bool:
    """文字列が政府機関(等)の名称らしい形をしているか。

    「政令」の X="政" や、万一の空文字列を弾く。人事院・閣は末尾の形が
    共通しない(語そのものが1つの機関名)ので、集合の完全一致で見る
    (「人事院」は「院」で終わるため実質的には末尾一致でも拾えるが、
    「閣」は単独字でこの判定にしか乗らない)。
    """
    if not segment:
        return False
    return (
        segment in _MINISTRY_LITERAL_SEGMENTS
        or bool(_GOVERNMENT_ORGAN_SUFFIX_RE.match(segment))
    )


class ExtractionFailed:
    """`extract_ministry_names` が「府省令・規則の形をしているのに名称を
    抽出できなかった」ことを表す番兵(レビュー指摘2)。

    `None`(経路1の対象外。法律・政令など)と衝突しない、明確に区別できる
    第3の値が必要だったため、単純な`bool`や文字列ではなく専用の型にした。
    件数の集計は呼び出し側が `is EXTRACTION_FAILED` で判定して行う。

    **この forward reference はTask 7で訂正した(元は「将来のTask 7で
    pipelineに法令を繋いだ時点」と書いていた)**: Task 7はbudgetモジュールの
    範囲であり、egov-lawのpipeline.pyへの結線はTask 7の対象外と判明した
    (egov-lawはこのリポジトリのレイクに実データが無く、Task 7はネットワークを
    使えないため取得もできない。test_pipeline.pyの既存コメント「法令を流す
    pipelineへの結線はTask 4の範囲外(Task 7/9/11)」、およびこの計画書の
    Task 11「統合 — 実データの全経路実行と実測」を参照)。この分類分けの
    件数集計は、egov-lawがpipelineに実際に繋がるタスク(Task 9/11)が行う。
    """

    __slots__ = ()

    def __repr__(self) -> str:
        return "EXTRACTION_FAILED"


EXTRACTION_FAILED = ExtractionFailed()


def extract_ministry_names(law_num: str) -> list[str] | None | ExtractionFailed:
    """法令番号の文字列から府省(等)の名称を抜き出す。

    **`law_num_type` ではなく、この文字列だけを正とする**(実測で
    `law_num_type=CabinetOrder` に太政官布告が入る例がある)。

    戻り値は3値(レビュー指摘2で`None`の二義性を解消した):

    - `list[str]`: 抽出に成功した名称(共管は複数件)
    - `None`: 経路1の対象外(法律・政令など)。「(元号)年+1文字の区分+
      令第…号」の形は、政令(区分="政")のように**既知の非府省令が
      たまたま同じ正規表現に一致する**唯一のパターンなので、区分が
      1文字かつ政府機関の形をしていない場合だけ`None`にする
      (実測で確認できたのは政令のみ。Task 11の実データで他の形が
      現れないか確認する)
    - `ExtractionFailed`(`EXTRACTION_FAILED`): 「(元号)年+…+令第…号」
      または「規則」の形をしているのに、名称が政府機関らしい形を
      していない(2文字以上)、または規則の直前に名称が無い場合。
      未知の表記で静かに`None`へ吸収されるのを防ぐための状態

    対象になるのは「(元号)(漢数字)年(X)令第…号」の形(共管は `X` を「・」で
    区切って複数名称を返す)と、「(機関名)規則…」の形(人事院規則・
    会計検査院規則 等。先頭の機関名をそのまま1件として返す。元号年の
    接頭辞が付く表記にも備え、その接頭辞を先に剥がしてから名称を取る —
    剥がさずに`(?:年接頭辞)?(.+?)規則`と書くと、接頭辞が任意である
    ことの正規表現の後戻りにより、年号そのものが名称として誤って
    採用される。レビュー指摘6の実測で確認済み)。
    """
    m = _ORDINANCE_RE.match(law_num)
    if m:
        segments = m.group(1).split("・")
        if all(_looks_like_government_organ(s) for s in segments):
            return segments
        if len(segments) == 1 and len(segments[0]) == 1:
            return None
        return EXTRACTION_FAILED

    remainder = _ERA_YEAR_PREFIX_RE.sub("", law_num, count=1)
    m = _RULE_RE.match(remainder)
    if m:
        # 最終レビュー要修正3(裁定B41): 共管(「・」区切り)は令の経路と同じく
        # 分割する。修正前は`[m.group(1)]`のまま返していたため、複数機関の
        # 共管規則が「連結された1つの機関名」になっていた(実測: 13機関の
        # 共管規則2件が該当。data/lake/egov-law/2026-08-24/laws.jsonlの
        # law_id 430M602A1FDA001/503M602A1FDA002)。
        #
        # **令の経路とは違い、ここでは`all(_looks_like_government_organ(...))`
        # ゲートを掛けない。** 令の経路がそのゲートを持つ理由は、正規表現の
        # 曖昧さ(「政令」の「政」を機関名区分と誤認する)を切り分けるためで、
        # 「規則」という語は曖昧さが無く区切りとして十分はっきりしている。
        # ゲートを掛けると、政府機関の形をしていない規則名(1区分。例:
        # 「ダミー機関規則」)が`EXTRACTION_FAILED`に変わり、
        # `derive_jurisdiction`が本来ここに割り振るはずのNO_CANDIDATE分類
        # (schema/core.yamlの定義そのもの「政府機関の形にも当たらない」)に
        # 到達できなくなる——既存の
        # `test_derive_jurisdiction_classifies_non_organ_shaped_name_as_no_candidate`
        # がこの設計を固定している。ゲート無しでの単一機関(人事院規則・
        # 会計検査院規則)への影響も無い(「・」を含まない文字列の
        # `.split("・")`は要素1件のリストを返すため)。
        return m.group(1).split("・")
    if remainder.startswith("規則"):
        # 元号年接頭辞(あれば剥がした)の直後に「規則」が続き、名称が無い
        return EXTRACTION_FAILED

    return None


# =============================================================================
# laws.jsonl(Task 3 の egov-law コネクタの出力)の正規化
# =============================================================================


class Revision(BaseModel):
    """1件の改正情報(`revision_info` 相当)。`law:LawRevision` に対応する。"""

    amendment_law_num: str | None = None
    amendment_enforcement_date: str | None = None
    revision_status: str = ""


class LawRecord(BaseModel):
    """`laws.jsonl` の1行(`law_info` + `revision_info` + `current_revision_info`)
    を正規化したもの。"""

    law_id: str
    law_num: str
    law_num_type: str
    law_type: str
    law_title: str
    abbrev: list[str]
    promulgation_date: str
    repeal_status: str
    revisions: list[Revision]


def _as_str_list(value: Any) -> list[str]:
    """`abbrev` の正規化。

    `law.yaml` の説明は「0件以上の複数件があり得る」だが、実データ
    (`tests/fixtures/egov_laws_page*.json`)は単一の文字列かnullしか
    観測できていない(コネクタのfixture収録がその範囲のため)。将来
    複数件の配列で返ってきた場合にも対応できるよう、両方の形を受ける
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value]


def _revision_from(info: Mapping[str, Any] | None) -> Revision | None:
    if not info:
        return None
    return Revision(
        amendment_law_num=info.get("amendment_law_num"),
        amendment_enforcement_date=info.get("amendment_enforcement_date"),
        revision_status=info.get("current_revision_status") or "",
    )


def parse_laws(path: Path) -> Iterator[LawRecord]:
    """`laws.jsonl`(1行1法令。`law_info`/`revision_info`/`current_revision_info`
    を持つJSONオブジェクト)を1行ずつ `LawRecord` にする。

    題名・略称・廃止状態は **`current_revision_info` を正とする**
    (`revision_info` は「この行が対応する改正」の情報。今のコネクタは
    APIから返る現在の改正情報しか取っていないため実データでは両者は同一だが、
    意味的には `current_revision_info` が法令の「現在の」状態を表す。
    fixtureでは検証できない前提であることをここに明記する)。

    法人番号CSVと違い、laws.jsonl は法令1件あたり数KBで全件でも数十MB程度
    (§Task 3 実測: MinisterialOrdinance 4,431件)なので、行単位でストリーミング
    しつつ `json.loads` する(全件を先に読み切ってメモリに載せない)。
    """
    with path.open("r", encoding="utf-8", errors="strict") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            law = json.loads(line)
            info = law["law_info"]
            current = law.get("current_revision_info") or {}
            revision = _revision_from(law.get("revision_info"))
            yield LawRecord(
                law_id=info["law_id"],
                law_num=info["law_num"],
                law_num_type=info["law_num_type"],
                law_type=info["law_type"],
                law_title=current.get("law_title") or "",
                abbrev=_as_str_list(current.get("abbrev")),
                promulgation_date=info["promulgation_date"],
                repeal_status=current.get("repeal_status") or "",
                revisions=[revision] if revision is not None else [],
            )


# =============================================================================
# 解決: 抽出した名称 → 現存府省の法人番号 / 未解決(理由付き)
# =============================================================================


def to_ministry_reference(ministries: Iterable[Ministry]) -> dict[str, list[Ministry]]:
    """`ministry.build()` の出力(`list[Ministry]`)を名称でグループ化する。

    **単純な `{m.name: m for m in ministries}` にはしない。** それでは同名が
    複数ある場合に最後の1件で上書きされ、AMBIGUOUS を検出できなくなる
    (実行前スキャンで見つからなかった不整合 — ブリーフ本文は
    `dict[name, Ministry]` と書くが、Step 3 が要求する「参照表に同名2行→
    AMBIGUOUS」はこの形では表現できない。値を `list[Ministry]` にして
    件数で判定できるようにした)。
    """
    ref: dict[str, list[Ministry]] = {}
    for m in ministries:
        ref.setdefault(m.name, []).append(m)
    return ref


class UnresolvedJurisdiction(BaseModel):
    name: str  # 法令番号から抽出した名称(そのまま core:unresolved_key になる)
    reason: str  # OLD_MINISTRY / OBSOLETE_ORGANIZATION / NO_CANDIDATE / AMBIGUOUS


class JurisdictionResult(BaseModel):
    law_id: str
    ministry_names: list[str]  # 法令番号から抽出した名称(共同省令は複数)
    resolved: list[str]  # 解決できた府省の法人番号
    unresolved: list[UnresolvedJurisdiction]


def derive_jurisdiction(
    record: LawRecord,
    reference: Mapping[str, list[Ministry]],
    old_ministries: set[str],
) -> JurisdictionResult | None | ExtractionFailed:
    """法令番号から府省を導く(経路1)。

    戻り値は3値(`extract_ministry_names` の3値をそのまま引き継ぐ):

    - `None`: 経路1の対象外(法令番号に府省名を含まない法律・政令など)
    - `ExtractionFailed`(`EXTRACTION_FAILED`): 府省令・規則の形をしているのに
      名称を抽出できなかった(レビュー指摘2)。件数の集計は呼び出し側が
      `is EXTRACTION_FAILED` で判定して行う(egov-lawがpipelineに実際に
      繋がった時点で`PipelineReport`に載せる。**Task 7で訂正**: 当初この
      docstringは「Task 7でpipelineに法令を繋いだ時点」と書いていたが、
      Task 7の対象はbudgetモジュールであり、egov-lawをpipeline.pyへ結線する
      ことはTask 7の範囲外と判明した(レイクに実データが無く、Task 7は
      ネットワークを使えない。test_pipeline.pyの既存コメントの通りTask 7/9/11
      で分担する。全経路の実行と実測はTask 11)。現時点でもlawはpipeline
      未結線のままなので、ここでは戻り値を区別できる形にするところまでを行う)
    - `JurisdictionResult`: 対象内。抽出した名称は**必ず** `resolved` か
      `unresolved` のどちらかに振り分ける(§8.2「解決できた分だけ返す」
      設計にしない — このタスクで踏みやすい欠陥の型の2番目)

    分類の優先順位(レビュー指摘3・裁定B7で3〜4を分割):
      1. 参照表に同名が正確に1件 → `resolved`(法人番号を積む)
      2. 参照表に同名が2件以上 → `AMBIGUOUS`(実行前スキャンで見つかった
         Step 3 の要求。反対に0件のときは3へ進む)
      3. 旧省庁名の判定集合(`old-ministries.csv`。**2001年の中央省庁再編で
         廃止された名称に限る**)に載っている → `OLD_MINISTRY`
      4. 参照表にも旧省庁名の判定集合にも無いが、政府機関の形
         (`_looks_like_government_organ`。省/府/庁/院/委員会で終わる、
         または人事院/閣)をしている → `OBSOLETE_ORGANIZATION`
         (2001年より前に廃止された省庁名など。列挙を増やさず形で導出する
         — 明治以来の官庁は無限に近く、旧省庁の継承マッピングをPhase 2へ
         送ったのと同じ理由で列挙をやめた)
      5. どちらでもない → `NO_CANDIDATE`(政府機関の形にすら見えない。
         抽出そのものを疑うべき警報。3・4に該当しないここに残るのは、
         抽出段の誤りか、本当に未知の名称かのいずれか)

    `reference`(現存府省)と `old_ministries`(旧省庁名の判定集合)は、
    呼び出し側が事前に読み込んで**毎回渡す**。関数内で毎回ファイルを
    読み直すと、実データ(法令 数千件)に対して呼ぶたびにディスクI/Oが走る
    (`ministry.build()` の出力を渡す既存の呼び方と同じ理由で、副作用のある
    I/Oを純粋な変換関数に持ち込まない)。ブリーフ本文の署名は
    `(record, reference)` の2引数だが、`old_ministries` を無しに
    OLD_MINISTRY の判定はできないため、明示的な第3引数として追加した
    (このタスクで確定した、ブリーフ本文からの意図的な逸脱)。
    """
    names = extract_ministry_names(record.law_num)
    if names is None:
        return None
    if names is EXTRACTION_FAILED:
        return EXTRACTION_FAILED

    resolved: list[str] = []
    unresolved: list[UnresolvedJurisdiction] = []

    for name in names:
        matches = reference.get(name, [])
        if len(matches) == 1:
            resolved.append(matches[0].houjin_bangou)
        elif len(matches) > 1:
            unresolved.append(UnresolvedJurisdiction(name=name, reason="AMBIGUOUS"))
        elif name in old_ministries:
            unresolved.append(UnresolvedJurisdiction(name=name, reason="OLD_MINISTRY"))
        elif _looks_like_government_organ(name):
            unresolved.append(
                UnresolvedJurisdiction(name=name, reason="OBSOLETE_ORGANIZATION")
            )
        else:
            unresolved.append(UnresolvedJurisdiction(name=name, reason="NO_CANDIDATE"))

    return JurisdictionResult(
        law_id=record.law_id,
        ministry_names=names,
        resolved=resolved,
        unresolved=unresolved,
    )


__all__ = [
    "EXTRACTION_FAILED",
    "ExtractionFailed",
    "JurisdictionResult",
    "LawRecord",
    "Revision",
    "UnresolvedJurisdiction",
    "derive_jurisdiction",
    "extract_ministry_names",
    "parse_laws",
    "to_ministry_reference",
]
