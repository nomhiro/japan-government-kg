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

**センチネル(B18)は上記3段の外にある第4の分類**: `resolve_recipient`が
`SENTINEL_HOUJIN_BANGOU`を検出した場合、束ね行と同様にrecipientを設定
しないが、UnresolvedReferenceも立てない — 束ね行(「意図的に複数を集約」)・
未解決(「照合を試みたが一致しなかった」)のどちらでもなく、「そもそも
照合すべき法人ではない」という別の事実を表すため(task-7-review.md指摘1)。
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
# センチネル法人番号(task-7-review.md 指摘1。B18)
# =============================================================================

SENTINEL_HOUJIN_BANGOU: frozenset[str] = frozenset({"9999999999999"})
"""RSが「法人番号を持たない支払先」(個人・職員等)に使う13桁のセンチネル値。

法人番号の検査数字(9 - (Σ Pn×Qn mod 9))は基礎番号12桁がすべて9でも
満たされてしまう(Σ=162、162 mod 9=0、検査数字=9)ため、**検査数字では
この値を検出できない**。法人番号全件データ(1.26GB全走査)にこの値の出現は
0件(実在しない番号であることを確認済み)。実データでは13.6%の「支出先名・
法人番号ともに非空の行」がこの値を持ち(157,729行中21,460行)、Expenditureと
してemitされる行のうち9,922件(14.9%)がこの値を持つ(task-7-review.md指摘1)。

この値を法人番号として`budget:recipient`に直結すると、互いに無関係な
5,264通りの支払先名(個人Ａ〜、職員Ａ〜、その他 等)が単一のOrganization URIに
融合し、CQ2/CQ3(「この府省はどの法人にいくら支出したか」)で実在しない1法人が
6.27兆円で最大の支出先として首位に立つ(指摘1)。`resolve_recipient`はこの値を
明示的に除外する(B18裁定)。

**zenken fixture(houjin_bangou_sample.csv等)側で同じ文字列を「明らかに合成」
の負例(R45)として使っているのとは意味が違う**(偶然の一致。統一を意図した
ものではない) — zenken側は「テストがR45の負例として作った、実データには
存在しない値」、RS側は「RS自身が実データにそのまま書き込む、実在するが
法人ではない支払先を表すセンチネル」。
"""


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

    `role`([16]事業を行う上での役割。B20・task-7-review.md指摘8)は
    **ブロック行にしか物理的に現れない**(この行自身の列16は常に空。
    ブロック番号を介してブロック行から引く。§Task 7照合記録参照)。verbatim
    (解釈しない) — 「一次/二次支出先」等の集計セマンティクスはTask 9が決める。
    """

    recipient_name: str
    recipient_houjin_bangou: str | None
    is_bundled: bool
    amount: int
    role: str = ""


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

    prior_year_executed_amount は直前の事業年度(fiscal_year - 1)の執行額
    （合計）。B19(task-9-brief.md申し送り)が実測した「支出先の金額
    (payee_payment_information)はレビューシート年度そのものではなく、
    その1年前の執行実績と中央値1.0で一致する」対応の分母に使う値で、
    B24(6)(裁定B24。task-10-brief.md引き継ぐ決定)が要求する「合計/執行額の
    比の分布」という**観測**専用(RDFには出さない。ゲートにも使わない —
    正しい事業でも一致は32%のみと確定済み)。budget_amountと同じ理由で
    見つからなければ欠損として`None`。
    """

    project_id: str
    fiscal_year: str
    project_name: str
    ministry_name: str
    budget_amount: int | None
    prior_year_executed_amount: int | None = None
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


