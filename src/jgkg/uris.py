"""URIの構築。設計書§4.2で固定したパターンをここだけで表現する。"""
import datetime
import re
from urllib.parse import quote

from jgkg.config import get_settings

HOUJIN_BANGOU_RE = re.compile(r"^\d{13}$")


def _base() -> str:
    return get_settings().base_uri


def org_uri(houjin_bangou: str) -> str:
    if not HOUJIN_BANGOU_RE.match(houjin_bangou):
        raise ValueError(f"法人番号は13桁の数字である必要がある: {houjin_bangou!r}")
    return f"{_base()}/id/org/{houjin_bangou}"


def law_uri(law_id: str) -> str:
    if not law_id:
        raise ValueError("法令IDが空である")
    return f"{_base()}/id/law/{quote(law_id, safe='')}"


def law_version_uri(
    law_id: str, date: datetime.date, amendment_law_num: str | None = None
) -> str:
    """`law:LawRevision` のURI。

    施行日だけを鍵にすると、同一施行日の改正が2件あれば1つのURIに合流し、
    `amendmentLawNum` が2値になって閉じたシェイプの `sh:maxCount 1` に違反する
    (レビュー指摘10。隔離の単位はグラフなので、その取得日の全法令が丸ごと
    落ちる)。改正法令番号を追加の鍵にして区別する。`None`(改正法令番号が
    無い行。現状のコネクタでは起こらないが型としてはあり得る)の場合は、
    従来どおり日付のみのURIにする(鍵の材料が無いところへ無理に材料を作らない)。
    """
    if amendment_law_num:
        return f"{law_uri(law_id)}/{date:%Y%m%d}_{quote(amendment_law_num, safe='')}"
    return f"{law_uri(law_id)}/{date:%Y%m%d}"


def unresolved_jurisdiction_uri(law_id: str, name: str) -> str:
    """経路1(法令番号→府省)で解決できなかった名称の `core:UnresolvedReference` ノードのURI。

    `name` だけを鍵にしない。複数の法令が同じ旧省庁名(例: 大蔵省令が数百件)を
    指すたびに1つのノードへ収束すると、UnresolvedReference の件数が法令ごとの
    ミス件数(CQ9が数えたいもの)ではなく「名称の種類数」に潰れてしまう
    """
    if not law_id or not name:
        raise ValueError("law_id と name はいずれも空であってはならない")
    return f"{_base()}/id/unresolved/jurisdiction/{quote(law_id, safe='')}/{quote(name, safe='')}"


def unresolved_ministry_uri(name: str) -> str:
    """府省参照表(名称主キー、裁定B12)で突合できなかった行の
    `core:UnresolvedReference` ノードのURI。

    `unresolved_jurisdiction_uri` と違い、鍵は `name` 単独でよい。参照表の
    1行=1つの「解決できるはずの府省」であり、同じ行が複数の法令から指される
    経路1(法令→府省)のような「件数が潰れる」問題が起こらないため
    (裁定B12: 未解決府省URIの鍵を ministry_code から名称(percent-encode)へ変更)
    """
    if not name:
        raise ValueError("name が空である")
    return f"{_base()}/id/unresolved/ministry/{quote(name, safe='')}"


def budget_uri(fiscal_year: str, project_id: str) -> str:
    """`budget:BudgetProject` のURI。

    `project_id` 単独では一意でない(同じ事業が複数の予算年度に渡って
    存在する。budget.yaml の `projectId` docstring参照)。同一性は
    `(project_id, fiscal_year)` の組で決まるため、両方をURIの材料にする
    (Task 7 brief §URI規約)。
    """
    if not fiscal_year or not project_id:
        raise ValueError("fiscal_year と project_id はいずれも空であってはならない")
    return f"{_base()}/id/budget/{quote(fiscal_year, safe='')}/{quote(project_id, safe='')}"


def expenditure_uri(fiscal_year: str, project_id: str, seq: int) -> str:
    """`budget:Expenditure` のURI。ハッシュの安定IDではなく連番(ソース内の行順)。

    **連番が版間で安定しない場合は Task 10 の置換セマンティクスが吸収する**
    (グラフごと置き換わるため、個別IDの持続性はこのタスクの要件ではない。
    Task 7 brief §URI規約)。
    """
    if seq < 0:
        raise ValueError(f"seq は0以上である必要がある: {seq!r}")
    return f"{budget_uri(fiscal_year, project_id)}/{seq}"


def unresolved_budget_ministry_uri(fiscal_year: str, project_id: str, name: str) -> str:
    """予算事業→府省の解決に失敗した名称の `core:UnresolvedReference` ノードのURI。

    `unresolved_ministry_uri`(参照表の1行が突合できない、という別の軸)とは
    意図的に別関数にする。あちらは名称のみを鍵にするが、こちらを名称のみで
    鍵にすると、同じ未突合の府省名を指す予算事業が何百件あっても1ノードに
    収束し、事業ごとの件数(法令の`unresolved_jurisdiction_uri`と同じ理由、
    CQ9型の集計)が測れなくなる。鍵に `(fiscal_year, project_id)` を含める。
    """
    if not fiscal_year or not project_id or not name:
        raise ValueError("fiscal_year・project_id・name はいずれも空であってはならない")
    return (
        f"{_base()}/id/unresolved/budget-ministry/"
        f"{quote(fiscal_year, safe='')}/{quote(project_id, safe='')}/{quote(name, safe='')}"
    )


def unresolved_basis_law_uri(fiscal_year: str, project_id: str, key: str) -> str:
    """予算事業の根拠法令引用が解決に失敗した場合の `core:UnresolvedReference` ノードのURI。

    `key` は試みた識別子(law_idが分かっていればそれ、無ければ法令名)。
    `unresolved_jurisdiction_uri` と同じ理由で `(fiscal_year, project_id)` を
    鍵に含める(同じ未解決の法令名/IDを指す予算事業が複数あっても1ノードに
    収束させない)。
    """
    if not fiscal_year or not project_id or not key:
        raise ValueError("fiscal_year・project_id・key はいずれも空であってはならない")
    return (
        f"{_base()}/id/unresolved/budget-basis-law/"
        f"{quote(fiscal_year, safe='')}/{quote(project_id, safe='')}/{quote(key, safe='')}"
    )


def unresolved_recipient_uri(fiscal_year: str, project_id: str, seq: int, key: str) -> str:
    """支出(Expenditure)の支出先が解決に失敗した場合の `core:UnresolvedReference` ノードのURI。

    支出自体が `expenditure_uri` で連番により一意なので、その連番を鍵に含める
    だけで事業内の衝突を避けられる(法令・府省の未解決URIのように名称だけで
    件数が潰れる心配は無い — 1つの支出行につき未解決ノードは最大1つ)。
    `key` は支出先名(束ね行なら「その他」等の表示名そのもの)。
    """
    if not fiscal_year or not project_id or not key:
        raise ValueError("fiscal_year・project_id・key はいずれも空であってはならない")
    if seq < 0:
        raise ValueError(f"seq は0以上である必要がある: {seq!r}")
    return f"{expenditure_uri(fiscal_year, project_id, seq)}/unresolved/{quote(key, safe='')}"


def graph_uri(source_id: str, fetched_on: datetime.date) -> str:
    if not source_id:
        raise ValueError("ソースIDが空である")
    return f"{_base()}/graph/{quote(source_id, safe='')}/{fetched_on:%Y-%m-%d}"


def term_uri(module: str, term: str) -> str:
    return f"{_base()}/def/{quote(module, safe='')}#{term}"
