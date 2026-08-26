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
同じ発想を使う。実データを確認すると、58行のうち8行
(例:「総理府北海道開発庁」「総理府金融再生委員会」)は
「総理府」+外局名を**区切り文字なしで連結した**形をしている(2001年改革
前、これらの庁・委員会は総理府の外局だった実際の行政組織上の事実)。
この「総理府」という接頭辞を決め打ちの文字列として持たない——
`old-ministries.csv` の18名称の集合そのものを接頭辞の候補として使い、
「対象名Aが対象名Bを先頭から取り除いた残りと一致する」形で導出する
(ヘッダ文言から列の意味を導出するのと同じ「既存の参照データから導出する」
という発想の繰り返し)。

**新側(`new_name`)にも同じ発想を適用する(2026-08-26レビュー指摘で発覚)。**
18名称のうち17件はnew_nameがそのまま現行の府省・外局等の参照集合
(`ministry-codes.csv`)の名称と一致するが、金融再生委員会の1件だけは
「内閣府金融庁」という、旧側の「総理府北海道開発庁」と同じ**区切り文字
なしの連結**の形をしている。旧側の分解と同じ発想で、`reference_names`
(ministry-codes.csvの全名称)自体を接頭辞の候補として使い、新側も分解する
(`resolve_successor_names`)。「総理府」を決め打ちにしないのと同じ理由で、
ここでも「内閣府」を決め打ちの接頭辞にしない。

**58データ行のうちKGに符号化するのは18名称の分だけ、という設計上の制約。**
この対応表は2000年時点のスナップショットである(法令自体は2001年1月6日
施行)。new_name側には、この時点では現存していたがその後さらに別の改革で
廃止・独立行政法人化された機関を指す行が多数ある(例: 防衛庁→2007年に
防衛省へ、社会保険庁→2010年廃止、郵政事業庁・食糧庁→2003年廃止、
造幣局・印刷局→2003年独立行政法人化)。実際、58行のnew_nameは43種類に
正規化され、そのうち`ministry-codes.csv`(現行40件)の名称と一致するのは
11件(素の名称)+15件(2名称の連結として分解可能)=26件のみで、**残り17件は
どの現存組織の名称にも一致しない**。したがって全58行をそのまま
succeededByのエッジとして符号化すると、KGに存在しない組織を指す参照整合性
の失敗を生む。**この対応表の全58行はCSV(`ministry-succession.csv`)に出典
として残すが、KGへ符号化するのは`old-ministries.csv`の18名称の解決分だけに
限る**(パイプラインへの実際の結線はC-3で行う。ここでは境界を明記するのみ)。
"""
import dataclasses
import re
from collections.abc import Iterator, Mapping

# この対応表の出典法令(C-1)。「導出すべき値を手書きしている」の対象は
# ツリー上の位置・パス・件数等の**派生値**であり、この法令IDは主要な入力の
# 識別子そのもの(sources.pyのURL群と同じ層)——1箇所で正として持ち、
# scripts/extract_ministry_succession.py・pipeline.pyの両方がここから
# importする(以前は各ファイルに同じ文字列リテラルが散っていた)
SUCCESSION_LAW_ID = "412CO0000000315"

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


class AmbiguousSuccessorDecompositionError(RuntimeError):
    """新側(`new_name`)を参照集合(ministry-codes.csv)へ分解する際、

    複数の分解が成立した。どちらを後継として選ぶべきかが自明ではない
    ので、`AmbiguousResolutionError` と同じ立場を取り、黙って選ばない。
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


@dataclasses.dataclass(frozen=True)
class ResolvedSuccessor:
    """`ResolvedMinistry.row.new_name` を、現行の府省・外局等の参照集合

    (`ministry-codes.csv`)に対して分解した結果。
    """

    target_name: str
    row: SuccessionRow
    #: 旧側の解決機序。`ResolvedMinistry.mechanism` をそのまま引き継ぐ
    old_mechanism: str
    #: 参照集合に実在する後継名(分解後)
    successor_name: str
    #: "exact"、または "suffix-decomposition(<取り除いた接頭辞>)"
    successor_mechanism: str


