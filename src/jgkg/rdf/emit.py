"""Pydanticモデル → 名前付きグラフ。

データは「ソース×取得日」の名前付きグラフに入れる。そのグラフについての
PROV-O記述は、置換の単位を揃えるため専用のメタデータグラフに入れる。
"""
import datetime
from collections.abc import Iterable, Mapping
from pathlib import Path

from rdflib import RDF, XSD, Dataset, Graph, Literal, Namespace, URIRef
from rdflib.namespace import SKOS

from jgkg.config import get_settings
from jgkg.rdf.provenance import provenance_graph
from jgkg.transform.law import JurisdictionResult, LawRecord
from jgkg.transform.ministry import Ministry, UnmatchedMinistry
from jgkg.transform.ministry_succession import AbolishedMinistryRecord
from jgkg.transform.organization import Organization
from jgkg.transform.rs import (
    AnnualBudgetRecord,
    BudgetProjectRecord,
    ExpenditureBlockRecord,
    ExpenditureRecord,
    IndirectCostRecord,
    UnresolvedBudgetReference,
)
from jgkg.uris import (
    abolished_organ_uri,
    annual_budget_uri,
    budget_uri,
    expenditure_block_uri,
    expenditure_uri,
    graph_uri,
    indirect_cost_uri,
    law_uri,
    law_version_uri,
    org_uri,
    unresolved_basis_law_uri,
    unresolved_budget_ministry_uri,
    unresolved_jurisdiction_uri,
    unresolved_ministry_uri,
    unresolved_recipient_uri,
)

#: `AnnualBudget` が書く金額系の述語(裁定B99)。
#:
#: **モジュール定数にしているのは、検査から見えるようにするためである。**
#: `tests/test_schema_consistency.py` の表示名の被覆テストは、emitが書く述語を
#: `ns["budget"]["…"]` というリテラルの呼び出しから集める。ここをループ変数
#: (`ns["budget"][predicate]`)だけで書くと**8件がまるごと検査の視野から外れ、
#: 日本語の表示名が無いまま通ってしまう** —— controllerが手書き一覧を導出に
#: 切り替えた直後に実際に踏んだ。定数にしておけばテスト側が値として読める。
#:
#: **新しく述語名を動的に組み立てる箇所を足すときは、同じように定数へ出し、
#: テスト側の `_dynamic_predicate_names()` に加えること。**
ANNUAL_BUDGET_AMOUNT_PREDICATES: tuple[str, ...] = (
    "initialBudget",
    "supplementaryBudget",
    "carriedOverFromPreviousYear",
    "reserveFund",
    "totalBudgetAvailable",
    "executedAmount",
    "carriedOverToNextYear",
    "nextYearRequest",
)


def _ns() -> dict[str, Namespace]:
    base = get_settings().base_uri
    return {
        "core": Namespace(f"{base}/def/core#"),
        "org": Namespace(f"{base}/def/org#"),
        "law": Namespace(f"{base}/def/law#"),
        "budget": Namespace(f"{base}/def/budget#"),
    }


class _NSProxy:
    """テストから emit.NS["core"] で参照できるようにする薄いラッパ。"""

    def __getitem__(self, key: str) -> Namespace:
        return _ns()[key]


NS = _NSProxy()


def _metadata_graph_uri() -> str:
    return f"{get_settings().base_uri}/graph/provenance"


def _new_dataset(
    source_id: str,
    fetched_on: datetime.date,
    sha256: str | Iterable[str] | None,
    recorded_on: datetime.date | None = None,
) -> tuple[Dataset, Graph]:
    # default_union=True にしないと、rdflib の Dataset は既定でクエリを
    # デフォルトグラフだけに限定する(名前付きグラフを跨いだ ds.objects() 等が
    # 常に空になる)。データもメタデータも名前付きグラフに入れる設計(デフォルト
    # グラフは使わない)なので、これが無いと出典の記述に到達できない
    ds = Dataset(default_union=True)
    gid = graph_uri(source_id, fetched_on)
    data = ds.graph(URIRef(gid))

    meta = ds.graph(URIRef(_metadata_graph_uri()))
    for triple in provenance_graph(
        gid, source_id, fetched_on, sha256=sha256, recorded_on=recorded_on
    ):
        meta.add(triple)
    return ds, data


