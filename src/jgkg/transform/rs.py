"""RSシステム(行政事業レビュー見える化サイト)実データ → 予算事業・支出。

府省 → 予算事業(BudgetProject) → 支出先法人(Expenditure.recipient) という
縦スライスの本体(Task 7)。列には `rs_columns.RS_FILES` / `rs_columns.RS_COL`
経由でのみ触る(このモジュール自身は列インデックスを持たない)。

**ブリーフが要求した `parse_rs(path) -> Iterator[RsRow]`(単一パス)という形は、
RSが単一のCSVではなく事業年度ごとに15本の関連ファイルに分かれる構造(rs_columns.py
モジュールdocstring参照)に合わない。`rs_columns.RS_COL` が単一テーブル前提の
`dict[str, str|int]` から `dict[str, tuple[group_key, index]]` に変わった
Task 6の分岐と同じ理由で、`parse_rs` も単一 `path` ではなく
`Mapping[group_key, Path]` を受ける形に変えた(このタスクの分岐。報告書に明記)。**

3段の解決(§8.1):
  1. 決定的な直結(法人番号・法令ID) — 曖昧さが無い
  2. 正規化した上での一意一致(法人名・法令名/略称) — 「血縁のある正規化のみ」
  3. 一致しなければ UnresolvedReference(理由付き) — 沈黙させない(§8.2)
"""
import csv
import io
import re
import unicodedata
import zipfile
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from jgkg.transform import rs_columns
from jgkg.transform.law import LawRecord
from jgkg.transform.ministry import Ministry
from jgkg.transform.organization import Organization

# =============================================================================
# 金額の正規化(Step 2)
# =============================================================================

_ZENKAKU_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def normalize_amount(raw: str) -> int | None:
    """RSの金額文字列を正規化してintにする。

    空文字(strip後)は**欠損**として `None` を返す(0とは違う。budget_summaryの
    '0' は有効なゼロ予算であり、ここでは素通りする — rs_columns.
    find_budget_aggregate_row のdocstringと同じ判定)。カンマ・全角数字を
    正規化する(Step 2の指示)。budget_summaryの一部の列には小数点付き文字列
    ('50617000.0')が現れる実例がある(rs_columns.py [budget_summary] 行構造の
    引用参照。Task 7が使う列(当初予算・支出先の合計支出額)そのものでは未確認だが、
    同じファイル内の同義列に現れる形なので防御的に対応する)ため、末尾の'.0'は
    安全に落とす。それ以外の小数(実データで未確認)は `int()` に委ねて例外にする
    (黙って切り捨てない)。
    """
    s = raw.strip()
    if not s:
        return None
    s = s.translate(_ZENKAKU_DIGITS).replace(",", "").replace("，", "")
    s = s.removesuffix(".0")
    return int(s)


# =============================================================================
# 法人名の正規化(Step 3。§8.1の2段目。血縁のある正規化のみ)
# =============================================================================

# 法人種別語の表記ゆれ。NFKCで ㈱→(株) に分解された後の形も含めて列挙する
_CORPORATE_TYPE_WORDS = (
    "株式会社", "有限会社", "合同会社", "合名会社", "合資会社",
    "(株)", "(有)", "(合)",
)


def normalize_corporate_name(name: str) -> str:
    """法人名を正規化する。全半角統一(NFKC。㈱は(株)に分解される)・空白除去・

    法人種別語の除去のみ(曖昧照合はしない。「血縁のある正規化のみ」)。
    法人種別語を統一する代わりに**除去**するのは、前株(株式会社ウルフスタイル)・
    後株(ウルフスタイル(株))のどちらの表記でも同じ結果になるようにするため
    (どちらを正準形にするかを決める代わりに、両方から同じ情報を引く)。
    """
    n = unicodedata.normalize("NFKC", name)
    n = n.replace(" ", "").replace("　", "")
    for word in _CORPORATE_TYPE_WORDS:
        n = n.replace(word, "")
    return n


# =============================================================================
# 中間表現(parse_rsの出力・build_projectsの入力)
# =============================================================================


