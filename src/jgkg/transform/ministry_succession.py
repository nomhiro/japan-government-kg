"""旧省庁→新府省の継承マッピングを法令の対応表(Table)から抽出する(C-1)。

未解決の所管2,272件のうち1,995件(87.8%)が `OLD_MINISTRY`(旧省庁名。
`old_ministries.py` 参照)のまま留め置かれている。ここではその一部を解決
できるようにするため、法令の条文に**そのまま入っている対応表**
(`412CO0000000315`「従前の府省等の相当の新府省等を定める政令」)から
旧→新のマッピングを抽出する。

**このモジュールが「してはならないこと」: ツリー上の位置を手書きで
焼き込むこと。** このプロジェクトで最も再発している欠陥は「導出すべき
値を手書きしている」(公開物検査のモジュール一覧・乗数・除外リスト・
エラー文言中のパス・CQ8の日付・ministry-codesの日付検査・`--target` の
7件)であり、法令本文ツリーの中の対応表の位置
(実測: `law_full_text.children[1].children[2].children[1].children[2]
.children[2].children[0]`)を直接書くことは8件目の同じ欠陥になる。

代わりに次の2段で「導出」する:
1. ツリーを再帰的に走査して `tag == "Table"` のノードを**すべて**見つける
2. 見つかった各Tableについて、先頭行(ヘッダ)の文言に「従前」を含む列と
   「新」を含む列がそれぞれちょうど1つあるかを見て、対応表として使える
   Tableを同定する。**列の位置(0番目=旧、1番目=新)を仮定しない**——
   ヘッダの文言だけから列の意味を確定する。法令が改正されて列の順序が
   入れ替わっても、ヘッダ文言が変わらなければ動作し続ける

抽出後の18名称(`data/reference/old-ministries.csv`)への解決についても
同じ発想を使う。実データを確認すると、59行のうち8行
(例:「総理府北海道開発庁」「総理府金融再生委員会」)は
「総理府」+外局名を**区切り文字なしで連結した**形をしている(2001年改革
前、これらの庁・委員会は総理府の外局だった実際の行政組織上の事実)。
この「総理府」という接頭辞を決め打ちの文字列として持たない——
`old-ministries.csv` の18名称の集合そのものを接頭辞の候補として使い、
「対象名Aが対象名Bを先頭から取り除いた残りと一致する」形で導出する
(ヘッダ文言から列の意味を導出するのと同じ「既存の参照データから導出する」
という発想の繰り返し)。
"""
import dataclasses
import re
from collections.abc import Iterator

_OLD_HEADER_MARKER = "従前"
_NEW_HEADER_MARKER = "新"

# 実データで確認した括弧限定の形(全角（）・半角()、入れ子なし、末尾に1箇所)
# のみを扱う。例:「大蔵省(造幣局、印刷局及び国税庁を除く。)」→「大蔵省」
_TRAILING_QUALIFIER_RE = re.compile(r"[(（][^()（）]*[)）]$")


class NoQualifyingTableError(RuntimeError):
    """ヘッダに「従前」・「新」の列を持つTableノードが1件も見つからない。

    法令の構造が変わった(改正・API仕様変更)可能性がある。黙って
    「見つかった最初のTable」を使わない——それは位置の決め打ちと
    同じ欠陥になる。
    """


class AmbiguousTableError(RuntimeError):
    """ヘッダで同定できるTableノードが2件以上見つかった。

    どちらを対応表として使うべきかをこのモジュールが黙って決めない
    (最初に見つかったものを使う、は導出の放棄と同じ欠陥になる)。
    """


class RaggedRowError(RuntimeError):
    """データ行のセル数が2ではない。想定外の構造なので自動で解釈しない。"""


class AmbiguousResolutionError(RuntimeError):
    """18名称の網羅検査で、多対多の一致が生じた。

    1つの対象名が複数行に一致した、または1行が複数の対象名に一致した
    場合にここに落ちる。どちらを正としてよいか自明ではないので、
    黙って先着で決めない。
    """


@dataclasses.dataclass(frozen=True)
class SuccessionRow:
    """抽出した対応表の1データ行(ヘッダ行を除く)。"""

    source_law_id: str
    #: 選んだTableノードの `children` 内での生の添字。ヘッダ行が0で、
    #: データ行は1から始まる(レイクに保存した実データを開いて
    #: children[row_index] を数えれば同じ行にたどり着ける——独自の
    #: 除外・再割番規約を知らなくても出典を追跡できるようにするため)。
    row_index: int
    old_text: str
    new_text: str
    #: `old_text` の末尾の括弧限定を取り除いたもの
    old_name: str
    #: `new_text` の末尾の括弧限定を取り除いたもの
    new_name: str