def emit_organizations(
    orgs: Iterable[Organization],
    source_id: str,
    fetched_on: datetime.date,
    sha256: str | None = None,
    recorded_on: datetime.date | None = None,
) -> Dataset:
    ns = _ns()
    ds, data = _new_dataset(source_id, fetched_on, sha256, recorded_on)

    for org in orgs:
        s = URIRef(org.uri)
        # 型は「最も具体的なもの1つ」だけを出す。上位型(core:Agent 等)を材質化
        # しないのは、LinkMLの生成SHACLが閉じたシェイプであり、上位クラスが
        # 宣言していないプロパティが違反になるため。上位型はOWLの階層から導ける
        most_specific = "GovernmentOrgan" if org.is_government_organ else "Organization"
        data.add((s, RDF.type, ns["org"][most_specific]))
        data.add((s, SKOS.prefLabel, Literal(org.name, lang="ja")))
        data.add((s, ns["org"]["houjinBangou"], Literal(org.houjin_bangou)))
        data.add((s, ns["org"]["organizationKindCode"], Literal(org.kind_code)))
        if org.prefecture:
            data.add((s, ns["org"]["prefectureName"], Literal(org.prefecture, lang="ja")))
        if org.city:
            data.add((s, ns["org"]["cityName"], Literal(org.city, lang="ja")))
    return ds


def emit_ministries(
    ministries: Iterable[Ministry],
    unmatched: Iterable[UnmatchedMinistry],
    source_id: str,
    fetched_on: datetime.date,
    sha256: str | None = None,
    recorded_on: datetime.date | None = None,
) -> Dataset:
    ns = _ns()
    ds, data = _new_dataset(source_id, fetched_on, sha256, recorded_on)

    for m in ministries:
        s = URIRef(m.uri)
        data.add((s, RDF.type, ns["org"]["Ministry"]))
        # ministryCode は現行コードの一次資料が見つかった行だけが持つ(裁定B12)。
        # 無い行にまで `Literal(None)` を書くと、KGに"None"という文字列リテラルが
        # 実在してしまう(欠落の表現として最悪の形。SHACLの sh:maxCount 1は
        # 満たすがCQを読む人間を騙す)
        if m.ministry_code is not None:
            data.add((s, ns["org"]["ministryCode"], Literal(m.ministry_code)))

    for u in unmatched:
        # 未解決府省URIの鍵は名称(裁定B12)。主キーが名称に変わったため、
        # ministry_code(欠落しうる・任意)ではなく必須の name を鍵にする
        s = URIRef(unresolved_ministry_uri(u.name))
        data.add((s, RDF.type, ns["core"]["UnresolvedReference"]))
        data.add((s, ns["core"]["unresolved_text"], Literal(u.name, lang="ja")))
        data.add((s, ns["core"]["unresolved_reason"], Literal(u.reason)))
        # ドメイン固有の org:ministryCode ではなく core の汎用キーに入れる。
        # UnresolvedReference は org: のプロパティを宣言しておらず、閉じたシェイプに
        # 違反するため。CQ P0-5 が core:UnresolvedReference を直接問えるよう
        # サブクラス化はしない(推論なしのFusekiでは上位型が引けない)。
        # 値そのものも ministry_code ではなく name にする(鍵と同じ理由)
        data.add((s, ns["core"]["unresolved_key"], Literal(u.name)))
    return ds


def _iso_date_literal(value: str) -> Literal:
    return Literal(datetime.date.fromisoformat(value), datatype=XSD.date)