@dataclass(frozen=True)
class BasisLawCitation:
    """policy_measure_laws_and_regulationsの1行(根拠法令の引用1件)。

    law_id・law_titleのいずれも空なら「この行は法令を引用していない」
    (rs_columns.py照合記録「検証4」。全体の46.5%がこの形。抽出失敗ではないので
    build_projectsはこれを未解決としては数えない)。
    """

    law_id: str | None
    law_title: str | None


@dataclass(frozen=True)
class ExpenditureLine:
    """payee_payment_informationの支出先1件分(集計行を選び終えた後)。

    ブロック行(支出先名が空)は既に除かれている前提。is_bundled は
    「その他」フラグ・表示名のいずれかで判定済み(rs_columns.py照合記録
    「検証7」)。
    """

    recipient_name: str
    recipient_houjin_bangou: str | None
    is_bundled: bool
    amount: int


@dataclass(frozen=True)
class RsRow:
    """1つの(project_id, fiscal_year)についての、4ファイルを結合した中間表現。

    fiscal_year は project_summary の事業年度(RS_COL "fiscal_year")。
    budget_amount はこの事業年度の当初予算(合計)で、budget_summaryが持つ
    直近5年度分の履歴のうち、このfiscal_yearに一致する集計行だけを取る
    (過去4年度分の履歴はモデル化しない。Task 7報告書の逸脱台帳参照)。
    その年度の集計行が見つからない場合は `None`(欠損。ColumnLayoutErrorには
    しない — 「この事業がbudget_summaryに1行も無い」ケースは実データでは
    0件だったが、将来のRS更新で起こり得るため、`parse_rs` はこれを
    ColumnLayoutError(実データ上あり得ないはずの状態、を示す例外)ではなく
    欠損として扱う)。
    """

    project_id: str
    fiscal_year: str
    project_name: str
    ministry_name: str
    budget_amount: int | None
    basis_law_citations: tuple[BasisLawCitation, ...] = ()
    expenditures: tuple[ExpenditureLine, ...] = ()


# =============================================================================
# parse_rs: ファイルの読み込みと結合(解決ロジックは持たない)
# =============================================================================

REQUIRED_GROUPS: tuple[str, ...] = (
    "project_summary",
    "budget_summary",
    "policy_measure_laws_and_regulations",
    "payee_payment_information",
)


def _group_rows(group_key: str, path: Path) -> Iterator[list[str]]:
    """指定した group_key のCSV(配布形態のzip、またはfixtureの生CSV)を読み、

    ヘッダをrs_columns.verify_headerで検査した後のデータ行を返す。**BOMの
    有無に関わらず動く**(`utf-8-sig` は先頭にBOMがあれば剥がし、無ければ
    何もしない。rs_columns.pyのエンコーディング注記参照)。organization.
    parse_source と同じ、配布形態(zip)・生CSV(fixture)の両方を受ける設計。
    """
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            members = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if len(members) != 1:
                raise ValueError(
                    f"{path}: zip内のCSVが1つではない({members})。"
                    " 配布仕様が変わった可能性がある"
                )
            with z.open(members[0]) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="strict", newline="")
                yield from _verified_rows(group_key, text)
    else:
        with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as text:
            yield from _verified_rows(group_key, text)


def _verified_rows(group_key: str, text: Iterable[str]) -> Iterator[list[str]]:
    reader = csv.reader(text)
    header = next(reader)
    rs_columns.verify_header(group_key, header)
    yield from reader


def _group_by_project_id(rows: Iterator[list[str]]) -> dict[str, list[list[str]]]:
    idx = rs_columns.RS_COL["project_id"][1]
    out: dict[str, list[list[str]]] = {}
    for row in rows:
        out.setdefault(row[idx], []).append(row)
    return out