@dataclasses.dataclass(frozen=True)
class ExtractionResult:
    rows: list[SuccessionRow]
    #: 空セルのため落とした行。(row_index, 理由) の組。**黙って落とさず、
    #: 件数を報告できるようにするため保持する**(C-1ブリーフの要求)。
    dropped_rows: list[tuple[int, str]]


@dataclasses.dataclass(frozen=True)
class ResolvedMinistry:
    target_name: str
    row: SuccessionRow
    #: "exact"(そのまま一致)、または "prefix-decomposition(<接頭辞>)"
    #: (他の対象名を接頭辞として取り除いた上で一致)
    mechanism: str


@dataclasses.dataclass(frozen=True)
class CoverageResult:
    resolved: list[ResolvedMinistry]
    #: 解決できなかった対象名。**推測で埋めない**——このリストが
    #: 空でなくても、対応表から読み取れる範囲で前進したことにする
    #: (C-1ブリーフ: 部分的な成功でも前進である)
    unresolved: list[str]


def _iter_table_nodes(node: object) -> Iterator[dict]:
    """`tag == "Table"` のノードを再帰的に見つける。位置を仮定しない。"""
    if isinstance(node, dict):
        if node.get("tag") == "Table":
            yield node
        children = node.get("children")
        if isinstance(children, list):
            for child in children:
                yield from _iter_table_nodes(child)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_table_nodes(item)


def _cell_text(cell: object) -> str:
    """TableColumn(またはその子)から文字列を再帰的に取り出す。"""
    if isinstance(cell, str):
        return cell
    if isinstance(cell, dict):
        parts = []
        if "text" in cell:
            parts.append(str(cell["text"]))
        children = cell.get("children")
        if isinstance(children, list):
            for child in children:
                parts.append(_cell_text(child))
        return "".join(parts)
    if isinstance(cell, list):
        return "".join(_cell_text(item) for item in cell)
    return ""


def _header_column_roles(header_cells: list[str]) -> dict[str, int] | None:
    """ヘッダの各セルの文言から、旧列・新列の添字を確定する(列の位置は仮定しない)。

    「従前」を含むセルが旧列、「新」を含み「従前」を含まないセルが新列。
    それぞれちょうど1つでなければ(0個・2個以上・重複)同定できないとして
    Noneを返す。
    """
    old_idx = [i for i, t in enumerate(header_cells) if _OLD_HEADER_MARKER in t]
    new_idx = [
        i
        for i, t in enumerate(header_cells)
        if _NEW_HEADER_MARKER in t and _OLD_HEADER_MARKER not in t
    ]
    if len(old_idx) != 1 or len(new_idx) != 1 or old_idx[0] == new_idx[0]:
        return None
    return {"old": old_idx[0], "new": new_idx[0]}


def _select_table_and_roles(law_full_text: dict) -> tuple[dict, dict[str, int]]:
    """テーブル選定とヘッダのロール確定を1回の走査でまとめて行う。

    `select_succession_table`(公開API)と`extract_succession_rows`が
    同じヘッダ判定基準を**別々に再計算して食い違う**ことを避けるための
    内部共有実装(食い違いが起きるとテーブルは選べたのにヘッダは
    読めない、という到達不能なはずの状態を作りかねない)。
    """
    tables = list(_iter_table_nodes(law_full_text))
    qualifying: list[tuple[dict, dict[str, int]]] = []
    for table in tables:
        rows = table.get("children") or []
        if not rows:
            continue
        header_cells = [_cell_text(c) for c in (rows[0].get("children") or [])]
        roles = _header_column_roles(header_cells)
        if roles is not None:
            qualifying.append((table, roles))

    if not qualifying:
        raise NoQualifyingTableError(
            "「従前」・「新」のヘッダで同定できるTableノードが見つからない"
            f"(見つかったTableノード総数: {len(tables)})。"
            "法令の構造が変わった可能性がある"
        )
    if len(qualifying) > 1:
        raise AmbiguousTableError(
            f"「従前」・「新」のヘッダで同定できるTableノードが"
            f"{len(qualifying)}件見つかった。どれを対応表として使うべきかを"
            "自動で決めない"
        )
    return qualifying[0]


def select_succession_table(law_full_text: dict) -> dict:
    """`law_full_text` の中から、ヘッダで同定できるTableノードを1つ選ぶ。

    0件・2件以上は例外にする(黙って最初のものを選ばない)。
    """
    table, _roles = _select_table_and_roles(law_full_text)
    return table


