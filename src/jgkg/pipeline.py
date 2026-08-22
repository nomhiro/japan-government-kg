"""パイプラインの結線。取得済みスナップショットからN-Quadsまでを1本にする。

各段の件数を PipelineReport として返す。観測性は設計書§11.1の要件。
"""
import datetime
from pathlib import Path

from pydantic import BaseModel
from rdflib import Dataset

from jgkg import lake, validate
from jgkg.config import get_settings
from jgkg.connectors import houjin_bangou
from jgkg.rdf import emit
from jgkg.transform import ministry as ministry_mod
from jgkg.transform import organization as org_mod

MINISTRY_REFERENCE = Path("data/reference/ministry-codes.csv")
SHAPES_DIR = Path("schema/generated")


class PipelineReport(BaseModel):
    release: str
    # 入力スナップショットから解析した全件数。スナップショット破損や欠落の検知に使う
    organizations: int
    # そのうちKGに入れた件数(国の機関のみ)。organizations との差が
    # 「絞り込みで除外された数」になる。両方を出さないと、レポートを読んだ人が
    # 「解析した件数がKGに入っている」と誤解する
    government_organs: int
    ministries: int
    unmatched_ministries: int
    graphs_validated: int
    graphs_quarantined: int
    # 検証を通ったグラフのURI一覧。manifest に渡すため正確な値をここで持つ
    # (N-Quadsのテキストから推測すると、リテラルに含まれる `>` や3項行の
    #  オブジェクトIRIを誤認する。実測で確認済み)
    graphs: list[str]


def _merge(target: Dataset, source: Dataset) -> None:
    for ctx in source.contexts():
        if len(ctx) == 0:
            continue
        g = target.graph(ctx.identifier)
        for triple in ctx:
            g.add(triple)


def run(fetched_on: datetime.date, out_dir: Path) -> PipelineReport:
    settings = get_settings()

    # ファイルパスを渡してストリームで解析する。bytes で読むと実データ(約1GB)で
    # メモリが破綻する(§Task 6 の説明を参照)
    snapshot_path = lake.path_of("houjin-bangou", fetched_on, houjin_bangou.FILENAME)
    if not snapshot_path.exists():
        raise FileNotFoundError(
            f"スナップショットが無い: {snapshot_path}。先にコネクタで取得する"
        )
    # **1パスで「全件数」と「国の機関のみのリスト」を分離する。**
    # 全法人(約500万件)を list() すると pydantic オブジェクトで数GB、さらに emit が
    # rdflib に 3000万トリプルを載せるため破綻する。Phase 0 の目的は基盤の確立であり、
    # 任意の法人が必要になるのは Phase 1 の縦スライス(支出先法人)。設計書§6.2.3の
    # 「規模の問題は分割で対処し、1つを大きくするな」に従う。
    # 全件数も数えるのは、スナップショット破損や欠落を検知するため(§11.1の観測性)
    total_organizations = 0
    orgs: list[org_mod.Organization] = []
    for o in org_mod.parse_file(snapshot_path):
        total_organizations += 1
        if o.is_government_organ:
            orgs.append(o)

    reference = ministry_mod.load_reference(MINISTRY_REFERENCE)
    ministries, unmatched = ministry_mod.build(orgs, reference)

    ds = Dataset(default_union=True)
    _merge(ds, emit.emit_organizations(orgs, "houjin-bangou", fetched_on))
    _merge(ds, emit.emit_ministries(ministries, unmatched, "ministry-codes", fetched_on))

    results = validate.validate_dataset(ds, SHAPES_DIR)
    quarantined = [r for r in results if not r.conforms]
    if quarantined:
        validate.quarantine(ds, results, Path(settings.quarantine_dir))

    clean = validate.passing_dataset(ds, results)
    out_dir.mkdir(parents=True, exist_ok=True)
    emit.write_nquads(clean, out_dir / "kg.nq")

    return PipelineReport(
        release=fetched_on.isoformat(),
        organizations=total_organizations,
        government_organs=len(orgs),
        ministries=len(ministries),
        unmatched_ministries=len(unmatched),
        graphs_validated=len(results),
        graphs_quarantined=len(quarantined),
        # Dataset から正確なグラフURIを取る。テキストから推測してはならない
        graphs=sorted(str(c.identifier) for c in clean.contexts() if len(c) > 0),
    )