def _current_year_budget_amount(
    rows_for_project: list[list[str]], fiscal_year: str
) -> int | None:
    """この事業年度の当初予算(合計)を取る。見つからなければ欠損として `None`。

    `rs_columns.find_budget_aggregate_row` と**同じ選択規則**(予算年度が一致し
    当初予算(合計)が非空の行を1件選ぶ)を使うが、**「この事業年度の行が1件も
    無い」場合の扱いが違う**: `find_budget_aggregate_row` は「0件・2件以上は
    実データの範囲では起きないはずの異常」として常に例外にするが、ここでは
    「その事業がbudget_summaryに1行も無い/この事業年度の行が無い」を、まだ
    実データで確認していないだけの正当な欠損として区別する(実測: 2026-08-23
    取得の全5,794事業で0件のはずだが、将来のRS更新で起こり得るため、
    ColumnLayoutErrorではなく欠損で受ける。2件以上(実データの範囲外の異常)は
    `find_budget_aggregate_row` に委ねてColumnLayoutErrorにする)。
    """
    if not rows_for_project:
        return None
    spec = rs_columns.RS_FILES["budget_summary"]
    idx_fy = spec.col["budget_fiscal_year"]
    idx_amount = spec.col["budget_amount"]
    matches = [
        r for r in rows_for_project
        if r[idx_fy] == fiscal_year and r[idx_amount].strip() != ""
    ]
    if not matches:
        return None
    if len(matches) > 1:
        # 実データの範囲では起きないはずの異常。既存の検算済みルールに委ねる
        rs_columns.find_budget_aggregate_row(rows_for_project, fiscal_year)
    return normalize_amount(matches[0][idx_amount])


def _basis_law_citations_for(rows_for_project: list[list[str]]) -> tuple[BasisLawCitation, ...]:
    spec = rs_columns.RS_FILES["policy_measure_laws_and_regulations"]
    idx_id = spec.col["basis_law_id"]
    idx_title = spec.col["basis_law_text"]
    out = []
    for r in rows_for_project:
        law_id = r[idx_id].strip() or None
        law_title = r[idx_title].strip() or None
        out.append(BasisLawCitation(law_id=law_id, law_title=law_title))
    return tuple(out)


def _is_bundled_row(row: list[str], idx_flag: int, idx_name: int) -> bool:
    """束ね行の判定。「その他」フラグ・表示名のいずれかが立っていれば束ね行とする

    (rs_columns.py照合記録「検証7」: フラグが立った行に法人番号が入っている行は
    実データに0件なので、この判定を先に行っても法人番号直結の対象を取りこぼさない)。
    """
    return row[idx_flag].strip().upper() == "TRUE" or row[idx_name].strip() == "その他"


def _expenditures_for(rows_for_project: list[list[str]]) -> tuple[ExpenditureLine, ...]:
    """支出先の集計行だけを取り、明細行(契約単位の内訳)は無視する。

    rs_columns.py照合記録「検証6」: 1支出先につき[23]支出先の合計支出額が
    非空の行はちょうど1件(実データ74,291組全件で確認済み)。単純な行フィルタで
    足りる(budget_summaryのようなfind_*_aggregate_rowは不要)。
    """
    spec = rs_columns.RS_FILES["payee_payment_information"]
    idx_name = spec.col["recipient_name"]
    idx_bangou = spec.col["recipient_houjin_bangou"]
    idx_flag = spec.col["recipient_other_flag"]
    idx_amount = spec.col["expenditure_amount"]

    out = []
    for r in rows_for_project:
        name = r[idx_name].strip()
        if not name:
            continue  # ブロック行(支出先名が空)
        amount_raw = r[idx_amount]
        amount = normalize_amount(amount_raw)
        if amount is None:
            continue  # 集計額が本当に欠落している明細行(検証6の「374組」)。呼び出し側が計数する
        bangou = r[idx_bangou].strip() or None
        is_bundled = _is_bundled_row(r, idx_flag, idx_name)
        out.append(
            ExpenditureLine(
                recipient_name=name,
                recipient_houjin_bangou=None if is_bundled else bangou,
                is_bundled=is_bundled,
                amount=amount,
            )
        )
    return tuple(out)