def strip_trailing_qualifier(text: str) -> str:
    """末尾の括弧限定(全角（）・半角()の両方)を取り除く。

    実データで確認した形(入れ子なし・末尾に1箇所のみ)だけを扱う。
    例:「大蔵省(造幣局、印刷局及び国税庁を除く。)」→「大蔵省」
    括弧が無い場合はそのまま返す(例:「建設省」→「建設省」)。
    """
    return _TRAILING_QUALIFIER_RE.sub("", text)


def extract_succession_rows(law_full_text: dict, source_law_id: str) -> ExtractionResult:
    """対応表を選び、ヘッダ行を除いた全データ行を `SuccessionRow` に変換する。

    行のセル数が2でなければ `RaggedRowError`(想定外の構造。自動で解釈
    しない)。旧・新いずれかのセルが空文字列の行は、**黙って落とさず**
    `dropped_rows` に記録した上で結果から除く(セル結合等で意味が
    確定できない行を、確定していないまま含めるのは危険)。
    """
    table, roles = _select_table_and_roles(law_full_text)
    rows = table.get("children") or []
    old_i, new_i = roles["old"], roles["new"]

    result_rows: list[SuccessionRow] = []
    dropped: list[tuple[int, str]] = []
    for idx in range(1, len(rows)):
        cells = rows[idx].get("children") or []
        if len(cells) != 2:
            raise RaggedRowError(
                f"row_index={idx}: セル数が2ではない({len(cells)}件)。"
                "想定外の構造なので自動で処理しない"
            )
        texts = [_cell_text(c) for c in cells]
        old_text, new_text = texts[old_i], texts[new_i]
        if not old_text.strip() or not new_text.strip():
            reason = "old cell empty" if not old_text.strip() else "new cell empty"
            dropped.append((idx, reason))
            continue
        result_rows.append(
            SuccessionRow(
                source_law_id=source_law_id,
                row_index=idx,
                old_text=old_text,
                new_text=new_text,
                old_name=strip_trailing_qualifier(old_text),
                new_name=strip_trailing_qualifier(new_text),
            )
        )
    return ExtractionResult(rows=result_rows, dropped_rows=dropped)


def resolve_old_ministries(
    rows: list[SuccessionRow], target_names: frozenset[str]
) -> CoverageResult:
    """対象の名称集合(`old-ministries.csv` の18名称)のうち、抽出した表の

    行で解決できるものを同定する。

    まず素の一致(`old_name` が対象名と等しい)を試す。一致しなければ、
    対象名を「別の対象名を先頭から取り除いた残り」として見る(実データで
    確認した「総理府」+外局名の連結パターンへの対応。「総理府」という
    文字列そのものを決め打ちにするのではなく、`target_names` 自体を
    接頭辞の候補集合として使う)。
    """
    matches: dict[str, list[tuple[SuccessionRow, str]]] = {name: [] for name in target_names}

    for row in rows:
        if row.old_name in target_names:
            matches[row.old_name].append((row, "exact"))
            continue
        for prefix in target_names:
            if row.old_name.startswith(prefix) and row.old_name != prefix:
                remainder = row.old_name[len(prefix) :]
                if remainder in target_names:
                    matches[remainder].append(
                        (row, f"prefix-decomposition({prefix})")
                    )

    resolved: list[ResolvedMinistry] = []
    unresolved: list[str] = []
    ambiguous_names: dict[str, int] = {}
    for name in sorted(target_names):
        candidates = matches[name]
        if len(candidates) == 0:
            unresolved.append(name)
        elif len(candidates) == 1:
            row, mechanism = candidates[0]
            resolved.append(ResolvedMinistry(target_name=name, row=row, mechanism=mechanism))
        else:
            ambiguous_names[name] = len(candidates)

    if ambiguous_names:
        raise AmbiguousResolutionError(
            f"次の対象名が複数行に一致した(自動でどちらかを選ばない): {ambiguous_names}"
        )

    # 1行が複数の対象名に一致していないかも確認する(多対多を許さない側)
    row_to_names: dict[int, list[str]] = {}
    for rm in resolved:
        row_to_names.setdefault(rm.row.row_index, []).append(rm.target_name)
    multi_matched_rows = {idx: names for idx, names in row_to_names.items() if len(names) > 1}
    if multi_matched_rows:
        raise AmbiguousResolutionError(
            f"次の行(row_index)が複数の対象名に一致した"
            f"(自動でどちらかを選ばない): {multi_matched_rows}"
        )

    return CoverageResult(resolved=resolved, unresolved=unresolved)
