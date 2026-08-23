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
_KANJI_NUM = r"[〇一二三四五六七八九十百千]+"

# (元号)(漢数字)年(X)令第…号 の X を取り出す。共管(総理府・大蔵省令 等)は
# X の中に「・」を含む。X が本当に府省(等)の名称かどうかは、この場では
# 判定せず(貪欲/非貪欲の選び方だけで済ませず)、抽出したあとに
# `_looks_like_ministry_segment` で1区分ずつ検査する。これにより
# 「政令」の X="政"、「省令」という語自体、のような偽陽性を、
# 末尾の形(…省/…府/…庁、または「人事院」「閣」そのもの)で弾ける
_ORDINANCE_RE = re.compile(rf"^(?:{_ERA}){_KANJI_NUM}年(.+?)令第.+号$")

# 「(元号)(漢数字)年」を伴わない規則(人事院規則・会計検査院規則 等)。
# 先頭の元号年が付く実例(例:「昭和二十三年人事院規則一―四」のような表記)にも
# 備えて、年の部分は任意にする(実行前スキャンで想定した保守的な拡張)
_RULE_RE = re.compile(rf"^(?:(?:{_ERA}){_KANJI_NUM}年)?(.+?)規則")

_MINISTRY_SUFFIX_RE = re.compile(r".+(?:省|府|庁)$")
_MINISTRY_LITERAL_SEGMENTS = frozenset({"人事院", "閣"})


def _looks_like_ministry_segment(segment: str) -> bool:
    """共管の1区分が府省(等)の名称らしい形をしているか。

    「政令」の X="政" や、万一の空文字列を弾く。人事院・閣は末尾の形が
    共通しない(語そのものが1つの機関名)ので、集合の完全一致で見る。
    """
    if not segment:
        return False
    return segment in _MINISTRY_LITERAL_SEGMENTS or bool(_MINISTRY_SUFFIX_RE.match(segment))


def extract_ministry_names(law_num: str) -> list[str] | None:
    """法令番号の文字列から府省(等)の名称を抜き出す。対象外なら `None`。

    **`law_num_type` ではなく、この文字列だけを正とする**(実測で
    `law_num_type=CabinetOrder` に太政官布告が入る例がある)。

    対象になるのは「(元号)(漢数字)年(X)令第…号」の形(共管は `X` を「・」で
    区切って複数名称を返す)と、「(機関名)規則…」の形(人事院規則・
    会計検査院規則 等。先頭の機関名をそのまま1件として返す)。どちらにも
    当たらない、または `X` が府省(等)の名称らしい形をしていない場合は
    `None`(法律・政令など、経路1の対象外)。
    """
    m = _ORDINANCE_RE.match(law_num)
    if m:
        segments = m.group(1).split("・")
        if all(_looks_like_ministry_segment(s) for s in segments):
            return segments
        return None

    m = _RULE_RE.match(law_num)
    if m:
        name = m.group(1)
        if name:
            return [name]
        return None

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
    reason: str  # OLD_MINISTRY / NO_CANDIDATE / AMBIGUOUS


class JurisdictionResult(BaseModel):
    law_id: str
    ministry_names: list[str]  # 法令番号から抽出した名称(共同省令は複数)
    resolved: list[str]  # 解決できた府省の法人番号
    unresolved: list[UnresolvedJurisdiction]


def derive_jurisdiction(
    record: LawRecord,
    reference: Mapping[str, list[Ministry]],
    old_ministries: set[str],
) -> JurisdictionResult | None:
    """法令番号から府省を導く(経路1)。

    `None` は経路1の対象外(法令番号に府省名を含まない法律・政令など)。
    対象内であれば、抽出した名称は**必ず** `resolved` か `unresolved` の
    どちらかに振り分ける(§8.2「解決できた分だけ返す」設計にしない —
    このタスクで踏みやすい欠陥の型の2番目)。

    分類の優先順位:
      1. 参照表に同名が正確に1件 → `resolved`(法人番号を積む)
      2. 参照表に同名が2件以上 → `AMBIGUOUS`(実行前スキャンで見つかった
         Step 3 の要求。反対に0件のときは3へ進む)
      3. 旧省庁名の判定集合に載っている → `OLD_MINISTRY`
      4. どちらでもない → `NO_CANDIDATE`

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
        else:
            unresolved.append(UnresolvedJurisdiction(name=name, reason="NO_CANDIDATE"))

    return JurisdictionResult(
        law_id=record.law_id,
        ministry_names=names,
        resolved=resolved,
        unresolved=unresolved,
    )


__all__ = [
    "JurisdictionResult",
    "LawRecord",
    "Revision",
    "UnresolvedJurisdiction",
    "derive_jurisdiction",
    "extract_ministry_names",
    "parse_laws",
    "to_ministry_reference",
]