def parse_rs(paths: Mapping[str, Path]) -> Iterator[RsRow]:
    """RSの複数ファイルを読み、project_idで結合した `RsRow` を生成する。

    `paths` は group_key(rs_columns.RS_FILESのキー) → ファイルパス(配布形態の
    zip、またはfixtureの生CSV)。`REQUIRED_GROUPS` の4つが必須(organization_
    informationはRS_COLがどの論理名にも使わないため対象外。rs_columns.py参照)。
    project_id の集合は project_summary を正準の出典とする(RS_COLの設計。
    他の3ファイルも実データでは同じ集合を持つが、project_summaryが「この
    事業年度のレビューシートに載っている事業」の正の出典)。
    """
    missing = [g for g in REQUIRED_GROUPS if g not in paths]
    if missing:
        raise ValueError(f"paths に必須のグループが無い: {missing}")

    project_spec = rs_columns.RS_FILES["project_summary"]
    idx_pid = project_spec.col["project_id"]
    idx_name = project_spec.col["project_name"]
    idx_ministry = project_spec.col["ministry_name"]
    idx_fy = project_spec.col["fiscal_year"]

    spine: dict[str, tuple[str, str, str]] = {}
    order: list[str] = []
    for row in _group_rows("project_summary", paths["project_summary"]):
        pid = row[idx_pid]
        if pid not in spine:
            spine[pid] = (row[idx_name], row[idx_ministry], row[idx_fy])
            order.append(pid)

    budget_by_pid = _group_by_project_id(_group_rows("budget_summary", paths["budget_summary"]))
    law_by_pid = _group_by_project_id(
        _group_rows("policy_measure_laws_and_regulations", paths["policy_measure_laws_and_regulations"])
    )
    payee_by_pid = _group_by_project_id(
        _group_rows("payee_payment_information", paths["payee_payment_information"])
    )

    for pid in order:
        project_name, ministry_name, fiscal_year = spine[pid]
        yield RsRow(
            project_id=pid,
            fiscal_year=fiscal_year,
            project_name=project_name,
            ministry_name=ministry_name,
            budget_amount=_current_year_budget_amount(budget_by_pid.get(pid, []), fiscal_year),
            basis_law_citations=_basis_law_citations_for(law_by_pid.get(pid, [])),
            expenditures=_expenditures_for(payee_by_pid.get(pid, [])),
        )


# =============================================================================
# laws_index_by_title(Step 4準備)
# =============================================================================


def laws_index_by_title(records: Iterable[LawRecord]) -> dict[str, list[LawRecord]]:
    """`LawRecord` を題名・略称の両方でグループ化する(B13の名称フォールバックの入力)。

    `law.to_ministry_reference` と同じ理由で値を `list[LawRecord]` にする —
    同じ題名/略称を持つ法令が複数あれば、それがAMBIGUOUSの検出そのものになる。
    1件のLawRecordが複数のキー(題名+各略称)の下に現れ得る。
    """
    idx: dict[str, list[LawRecord]] = {}
    for r in records:
        if r.law_title:
            idx.setdefault(r.law_title, []).append(r)
        for a in r.abbrev:
            if a:
                idx.setdefault(a, []).append(r)
    return idx


_TRAILING_PAREN_RE = re.compile(r"（[^（）]*）\s*$")


@dataclass(frozen=True)
class LawResolution:
    """`resolve_basis_law` の結果。3値(§8.1)を1つの型にまとめる。"""

    record: LawRecord | None
    method: Literal["law_id", "title_raw", "title_stripped"] | None
    reason: Literal["NO_CANDIDATE", "AMBIGUOUS"] | None
    key: str | None  # 未解決のとき、core:unresolved_key に入れる値