def emit_abolished_ministries(
    records: Iterable[AbolishedMinistryRecord],
    source_id: str,
    fetched_on: datetime.date,
    sha256: str | None = None,
    recorded_on: datetime.date | None = None,
) -> Dataset:
    """C-1(ministry_succession)が解決した`AbolishedGovernmentOrgan`を出す(C-3)。

    `emit_organizations`/`emit_ministries`と同じ、変換とemitの分離
    (`build_abolished_ministries`が組み立てた記録をそのまま書くだけで、
    後継名→houjin_bangouの解決や裁定2の除外はここでは行わない)。
    """
    ns = _ns()
    ds, data = _new_dataset(source_id, fetched_on, sha256, recorded_on)

    for rec in records:
        s = URIRef(abolished_organ_uri(rec.name))
        data.add((s, RDF.type, ns["org"]["AbolishedGovernmentOrgan"]))
        data.add((s, SKOS.prefLabel, Literal(rec.name, lang="ja")))
        data.add((s, ns["org"]["abolitionDate"], _iso_date_literal(rec.abolition_date)))
        for houjin_bangou in rec.successor_houjin_bangou:
            data.add((s, ns["org"]["succeededBy"], URIRef(org_uri(houjin_bangou))))
    return ds


def emit_laws(
    records: Iterable[LawRecord],
    jurisdictions: Mapping[str, JurisdictionResult],
    source_id: str,
    fetched_on: datetime.date,
    sha256: str | None = None,
    recorded_on: datetime.date | None = None,
) -> Dataset:
    """`LawRecord` を `law:Law`(+ 施行日のある改正は `law:LawRevision`)として書く。

    `jurisdictions` は `derive_jurisdiction` の結果を `law_id` で引けるようにした
    もの(経路1の対象外だった法令は key が無い。その場合 `jurisdiction` も
    `UnresolvedReference` も出さない)。emit 自身は解決ロジックを持たない
    (`emit_organizations`/`emit_ministries` と同じ、変換とemitの分離)。

    未解決の名称は `law:jurisdiction` を設定せず、別に `core:UnresolvedReference`
    を立てる(`law.yaml` の `jurisdiction` の説明どおり — このスロット自体は
    未解決を表さない)。ノードのURIは `(law_id, 抽出名)` の両方を材料にする
    (`uris.unresolved_jurisdiction_uri`)。名称だけを鍵にすると、同じ旧省庁名を
    指す法令が何百件あっても1つのノードに収束してしまい、CQ9が数えたい
    「法令ごとの件数」が測れなくなるため。ただし `core:unresolved_key` の値
    そのものは抽出名(ブリーフStep5の指定通り)。
    """
    ns = _ns()
    ds, data = _new_dataset(source_id, fetched_on, sha256, recorded_on)

    for record in records:
        s = URIRef(law_uri(record.law_id))
        # 型は最も具体的な1つだけ(emit_organizations と同じ理由。R1)
        data.add((s, RDF.type, ns["law"]["Law"]))
        data.add((s, SKOS.prefLabel, Literal(record.law_title, lang="ja")))
        data.add((s, ns["law"]["lawId"], Literal(record.law_id)))
        data.add((s, ns["law"]["lawNum"], Literal(record.law_num)))
        data.add((s, ns["law"]["lawNumType"], Literal(record.law_num_type)))
        data.add((s, ns["law"]["lawTitle"], Literal(record.law_title, lang="ja")))
        for a in record.abbrev:
            data.add((s, ns["law"]["abbrev"], Literal(a, lang="ja")))
        data.add((s, ns["law"]["promulgationDate"], _iso_date_literal(record.promulgation_date)))
        data.add((s, ns["law"]["repealStatus"], Literal(record.repeal_status)))

        jr = jurisdictions.get(record.law_id)
        if jr is not None:
            for houjin_bangou in jr.resolved:
                data.add((s, ns["law"]["jurisdiction"], URIRef(org_uri(houjin_bangou))))
            # C-3裁定: 発令した当時の組織(AbolishedGovernmentOrgan)自身を
            # 指す。現存の後継への読み替えではない(「昭和二十六年大蔵省令」の
            # 所管は大蔵省であり、財務省が1951年に発したと主張するのは偽)
            for name in jr.resolved_abolished:
                data.add((s, ns["law"]["jurisdiction"], URIRef(abolished_organ_uri(name))))
            for u in jr.unresolved:
                node = URIRef(unresolved_jurisdiction_uri(record.law_id, u.name))
                data.add((node, RDF.type, ns["core"]["UnresolvedReference"]))
                data.add((node, ns["core"]["unresolved_text"], Literal(u.name, lang="ja")))
                data.add((node, ns["core"]["unresolved_reason"], Literal(u.reason)))
                data.add((node, ns["core"]["unresolved_key"], Literal(u.name)))
                # 未解決ノード→法令(裁定B8)。CQ9等が未解決ノードから主体へ
                # グラフパターンで辿れるようにする(URIの再構成を要しない)
                data.add((node, ns["core"]["unresolvedFor"], s))

        for rev in record.revisions:
            if not rev.amendment_enforcement_date:
                # 施行日が無い改正(未施行・将来施行の予定日のみ等)はLawRevisionの
                # URI(law_version_uri)の材料が無いため、このタスクの範囲では
                # 見送る(§8.2の未解決の握り潰しとは異なる — Law本体は落とさず、
                # この改正イベント1件だけを作れない)
                continue
            rev_date = datetime.date.fromisoformat(rev.amendment_enforcement_date)
            # 改正法令番号も鍵に加える(指摘10。同一施行日の改正2件が1ノードに
            # 合流してsh:maxCount 1に違反することを防ぐ)
            rs = URIRef(law_version_uri(record.law_id, rev_date, rev.amendment_law_num))
            data.add((rs, RDF.type, ns["law"]["LawRevision"]))
            data.add((rs, ns["law"]["lawId"], Literal(record.law_id)))
            data.add(
                (rs, ns["law"]["amendmentEnforcementDate"], Literal(rev_date, datatype=XSD.date))
            )
            if rev.amendment_law_num:
                data.add((rs, ns["law"]["amendmentLawNum"], Literal(rev.amendment_law_num)))
            data.add((rs, ns["law"]["revisionStatus"], Literal(rev.revision_status)))

    return ds


