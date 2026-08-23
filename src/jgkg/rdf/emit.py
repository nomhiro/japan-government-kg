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
from jgkg.transform.organization import Organization
from jgkg.transform.rs import BudgetProjectRecord, ExpenditureRecord, UnresolvedBudgetReference
from jgkg.uris import (
    budget_uri,
    expenditure_uri,
    graph_uri,
    law_uri,
    law_version_uri,
    org_uri,
    unresolved_basis_law_uri,
    unresolved_budget_ministry_uri,
    unresolved_jurisdiction_uri,
    unresolved_ministry_uri,
    unresolved_recipient_uri,
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
) -> Dataset:
    """`rs.build_projects` の出力を `budget:BudgetProject` / `budget:Expenditure`

    として書く(Task 7 brief Step 5)。`emit_laws`/`emit_organizations` と同じ、
    変換とemitの分離(emit自身は解決ロジックを持たない)。

    `sha256` は複数件を受ける(RSは1つのグラフが project_summary/budget_summary/
    policy_measure_laws_and_regulations/payee_payment_information の4本の
    物理ファイルから作られるため。`provenance_graph` の複数件対応を実際に使う
    唯一の呼び出し元)。

    `unresolved` は3種類が混在する(`UnresolvedBudgetReference.kind`)。
    ministry/basis_law は主体がBudgetProject、recipientは主体がExpenditureで、
    それぞれ別のURI関数(`uris.unresolved_budget_ministry_uri` 等)を使う
    (law.pyのunresolved_jurisdiction_uriと同じ理由 — 同じ未解決の名称/IDを
    指す事業が複数あっても1ノードに収束させない)。
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
        # センチネル法人番号の行(B18)だけがpayeeLabelを持つ。recipientが
        # 無い他の行(束ね・未解決)と区別するため`is not None`で判定する
        # (空文字を欠損と混同しないという§8.2と同じ判定形)
        if exp.payee_label is not None:
            data.add((s, ns["budget"]["payeeLabel"], Literal(exp.payee_label, lang="ja")))
        # role(B20)はverbatim・plain(LangStringではない。budget.yaml参照)なので
        # lang タグを付けない。空文字(役割が記録されていないブロック)は
        # 書かない(§8.2「欠損を空文字列で表現しない」と同じ判断)
        if exp.role:
            data.add((s, ns["budget"]["role"], Literal(exp.role)))

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