def resolve_basis_law(
    citation: BasisLawCitation,
    laws_by_id: Mapping[str, LawRecord],
    laws_by_title: Mapping[str, list[LawRecord]],
) -> LawResolution:
    """1件の根拠法令引用を解決する(B13: law_id直結が主)。

    呼び出し側は「law_id・law_titleのいずれも空(引用そのものが無い)」行を
    あらかじめ除いていること(build_projectsのbasis_law_out_of_scope集計)。
    """
    if citation.law_id:
        # B13: law_idがある行はtitleへフォールバックしない(決定的な経路の
        # 結果そのものが答え。見つからなければNO_CANDIDATE — この時点で
        # 「law_idはあるがe-Govスナップショットには無い」ことが分かる)
        record = laws_by_id.get(citation.law_id)
        if record is not None:
            return LawResolution(record, "law_id", None, None)
        return LawResolution(None, None, "NO_CANDIDATE", citation.law_id)

    title = citation.law_title
    if not title:
        return LawResolution(None, None, "NO_CANDIDATE", "")

    matches = laws_by_title.get(title, [])
    if len(matches) == 1:
        return LawResolution(matches[0], "title_raw", None, None)
    if len(matches) > 1:
        return LawResolution(None, None, "AMBIGUOUS", title)

    # Trap 1(照合記録「検証5」): RS表記は題名の末尾に公布情報の全角括弧書きを
    # 持つことがある。e-Govのlaw_titleは公布情報を含まないため、末尾の
    # `（…）`を1回だけ剥がして完全一致を再試行する(曖昧照合はしない —
    # 剥がすのはこの1パターンのみで、カンマ区切りの複数法令並記等は
    # そのままNO_CANDIDATEになる)
    stripped = _TRAILING_PAREN_RE.sub("", title).strip()
    if stripped and stripped != title:
        matches = laws_by_title.get(stripped, [])
        if len(matches) == 1:
            return LawResolution(matches[0], "title_stripped", None, None)
        if len(matches) > 1:
            return LawResolution(None, None, "AMBIGUOUS", stripped)

    return LawResolution(None, None, "NO_CANDIDATE", title)


# =============================================================================
# build_recipient_name_index(Step 3: RSの支出先名の集合に限定してストリーミング)
# =============================================================================


def build_recipient_name_index(
    organizations: Iterable[Organization], target_normalized_names: set[str]
) -> dict[str, list[str]]:
    """法人番号 全件データを1パスで流し、`target_normalized_names` に含まれる

    正規化名だけを辞書に残す。**5.8M件を辞書に全載せしない**(R19)。
    `organizations` は `organization.parse_source` のジェネレータをそのまま
    渡すこと(全件をlist化しない)。
    """
    idx: dict[str, list[str]] = {}
    for org in organizations:
        normalized = normalize_corporate_name(org.name)
        if normalized in target_normalized_names:
            idx.setdefault(normalized, []).append(org.houjin_bangou)
    return idx


@dataclass(frozen=True)
class RecipientResolution:
    """`resolve_recipient` の結果。束ね行は method/reason ともに `None`
    (解決を試みていないことを型で表す — NO_CANDIDATEと紛れさせない)。
    """

    houjin_bangou: str | None
    method: Literal["houjin_bangou", "name"] | None
    reason: Literal["NO_CANDIDATE", "AMBIGUOUS"] | None


def resolve_recipient(
    line: ExpenditureLine, name_index: Mapping[str, list[str]]
) -> RecipientResolution:
    """支出先1件を解決する(B14: 法人番号直結 → 名称正規化の一意一致 → 未解決)。

    束ね行(is_bundled)は解決を試みない(B14: 「その他」への束ね行は名称解決の
    対象ではなく、束ね行として計数する。黙って落とさない — Expenditure自体は
    呼び出し側(build_projects)が作る)。
    """
    if line.is_bundled:
        return RecipientResolution(None, None, None)
    if line.recipient_houjin_bangou:
        return RecipientResolution(line.recipient_houjin_bangou, "houjin_bangou", None)

    normalized = normalize_corporate_name(line.recipient_name)
    candidates = name_index.get(normalized, [])
    if len(candidates) == 1:
        return RecipientResolution(candidates[0], "name", None)
    if len(candidates) > 1:
        return RecipientResolution(None, None, "AMBIGUOUS")
    return RecipientResolution(None, None, "NO_CANDIDATE")


# =============================================================================
# build_projects(rows, ministry_ref, laws_by_id, laws_by_title) -> BuildResult
# =============================================================================