def emit_budget(
    projects: Iterable[BudgetProjectRecord],
    expenditures: Iterable[ExpenditureRecord],
    unresolved: Iterable[UnresolvedBudgetReference],
    source_id: str,
    fetched_on: datetime.date,
    sha256: str | Iterable[str] | None = None,
    recorded_on: datetime.date | None = None,
    blocks: Iterable[ExpenditureBlockRecord] = (),
    indirect_costs: Iterable[IndirectCostRecord] = (),
    annual_budgets: Iterable[AnnualBudgetRecord] = (),
) -> Dataset:
    """`rs.build_projects` の出力を `budget:BudgetProject` / `budget:Expenditure`

    として書く(Task 7 brief Step 5)。`emit_laws`/`emit_organizations` と同じ、
    変換とemitの分離(emit自身は解決ロジックを持たない)。

    `sha256` は複数件を受ける(RSは1つのグラフが project_summary/budget_summary/
    policy_measure_laws_and_regulations/payee_payment_information の4本(裁定B97
    以降は payee_payment_block_connection も加えて5本)の物理ファイルから
    作られるため。`provenance_graph` の複数件対応を実際に使う唯一の呼び出し元)。

    `unresolved` は3種類が混在する(`UnresolvedBudgetReference.kind`)。
    ministry/basis_law は主体がBudgetProject、recipientは主体がExpenditureで、
    それぞれ別のURI関数(`uris.unresolved_budget_ministry_uri` 等)を使う
    (law.pyのunresolved_jurisdiction_uriと同じ理由 — 同じ未解決の名称/IDを
    指す事業が複数あっても1ノードに収束させない)。

    **`blocks`/`indirect_costs`(裁定B97)は既定が空**——5-2
    (payee_payment_block_connection)を渡していない呼び出し元(既存のテスト等)を
    壊さないため。`projects`/`expenditures`と同じ名前付きグラフに入れる
    (同じ一次資料の同じ取得日から作る事実であり、置換の単位も同じ)。

    **`annual_budgets`(裁定B99)も既定が空**で、同じ名前付きグラフに入れる
    (2-1という同じ一次資料の同じ取得日から作る事実。`projects`の
    `budgetAmount`とまったく同じ列から来る)。
    """
    ns = _ns()
    ds, data = _new_dataset(source_id, fetched_on, sha256, recorded_on)

    unresolved_for_project: dict[tuple[str, str], list[UnresolvedBudgetReference]] = {}
    unresolved_for_expenditure: dict[tuple[str, str, int], list[UnresolvedBudgetReference]] = {}
    for u in unresolved:
        if u.kind == "recipient":
            unresolved_for_expenditure.setdefault(
                (u.fiscal_year, u.project_id, u.seq), []
            ).append(u)
        else:
            unresolved_for_project.setdefault((u.fiscal_year, u.project_id), []).append(u)

    for project in projects:
        s = URIRef(budget_uri(project.fiscal_year, project.project_id))
        # 型は最も具体的な1つだけ(emit_organizations/emit_laws と同じ理由。R1)
        data.add((s, RDF.type, ns["budget"]["BudgetProject"]))
        data.add((s, SKOS.prefLabel, Literal(project.project_name, lang="ja")))
        data.add((s, ns["budget"]["projectId"], Literal(project.project_id)))
        data.add((s, ns["budget"]["projectName"], Literal(project.project_name, lang="ja")))
        data.add((s, ns["budget"]["fiscalYear"], Literal(int(project.fiscal_year))))
        # **ゼロ予算は有効な値**(rs_columns.py参照)。`if project.budget_amount:` は
        # 0を欠損と誤認して省略してしまうため、`is not None` で判定する
        if project.budget_amount is not None:
            data.add((s, ns["budget"]["budgetAmount"], Literal(project.budget_amount)))
        if project.ministry_houjin_bangou is not None:
            data.add((s, ns["budget"]["ministry"], URIRef(org_uri(project.ministry_houjin_bangou))))
        for law_id in project.basis_law_ids:
            data.add((s, ns["budget"]["basisLaw"], URIRef(law_uri(law_id))))

        for u in unresolved_for_project.get((project.fiscal_year, project.project_id), []):
            if u.kind == "ministry":
                node = URIRef(unresolved_budget_ministry_uri(u.fiscal_year, u.project_id, u.key))
            else:
                node = URIRef(unresolved_basis_law_uri(u.fiscal_year, u.project_id, u.key))
            data.add((node, RDF.type, ns["core"]["UnresolvedReference"]))
            data.add((node, ns["core"]["unresolved_text"], Literal(u.key, lang="ja")))
            data.add((node, ns["core"]["unresolved_reason"], Literal(u.reason)))
            data.add((node, ns["core"]["unresolved_key"], Literal(u.key)))
            data.add((node, ns["core"]["unresolvedFor"], s))

    # =========================================================================
    # 裁定B97: 資金の流れ。支出(Expenditure)だけでは同じお金を段ごとに何度も
    # 数えてしまう(実測29.9兆円の重複)。ブロックと`paidByGovernment`があれば
    # 入口だけを合計できる(schema/budget.yaml の ExpenditureBlock 参照)
    # =========================================================================
    for block in blocks:
        s = URIRef(expenditure_block_uri(block.fiscal_year, block.project_id, block.block_id))
        data.add((s, RDF.type, ns["budget"]["ExpenditureBlock"]))
        # ブロック名は core:label(実際の述語は skos:prefLabel。Expenditureの
        # labelと同じ理由 — `ns["core"]["label"]`は閉じたシェイプに存在しない)。
        # 5-1にも5-2にも名前が無いブロックは空文字になるので書かない
        # (§8.2「欠損を空文字列で表現しない」)
        if block.block_name:
            data.add((s, SKOS.prefLabel, Literal(block.block_name, lang="ja")))
        data.add((s, ns["budget"]["blockId"], Literal(block.block_id)))
        data.add(
            (s, ns["budget"]["project"], URIRef(budget_uri(block.fiscal_year, block.project_id)))
        )
        data.add((s, ns["budget"]["fiscalYear"], Literal(int(block.fiscal_year))))
        # roleはExpenditure側と同じverbatim・plain(lang無し)。空なら書かない
        if block.role:
            data.add((s, ns["budget"]["role"], Literal(block.role)))
        # 支出先の数・金額は5-2にしか現れないブロック(実測1,357件)ではNone。
        # **0は有効な値**なので`is not None`で判定する(budgetAmountと同じ判断)
        if block.payee_count is not None:
            data.add((s, ns["budget"]["payeeCount"], Literal(block.payee_count)))
        if block.amount is not None:
            data.add((s, ns["core"]["amount_jpy"], Literal(block.amount)))
        # **偽のときも必ず書く。** 「国が払っていない」ことは欠損ではなく情報
        # であり(借入金・回収金のブロックがまさにそれ)、トリプルを省略すると
        # 「調べていない」と区別できなくなる。入口の合計を出すクエリは
        # `paidByGovernment true`で絞るので、偽の値自体は集計を汚さない
        data.add((s, ns["budget"]["paidByGovernment"], Literal(block.paid_by_government)))
        # 出どころは同じ事業内の別ブロック。`build_projects`が「実在する
        # ブロック番号だけ」を保証しているのでそのままURIにできる
        # (rs.ExpenditureBlockRecord の docstring)
        for source_block_id in block.funded_by:
            data.add(
                (
                    s,
                    ns["budget"]["fundedBy"],
                    URIRef(
                        expenditure_block_uri(
                            block.fiscal_year, block.project_id, source_block_id
                        )
                    ),
                )
            )
        # flowNoteもroleと同じverbatim・plain(budget.yaml参照)。重複除去は
        # parse側で済んでいる
        for note in block.flow_notes:
            data.add((s, ns["budget"]["flowNote"], Literal(note)))

    # =========================================================================
    # 裁定B99: 年度ごとの予算と執行。BudgetProjectの`budgetAmount`だけでは
    # 「増えた・減った」に答えられず、執行額を比べるべき分母(歳出予算現額)も
    # 無い(schema/budget.yaml の AnnualBudget 参照)
    # =========================================================================
    for annual in annual_budgets:
        s = URIRef(
            annual_budget_uri(
                annual.fiscal_year, annual.project_id, annual.budget_fiscal_year
            )
        )
        data.add((s, RDF.type, ns["budget"]["AnnualBudget"]))
        data.add(
            (
                s,
                ns["budget"]["project"],
                URIRef(budget_uri(annual.fiscal_year, annual.project_id)),
            )
        )
        data.add((s, ns["budget"]["fiscalYear"], Literal(int(annual.fiscal_year))))
        data.add(
            (s, ns["budget"]["budgetFiscalYear"], Literal(int(annual.budget_fiscal_year)))
        )
        # **`skos:prefLabel`は付けない。** この記録に固有の名前は一次データに
        # 無い(`ExpenditureBlock`はブロック名を持つが、こちらは持たない)。
        # 「2025年度 ○○事業」のような文字列を合成すると、出典の無い事実を
        # KGに入れることになる(原則7)。表示は事業名と予算年度から作る
        #
        # **`core:amount_jpy`も付けない。** 名前の付いた金額が8つあるので、
        # そのうち1つを汎用スロットに載せると`SUM(?amount_jpy)`の意味が
        # また変わる(schema/budget.yaml の AnnualBudget docstring)
        #
        # **値がある分だけ書く。0は有効な値**なので`is not None`で判定する
        # (`budgetAmount`と同じ判断。実測: レビューシート年度2025の執行額は
        # 5,794事業すべて0 —— 欠損ではなく「まだ執行されていない」)。
        # 欠損を0として書くと、その区別がグラフ上から消える
        # 一次データの`nextYearRequest`は小数表記(`'45013000.0'`)だが、
        # ここに来る時点で`normalize_amount`がintにしている。
        # **`Literal(float)`を書くとSHACLの`sh:datatype xsd:integer`に違反する。**
        for predicate, value in zip(
            ANNUAL_BUDGET_AMOUNT_PREDICATES,
            (
                annual.initial_budget,
                annual.supplementary_budget,
                annual.carried_over_from_previous_year,
                annual.reserve_fund,
                annual.total_budget_available,
                annual.executed_amount,
                annual.carried_over_to_next_year,
                annual.next_year_request,
            ),
            strict=True,
        ):
            if value is not None:
                data.add((s, ns["budget"][predicate], Literal(value)))

    for cost in indirect_costs:
        s = URIRef(indirect_cost_uri(cost.fiscal_year, cost.project_id, cost.item))
        data.add((s, RDF.type, ns["budget"]["IndirectCost"]))
        data.add((s, SKOS.prefLabel, Literal(cost.item, lang="ja")))
        data.add((s, ns["core"]["amount_jpy"], Literal(cost.amount)))
        data.add(
            (s, ns["budget"]["project"], URIRef(budget_uri(cost.fiscal_year, cost.project_id)))
        )
        data.add((s, ns["budget"]["fiscalYear"], Literal(int(cost.fiscal_year))))

    for exp in expenditures:
        s = URIRef(expenditure_uri(exp.fiscal_year, exp.project_id, exp.seq))
        data.add((s, RDF.type, ns["budget"]["Expenditure"]))
        # 支出先の表示名(束ね行なら「その他」等)は解決状態に関わらず常に持つ
        # (core:label。RDF上の実際の述語はskos:prefLabel — core.yamlの
        # `label`スロットが `slot_uri: skos:prefLabel` で対応付けている。
        # `ns["core"]["label"]` という独自述語を書くと閉じたシェイプに
        # 存在しない述語になり違反する。budget.yamlのExpenditureのdocstring
        # 参照。専用のrecipientLabelスロットは追加しない)
        data.add((s, SKOS.prefLabel, Literal(exp.label, lang="ja")))
        data.add((s, ns["core"]["amount_jpy"], Literal(exp.amount)))
        data.add((s, ns["budget"]["project"], URIRef(budget_uri(exp.fiscal_year, exp.project_id))))
        data.add((s, ns["budget"]["fiscalYear"], Literal(int(exp.fiscal_year))))
        if exp.recipient_houjin_bangou is not None:
            data.add((s, ns["budget"]["recipient"], URIRef(org_uri(exp.recipient_houjin_bangou))))
        # D-2裁定: build_projects自身の判定(resolve_recipient)をそのまま書く。
        # 4分類のいずれか1つを必ず持つ(ExpenditureRecord.recipient_match_category
        # に既定値が無いのと同じ理由でここも無条件に書く。SHACL側もrequiredで
        # 固定している — schema/budget.yaml参照)
        data.add(
            (s, ns["budget"]["recipientMatchCategory"], Literal(exp.recipient_match_category))
        )
        # センチネル法人番号の行(B18)・実在しない法人番号の行(Ruling B27)
        # だけがpayeeLabelを持つ。recipientが無い他の行(束ね・未解決)と
        # 区別するため`is not None`で判定する(空文字を欠損と混同しないと
        # いう§8.2と同じ判定形)
        if exp.payee_label is not None:
            data.add((s, ns["budget"]["payeeLabel"], Literal(exp.payee_label, lang="ja")))
        # role(B20)はverbatim・plain(LangStringではない。budget.yaml参照)なので
        # lang タグを付けない。空文字(役割が記録されていないブロック)は
        # 書かない(§8.2「欠損を空文字列で表現しない」と同じ判断)
        if exp.role:
            data.add((s, ns["budget"]["role"], Literal(exp.role)))
        # 裁定B97: どの段に属する支出か。`build_projects`が同じ事業の
        # `blocks`に実在するブロック番号だけを入れている(無ければNoneにして
        # `BuildStats.expenditures_block_unknown`に数えている)ので、ここで
        # 存在確認をやり直さない — 参照整合ゲート(裁定B4)が検査する述語なので、
        # 判定を2箇所に分けると片方だけ直した時に黙って壊れる
        if exp.block_id is not None:
            data.add(
                (
                    s,
                    ns["budget"]["inBlock"],
                    URIRef(
                        expenditure_block_uri(exp.fiscal_year, exp.project_id, exp.block_id)
                    ),
                )
            )

        for u in unresolved_for_expenditure.get((exp.fiscal_year, exp.project_id, exp.seq), []):
            node = URIRef(unresolved_recipient_uri(u.fiscal_year, u.project_id, u.seq, u.key))
            data.add((node, RDF.type, ns["core"]["UnresolvedReference"]))
            data.add((node, ns["core"]["unresolved_text"], Literal(u.key, lang="ja")))
            data.add((node, ns["core"]["unresolved_reason"], Literal(u.reason)))
            data.add((node, ns["core"]["unresolved_key"], Literal(u.key)))
            data.add((node, ns["core"]["unresolvedFor"], s))

    return ds


def write_nquads(ds: Dataset, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.serialize(destination=str(path), format="nquads", encoding="utf-8")