@dataclasses.dataclass(frozen=True)
class SuccessorResolutionResult:
    resolved: list[ResolvedSuccessor]
    #: (target_name, new_name) の組。参照集合のどの名称とも一致せず、
    #: 既知の2名称の連結としても分解できなかったもの。**推測で埋めない**
    unresolved: list[tuple[str, str]]


def _resolve_name_against_reference(
    name: str, reference_names: frozenset[str]
) -> tuple[str, str] | None:
    """名称1つを参照集合に対して解決する(素の一致→分解の順)。

    `resolve_old_ministries` の「対象名を対象名自身の接頭辞候補で分解する」
    のと同じ発想を、対象を`reference_names`全体に広げて適用したもの。

    **分解は1段に決め打ちにせず、繰り返し適用する。** 実データに
    「内閣府国家公安委員会警察庁」(内閣府→国家公安委員会→警察庁の3段)
    のような例がある——警察庁は国家公安委員会の、国家公安委員会は内閣府の
    外局という実際の行政組織上の入れ子がそのまま文字列の連結段数になっている
    ため、段数を1段に決め打ちにするとこの実例を見落とす(このモジュールが
    禁じる「導出すべき値を手書きしている」の変種になる)。

    一致も分解もできない場合は None(推測で埋めない。呼び出し側が扱う)。
    どの段でも複数の接頭辞が成立する場合は `AmbiguousSuccessorDecompositionError`
    (自動で選ばない)。
    """
    stripped: list[str] = []
    remainder = name
    while remainder not in reference_names:
        candidates = [
            prefix
            for prefix in reference_names
            if remainder.startswith(prefix) and remainder != prefix
        ]
        if len(candidates) > 1:
            raise AmbiguousSuccessorDecompositionError(
                f"{name!r} の分解(残り{remainder!r})に複数の接頭辞が成立した"
                f"(自動で選ばない): {sorted(candidates)}"
            )
        if not candidates:
            return None
        prefix = candidates[0]
        stripped.append(prefix)
        remainder = remainder[len(prefix) :]

    if not stripped:
        return remainder, "exact"
    return remainder, f"suffix-decomposition({'+'.join(stripped)})"


def resolve_successor_names(
    resolved: list[ResolvedMinistry], reference_names: frozenset[str]
) -> SuccessorResolutionResult:
    """`resolve_old_ministries` が解決した各行の `new_name` を、現行の

    府省・外局等の参照集合(`ministry-codes.csv`)に対して分解する。

    旧側のprefix-decompositionと新側のこの分解は同じ発想の繰り返しである
    (モジュールdocstring参照)。18名称のうち17件は素の一致で解決し、
    金融再生委員会の1件(new_name="内閣府金融庁")だけがsuffix-decomposition
    経由になる(実データで確認済み)。
    """
    out: list[ResolvedSuccessor] = []
    unresolved: list[tuple[str, str]] = []
    for rm in resolved:
        outcome = _resolve_name_against_reference(rm.row.new_name, reference_names)
        if outcome is None:
            unresolved.append((rm.target_name, rm.row.new_name))
            continue
        successor_name, successor_mechanism = outcome
        out.append(
            ResolvedSuccessor(
                target_name=rm.target_name,
                row=rm.row,
                old_mechanism=rm.mechanism,
                successor_name=successor_name,
                successor_mechanism=successor_mechanism,
            )
        )
    return SuccessorResolutionResult(resolved=out, unresolved=unresolved)


# =============================================================================
# C-3: AbolishedGovernmentOrgan として符号化する記録を組み立てる
# =============================================================================


class MissingAmendmentEnforcementDateError(RuntimeError):
    """法令の`revision_info`に`amendment_enforcement_date`が無い。

    廃止日を手書きの定数にしない代わりにこのフィールドから導出するため、
    無い場合は推測で埋めず、ここで名指しして落とす(このタスク自身が
    禁じている「導出すべき値を手書きしている」の9件目を避けるための境界)。
    """


class MissingSuccessorMinistryError(RuntimeError):
    """`resolve_successor_names`が解決した後継名が、実際に符号化された

    `Ministry`(houjin-bangou×ministry-codes.csvの突合結果)のどれにも
    一致しない。黙って対象外にすると、参照整合ゲート(裁定B4)が拾う前に
    このタスクの中で欠落が握り潰されるため、名指しで落とす。
    """