@dataclass
class BuildStats:
    """解決率・束ね件数・未解決内訳(§11.1の観測性。欠陥型4対策)。

    PipelineReportに載せてenforce_release_gate/Task 11が読める形にすることは
    pipeline.pyへの結線を担うタスク(Task 11。brief引き継ぐ決定・環境注記参照)
    の作業だが、その入力になる件数はここで確定させる。
    """

    projects_seen: int = 0
    ministries_resolved: int = 0
    ministries_unresolved: int = 0
    budget_amount_missing: int = 0
    basis_law_out_of_scope: int = 0
    basis_law_resolved_by_id: int = 0
    basis_law_resolved_by_title_raw: int = 0
    basis_law_resolved_by_title_stripped: int = 0
    basis_law_unresolved: int = 0
    expenditures_seen: int = 0
    expenditures_bundled: int = 0
    recipients_resolved_by_houjin_bangou: int = 0
    recipients_resolved_by_name: int = 0
    recipients_unresolved: int = 0


@dataclass(frozen=True)
class BudgetProjectRecord:
    project_id: str
    fiscal_year: str
    project_name: str
    ministry_houjin_bangou: str | None
    budget_amount: int | None
    basis_law_ids: tuple[str, ...]


@dataclass(frozen=True)
class ExpenditureRecord:
    project_id: str
    fiscal_year: str
    seq: int
    recipient_houjin_bangou: str | None
    amount: int
    label: str
    is_bundled: bool


@dataclass(frozen=True)
class UnresolvedBudgetReference:
    """emit_budgetがcore:UnresolvedReferenceを立てるための最小限の情報。

    `kind` で対象の軸を区別する: "ministry"/"basis_law" は主体がBudgetProject、
    "recipient" は主体がExpenditure(uris.pyの3つの専用URI関数に対応する)。
    """

    kind: Literal["ministry", "basis_law", "recipient"]
    fiscal_year: str
    project_id: str
    seq: int | None  # kind=="recipient" のときのみ意味を持つ
    key: str
    reason: str


@dataclass(frozen=True)
class BuildResult:
    projects: tuple[BudgetProjectRecord, ...]
    expenditures: tuple[ExpenditureRecord, ...]
    unresolved: tuple[UnresolvedBudgetReference, ...]
    stats: BuildStats = field(default_factory=BuildStats)