@dataclass
class RsParseStats:
    """`parse_rs` が解析中に判明した、`build_projects` に渡らない件数(欠陥型4対策)。

    organization.ParseStatsと同じ設計 — **判定に使って捨てるのではなく、
    呼び出し側に返す。** payee_payment_informationの明細行(集計行[23]が空で
    契約単位の内訳[25]が非空)は構造として毎回無視するのが正しい動作だが、
    [23]も[25]も空の行(rs_columns.py照合記録「検証6追記」。実測755行。
    金額が本当に欠落している)は`RsRow.expenditures`がそもそも欠損行を表現
    できる形を持たないため、`parse_rs`を抜けた後では誰も数えられなくなる
    (§8.2「欠損を0と混同しない」の対象なのに、渡す先が無い)。この件数だけは
    parse段階でここに数える。

    task-7-review.md 指摘5・11(要記録・軽微)で、payee_payment_informationの
    ブロック行([18]支出先名が空。20,701行)とproject_summaryの複数行構造
    (241事業・267行)も同様に「渡す先が無いので数えるならここ」と判明した
    ため追加した。恒等式(payee: 全行=ブロック行+構造上の明細行+真の欠落+
    Expenditure。spine: 全行=事業数+重複行)がすべて閉じることをテストで
    固定する(指摘の「読んだ行数=…」を、束ね・センチネル・未解決がExpenditureの
    部分集合であることを踏まえて次元の合う形に直したもの。報告書に明記)。
    """

    payee_rows_missing_amount: int = 0
    payee_rows_block: int = 0
    payee_rows_contract_detail: int = 0
    project_summary_duplicate_rows: int = 0


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

    `rs_columns.find_budget_aggregate_row(..., allow_missing=True)` の
    薄いラッパー(task-7-review.md指摘10)。以前はここで選択規則(予算年度が
    一致し当初予算(合計)が非空の行を1件選ぶ)を逐語で複製し、
    `len(matches) > 1` のときだけヘルパを呼びつつ**戻り値を捨てて**
    ローカルの`matches[0]`を返していた — 2つの規則が同じ内容である限りは
    等価だが、将来どちらか一方だけを直すとヘルパの選んだ行と違う値を
    例外も出さずに返す経路になっていた(指摘3の変異実験がこの経路を
    実際に露呈させた)。規則を1箇所(`find_budget_aggregate_row`)に集約し、
    ここは`allow_missing=True`を渡して0件をNoneとして受けるだけにする
    (「その事業がbudget_summaryに1行も無い/この事業年度の行が無い」は、
    まだ実データで確認していないだけの正当な欠損として区別する。実測:
    2026-08-23取得の全5,794事業で0件のはず。`rows_for_project`が空の場合も
    `allow_missing=True`の下でNoneになるので、空チェックを別に持つ必要はない)。
    """
    row = rs_columns.find_budget_aggregate_row(
        rows_for_project, fiscal_year, allow_missing=True
    )
    if row is None:
        return None
    idx_amount = rs_columns.RS_FILES["budget_summary"].col["budget_amount"]
    return normalize_amount(row[idx_amount])


def _prior_year_executed_amount(
    rows_for_project: list[list[str]], fiscal_year: str
) -> int | None:
    """直前の事業年度(fiscal_year - 1)の執行額（合計)を取る(B24(6)の観測用)。

    `_current_year_budget_amount` と同じ選択規則(`find_budget_aggregate_row`)
    を1年ずらして呼ぶだけの薄いラッパー — 規則自体は1箇所(rs_columns.py)に
    集約されているので、ここで選択ロジックを複製しない。見つからなければ
    `None`(そもそも1年目の事業でbudget_summaryに前年度の行が無い等、
    実データではまだ確認していない欠損として扱う。`allow_missing=True`)。
    """
    prior_year = str(int(fiscal_year) - 1)
    row = rs_columns.find_budget_aggregate_row(
        rows_for_project, prior_year, allow_missing=True
    )
    if row is None:
        return None
    idx_executed = rs_columns.RS_FILES["budget_summary"].col["executed_amount"]
    return normalize_amount(row[idx_executed])


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


def _block_roles_for(
    rows_for_project: list[list[str]], idx_name: int, idx_block: int, idx_role: int
) -> dict[str, str]:
    """(ブロック番号 → [16]役割の文言)の対応を作る(B20)。

    [16]は**ブロック行(支出先名が空の行)にしか物理的に現れない** — 支出先行
    自身の[16]は常に空文字(実データ全193,912行で確認。
    rs_columns.py照合記録「検証12」)。1ブロックの支出先は
    複数の物理行に分かれる(検証6)ため、支出先行を作る前にブロック行だけを
    1パス先取りして対応表を作る必要がある(1回のループで両方をこなそうとすると
    「ブロック行が対応する支出先行より必ず先に現れる」という、検証していない
    ファイル順序への依存が生まれるため、2パスにする)。

    **1ブロックに物理行が2件以上ある実例が1件だけある**(project_id=1409・
    ブロックA・株式会社日本政策金融公庫。[15]支出先の数='0'/役割='-'の行と、
    [15]='1'/役割='※信用保証協会が代位弁済を行った場合...'の行が両方存在する。
    全20,701ブロック行のうち、この1件だけが(project_id,ブロック番号)の
    複合キーに対して2行を持つ)。**後に現れた行の役割で上書きする**(単純な
    後勝ち。この1件のためだけに「どちらがより完全な記述か」を判定する規則を
    作らない — 実害は最大1ブロック)。
    """
    out: dict[str, str] = {}
    for r in rows_for_project:
        if not r[idx_name].strip():  # ブロック行
            out[r[idx_block]] = r[idx_role].strip()
    return out


def _expenditures_for(
    rows_for_project: list[list[str]], stats: RsParseStats
) -> tuple[ExpenditureLine, ...]:
    """支出先の集計行だけを取り、明細行(契約単位の内訳)は無視する。

    rs_columns.py照合記録「検証6」: 1支出先につき[23]支出先の合計支出額が
    非空の行はちょうど1件(実データ74,291組全件で確認済み)。単純な行フィルタで
    足りる(budget_summaryのようなfind_*_aggregate_rowは不要)。

    [23]が空の行には2種類ある(検証6追記): (a) [25]契約単位の内訳が非空の
    構造上の明細行(想定内。黙って無視するのが正しい動作。
    `stats.payee_rows_contract_detail` に数える)、(b) [23]も[25]も空で
    金額が本当に欠落している行(実測755行。`stats.payee_rows_missing_amount`
    に数える)。ブロック行(支出先名が空。実測20,701行。[23][25]とも
    非空の行は0件=金額の喪失なし。指摘11)は `stats.payee_rows_block` に
    数える。3つとも数えないと、`RsRow.expenditures`が該当行を表現できる形を
    持たないため、この関数を抜けた時点で誰も数えられなくなる
    (欠陥型4「消費者のいない記録」)。
    """
    spec = rs_columns.RS_FILES["payee_payment_information"]
    idx_name = spec.col["recipient_name"]
    idx_bangou = spec.col["recipient_houjin_bangou"]
    idx_flag = spec.col["recipient_other_flag"]
    idx_amount = spec.col["expenditure_amount"]
    idx_contract_amount = spec.col["contract_amount"]
    idx_block = spec.col["block_number"]
    idx_role = spec.col["expenditure_role"]

    block_role = _block_roles_for(rows_for_project, idx_name, idx_block, idx_role)

    out = []
    for r in rows_for_project:
        name = r[idx_name].strip()
        if not name:
            stats.payee_rows_block += 1  # ブロック行(支出先名が空)
            continue
        amount_raw = r[idx_amount]
        amount = normalize_amount(amount_raw)
        if amount is None:
            if normalize_amount(r[idx_contract_amount]) is None:
                stats.payee_rows_missing_amount += 1  # (b) 本当に欠落
            else:
                stats.payee_rows_contract_detail += 1  # (a) 構造上の明細行
            continue
        bangou = r[idx_bangou].strip() or None
        is_bundled = _is_bundled_row(r, idx_flag, idx_name)
        out.append(
            ExpenditureLine(
                recipient_name=name,
                recipient_houjin_bangou=None if is_bundled else bangou,
                is_bundled=is_bundled,
                amount=amount,
                role=block_role.get(r[idx_block], ""),
            )
        )
    return tuple(out)


def parse_rs(
    paths: Mapping[str, Path], stats: RsParseStats | None = None
) -> Iterator[RsRow]:
    """RSの複数ファイルを読み、project_idで結合した `RsRow` を生成する。

    `paths` は group_key(rs_columns.RS_FILESのキー) → ファイルパス(配布形態の
    zip、またはfixtureの生CSV)。`REQUIRED_GROUPS` の4つが必須(organization_
    informationはRS_COLがどの論理名にも使わないため対象外。rs_columns.py参照)。
    project_id の集合は project_summary を正準の出典とする(RS_COLの設計。
    他の3ファイルも実データでは同じ集合を持つが、project_summaryが「この
    事業年度のレビューシートに載っている事業」の正の出典)。

    `stats` に `RsParseStats` を渡すと、`build_projects` が受け取れない
    parse段階の欠損件数(`payee_rows_missing_amount`)がそこに書き込まれる
    (organization.parse_fileのstats引数と同じ設計)。渡さなければ内部で
    使い捨てる(件数を要らない呼び出し元(単発テスト等)を壊さないため)。
    """
    missing = [g for g in REQUIRED_GROUPS if g not in paths]
    if missing:
        raise ValueError(f"paths に必須のグループが無い: {missing}")

    st = stats if stats is not None else RsParseStats()

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
        else:
            # project_summaryも「1事業=複数行」構造を持つ(task-7-review.md
            # 指摘5。241事業・267行。[22]主要経費のみ行間で異なり、採用する
            # project_name/ministry_name/fiscal_yearは241事業全件で一致する
            # ことを確認済み — rs_columns.py照合記録参照)。先頭行だけを採り、
            # 以降を捨てるのは正しい動作だが、捨てた行数を数えないと「渡す先が
            # 無いので誰も数えられない」記録になる(欠陥型4)
            st.project_summary_duplicate_rows += 1

    budget_by_pid = _group_by_project_id(_group_rows("budget_summary", paths["budget_summary"]))
    law_by_pid = _group_by_project_id(
        _group_rows("policy_measure_laws_and_regulations", paths["policy_measure_laws_and_regulations"])
    )
    payee_by_pid = _group_by_project_id(
        _group_rows("payee_payment_information", paths["payee_payment_information"])
    )

    for pid in order:
        project_name, ministry_name, fiscal_year = spine[pid]
        rows_for_project = budget_by_pid.get(pid, [])
        yield RsRow(
            project_id=pid,
            fiscal_year=fiscal_year,
            project_name=project_name,
            ministry_name=ministry_name,
            budget_amount=_current_year_budget_amount(rows_for_project, fiscal_year),
            prior_year_executed_amount=_prior_year_executed_amount(rows_for_project, fiscal_year),
            basis_law_citations=_basis_law_citations_for(law_by_pid.get(pid, [])),
            expenditures=_expenditures_for(payee_by_pid.get(pid, []), st),
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
    """`resolve_recipient` の結果。

    束ね行・センチネル行はどちらも method/reason ともに `None`
    (解決を試みていないことを型で表す — NO_CANDIDATEと紛れさせない)。
    `is_sentinel` でこの2つを区別する: 束ね行は「複数の支払先を意図的に
    集約した」行、センチネル行は「そもそも法人ではない支払先(個人・職員等)」
    の行で、どちらも`budget:recipient`は張らないが、センチネル行は
    **UnresolvedReferenceも作らない**(照合すべき実体がそもそも存在しない
    ので「未解決」と呼ぶと嘘になる。B18・task-7-review.md指摘1)。
    """

    houjin_bangou: str | None
    method: Literal["houjin_bangou", "name"] | None
    reason: Literal["NO_CANDIDATE", "AMBIGUOUS"] | None
    is_sentinel: bool = False


def resolve_recipient(
    line: ExpenditureLine, name_index: Mapping[str, list[str]]
) -> RecipientResolution:
    """支出先1件を解決する(B14: 法人番号直結 → 名称正規化の一意一致 → 未解決)。

    束ね行(is_bundled)は解決を試みない(B14: 「その他」への束ね行は名称解決の
    対象ではなく、束ね行として計数する。黙って落とさない — Expenditure自体は
    呼び出し側(build_projects)が作る)。

    **センチネル法人番号(`SENTINEL_HOUJIN_BANGOU`。B18・指摘1)は法人番号直結
    の対象から除外する** — 束ね行の判定の直後、法人番号直結の判定より前に
    見る(法人番号が非空でもセンチネルなら直結しない。束ね行チェックを先に
    置く理由は§8.1と同じ順序で、束ね行はそもそも法人番号を見ない設計だから)。
    """
    if line.is_bundled:
        return RecipientResolution(None, None, None)
    if line.recipient_houjin_bangou in SENTINEL_HOUJIN_BANGOU:
        return RecipientResolution(None, None, None, is_sentinel=True)
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
    recipients_sentinel: int = 0
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
    # B24(6): 観測専用(RDFには出さない。emit_budgetの対象外)。RsRowの
    # 同名フィールドのdocstring参照
    prior_year_executed_amount: int | None = None


@dataclass(frozen=True)
class ExpenditureRecord:
    project_id: str
    fiscal_year: str
    seq: int
    recipient_houjin_bangou: str | None
    amount: int
    label: str
    is_bundled: bool
    # センチネル行(B18)の表示名。`recipient_houjin_bangou`がNoneでも
    # 「未解決」ではない行だけがこれを持つ(束ね行はlabelで足りるので持たない
    # — budget.yaml Expenditureのdocstring参照)
    payee_label: str | None = None
    role: str = ""


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
                prior_year_executed_amount=row.prior_year_executed_amount,
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
                    # センチネル行だけがpayeeLabelを持つ(B18)。束ね行は
                    # labelで表示名を既に持つため、ここでは重複させない
                    payee_label=line.recipient_name if recipient.is_sentinel else None,
                    role=line.role,
                )
            )
            if recipient.is_sentinel:
                # B18: 法人でない支払先(センチネル)。「未解決」ではない
                # (照合すべき実体が無い)ので UnresolvedReference は作らない
                stats.recipients_sentinel += 1
            elif recipient.method == "houjin_bangou":
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
    "SENTINEL_HOUJIN_BANGOU",
    "BasisLawCitation",
    "BudgetProjectRecord",
    "BuildResult",
    "BuildStats",
    "ExpenditureLine",
    "ExpenditureRecord",
    "LawResolution",
    "RecipientResolution",
    "RsParseStats",
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