def derive_abolition_date(revision_info: Mapping[str, object]) -> str:
    """法令データの`revision_info`から、この法令の施行日を導出する(ISO8601)。

    **手書きの定数にしない。** `412CO0000000315`(この対応表そのものの出典)
    の`revision_info.amendment_enforcement_date`が"2001-01-06"であり、
    かつ`amendment_law_id`がNone(この法令自身の制定時点の版であり、後の
    別法令による改正ではない)であることを実データで確認済み——つまり
    この日付は「2001年の中央省庁再編がいつ施行されたか」そのものを表す。
    `old-ministries.csv`は2001年再編で廃止された名称に限る集合と裁定B7で
    明示的に狭められているため、この対応表から解決した18名称は全て同じ
    廃止日を共有する(コホート自体が単一の施行イベントで定義されている
    ため、「一部だけ導出できない」という分岐は構造上起こらない)。
    """
    value = revision_info.get("amendment_enforcement_date")
    if not value or not isinstance(value, str):
        raise MissingAmendmentEnforcementDateError(
            "revision_info.amendment_enforcement_date が無い(または空)。"
            "廃止日を推測で埋めない——法令データの取得元を確認すること"
        )
    return value


@dataclasses.dataclass(frozen=True)
class AbolishedMinistryRecord:
    """`AbolishedGovernmentOrgan`インスタンス1件分の、符号化に必要な情報。

    `successor_houjin_bangou`は複数のministry.Ministryの法人番号(裁定:
    succeededByは多値・必須)。**現データでは18件とも常に1件だけ**——
    多値を実際に行使する例は現データに無い(裁定5。合成データでのみ
    確認する。`tests/test_transform_ministry_succession.py`参照)。
    """

    name: str
    successor_houjin_bangou: list[str]
    abolition_date: str


def build_abolished_ministries(
    successors: SuccessorResolutionResult,
    ministry_houjin_bangou_by_name: Mapping[str, str],
    abolition_date: str,
) -> list[AbolishedMinistryRecord]:
    """`resolve_successor_names`の結果を、符号化できる形にまとめる。

    **府省レベルの`succeededBy`に、除外された下位組織の後継を含めない
    (裁定2)。** 例えば厚生省の対応表の行には、厚生省自身の後継である
    厚生労働省だけでなく、除外された1課(生活衛生局水道環境部環境整備課)
    の後継である環境省も実データに存在する(C-2報告の「除外パターンの
    再帰」参照)。しかし「厚生省令」は厚生省が全体として発した法令であり、
    後にその1課だけが環境省へ移った事実は、**省令の所管という意味では
    環境省を後継にしない**——含めると、あらゆる厚生省令のCQ1が環境省を
    併記して誤導する。この関数の入力が`SuccessorResolutionResult`
    (`resolve_old_ministries`が返す**府省レベルの**18行だけを経由した
    `resolve_successor_names`の出力)である時点で、除外された下位組織の
    行はそもそも入力に現れない——「含めない」は個別の除外ロジックではなく、
    **入力の構成そのもので保証されている**。情報自体は失われない
    (`ministry-succession.csv`に58行全て残る。将来、機関レベルの粒度を
    モデル化する日が来たらそちらを使える)。

    後継名(`successor_name`)を実際に符号化された`Ministry`の法人番号に
    変換する。**一致しない後継名があれば黙って落とさず
    `MissingSuccessorMinistryError`で名指しする**(推測で埋めない。
    参照整合ゲートより手前でここで検出する)。
    """
    missing: list[str] = []
    out: list[AbolishedMinistryRecord] = []
    for r in successors.resolved:
        houjin_bangou = ministry_houjin_bangou_by_name.get(r.successor_name)
        if houjin_bangou is None:
            missing.append(r.successor_name)
            continue
        out.append(
            AbolishedMinistryRecord(
                name=r.target_name,
                successor_houjin_bangou=[houjin_bangou],
                abolition_date=abolition_date,
            )
        )
    if missing:
        raise MissingSuccessorMinistryError(
            f"次の後継名が実際に符号化されたMinistryのどれにも一致しない"
            f"(自動で対象外にしない): {sorted(missing)}"
        )
    return out