def build_projects(
    rows: Iterable[RsRow],
    ministry_ref: Mapping[str, list[Ministry]],
    laws_by_id: Mapping[str, LawRecord],
    laws_by_title: Mapping[str, list[LawRecord]],
    name_index: Mapping[str, list[str]] = {},  # 読み取り専用。呼び出し側が変更しない
) -> BuildResult:
    """`RsRow` を解決済みの `BudgetProjectRecord` / `ExpenditureRecord` にする。

    **ブリーフ本文の署名は `(rows, ministry_ref, laws_by_title)` の3引数だが、
    2つの理由で逸脱する(Task 7報告書の逸脱台帳を参照)**:

    1. B13(law_id直結を主にする裁定)後は law_id 単体でも引けないと経路2の
       (1)が実装できないため、`laws_by_id` を第4引数として加えた
       (law.derive_jurisdictionが `old_ministries` を追加したのと同じ理由)
    2. Step 3(名称正規化による支出先解決)の結果を受け取る `name_index` が
       ブリーフのどの引数にも対応しないため、第5引数として加えた(既定は空辞書
       — 名称フォールバックを使わない呼び出し元(例: build_recipient_name_index
       を回す前の1回目のパースだけを見たいテスト)を壊さないため)。
       `build_recipient_name_index` の出力をそのまま渡せる形
       (`dict[normalized_name, list[houjin_bangou]]`)

    返り値も3-tupleではなく `BuildResult`(dataclass。中に stats を持つ)にした
    — 解決率・束ね件数・未解決内訳を「消費者のいない記録」にしないため(欠陥型4)。

    `ministry_ref` は `law.to_ministry_reference` と同じ形
    (`dict[name, list[Ministry]]`)。
    """
    stats = BuildStats()
    projects: list[BudgetProjectRecord] = []
    expenditures: list[ExpenditureRecord] = []
    unresolved: list[UnresolvedBudgetReference] = []

    for row in rows:
        stats.projects_seen += 1

        ministry_matches = ministry_ref.get(row.ministry_name, [])
        ministry_bangou: str | None = None
        if len(ministry_matches) == 1:
            ministry_bangou = ministry_matches[0].houjin_bangou
            stats.ministries_resolved += 1
        else:
            reason = "AMBIGUOUS" if len(ministry_matches) > 1 else "NO_CANDIDATE"
            stats.ministries_unresolved += 1
            unresolved.append(
                UnresolvedBudgetReference(
                    kind="ministry", fiscal_year=row.fiscal_year, project_id=row.project_id,
                    seq=None, key=row.ministry_name, reason=reason,
                )
            )

        if row.budget_amount is None:
            stats.budget_amount_missing += 1

        basis_law_ids: list[str] = []
        seen_law_ids: set[str] = set()
        for citation in row.basis_law_citations:
            if not citation.law_id and not citation.law_title:
                # 引用そのものが無い行(rs_columns.py検証4)。抽出失敗ではないので
                # 未解決にも解決にも数えない
                stats.basis_law_out_of_scope += 1
                continue
            resolution = resolve_basis_law(citation, laws_by_id, laws_by_title)
            if resolution.record is not None:
                if resolution.method == "law_id":
                    stats.basis_law_resolved_by_id += 1
                elif resolution.method == "title_raw":
                    stats.basis_law_resolved_by_title_raw += 1
                else:
                    stats.basis_law_resolved_by_title_stripped += 1
                if resolution.record.law_id not in seen_law_ids:
                    seen_law_ids.add(resolution.record.law_id)
                    basis_law_ids.append(resolution.record.law_id)
            else:
                stats.basis_law_unresolved += 1
                unresolved.append(
                    UnresolvedBudgetReference(
                        kind="basis_law", fiscal_year=row.fiscal_year, project_id=row.project_id,
                        seq=None, key=resolution.key or "", reason=resolution.reason or "NO_CANDIDATE",
                    )
                )

        projects.append(
            BudgetProjectRecord(
                project_id=row.project_id,
                fiscal_year=row.fiscal_year,
                project_name=row.project_name,
                ministry_houjin_bangou=ministry_bangou,
                budget_amount=row.budget_amount,
                basis_law_ids=tuple(basis_law_ids),
            )
        )

        for seq, line in enumerate(row.expenditures):
            stats.expenditures_seen += 1
            if line.is_bundled:
                stats.expenditures_bundled += 1
            recipient = resolve_recipient(line, name_index)
            expenditures.append(
                ExpenditureRecord(
                    project_id=row.project_id,
                    fiscal_year=row.fiscal_year,
                    seq=seq,
                    recipient_houjin_bangou=recipient.houjin_bangou,
                    amount=line.amount,
                    label=line.recipient_name,
                    is_bundled=line.is_bundled,
                )
            )
            if recipient.method == "houjin_bangou":
                stats.recipients_resolved_by_houjin_bangou += 1
            elif recipient.method == "name":
                stats.recipients_resolved_by_name += 1
            elif recipient.reason is not None:
                stats.recipients_unresolved += 1
                unresolved.append(
                    UnresolvedBudgetReference(
                        kind="recipient", fiscal_year=row.fiscal_year, project_id=row.project_id,
                        seq=seq, key=line.recipient_name, reason=recipient.reason,
                    )
                )

    return BuildResult(
        projects=tuple(projects),
        expenditures=tuple(expenditures),
        unresolved=tuple(unresolved),
        stats=stats,
    )


__all__ = [
    "REQUIRED_GROUPS",
    "BasisLawCitation",
    "BudgetProjectRecord",
    "BuildResult",
    "BuildStats",
    "ExpenditureLine",
    "ExpenditureRecord",
    "LawResolution",
    "RecipientResolution",
    "RsRow",
    "UnresolvedBudgetReference",
    "build_projects",
    "build_recipient_name_index",
    "laws_index_by_title",
    "normalize_amount",
    "normalize_corporate_name",
    "parse_rs",
    "resolve_basis_law",
    "resolve_recipient",
]
