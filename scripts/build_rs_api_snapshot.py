"""RSシステム公開APIの取得済み予算事業一覧からRDF成果物を作る。

この一覧APIはCSV15グループの代替ではない。ここでは全公開事業と、API一覧が
明示する年度別当初予算・直前年度執行額だけを既存のJGKG予算語彙で出力する。
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

from rdflib import RDF

from jgkg.config import get_settings
from jgkg.rdf.emit import emit_budget
from jgkg.transform.rs import AnnualBudgetRecord, BudgetProjectRecord
from jgkg.validate import validate_dataset

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = ROOT / "data/lake/rs-system-api/2026-10-04"
DEFAULT_OUTPUT = ROOT / "data/artifact/2026-10-04-rs-api-project-budget"
SOURCE_ID = "rs-system-api"
SHEET_YEAR = 2026


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_rows(snapshot_dir: Path) -> tuple[list[dict], dict]:
    manifest_path = snapshot_dir / "snapshot-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("source_url") != "https://rssystem.go.jp/api/projects/":
        raise ValueError("snapshot source_url がRSシステム予算事業一覧APIと一致しない")
    if manifest.get("query") != {"fiscal_year": SHEET_YEAR, "page_size": 1000}:
        raise ValueError("snapshot query が2026年度のページ取得条件と一致しない")

    rows: list[dict] = []
    page_entries = manifest.get("pages", [])
    if not page_entries:
        raise ValueError("snapshot manifestに取得ページが無い")
    for entry in page_entries:
        path = snapshot_dir / entry["file"]
        if _sha256(path) != entry["sha256"]:
            raise ValueError(f"取得ページのsha256不一致: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        if len(payload.get("results", [])) != entry["rows"]:
            raise ValueError(f"ページ件数がmanifestと不一致: {path}")
        rows.extend(payload["results"])

    if len(rows) != manifest.get("records_reported"):
        raise ValueError(
            f"取得件数がAPI countと不一致: {len(rows)} != "
            f"{manifest.get('records_reported')}"
        )
    if any(row.get("fiscal_year") != SHEET_YEAR for row in rows):
        raise ValueError("2026年度以外の行が混在している")
    if any(row.get("is_published") is not True for row in rows):
        raise ValueError("非公開の事業行が含まれている")
    if len({row.get("id") for row in rows}) != len(rows):
        raise ValueError("API project UUIDが重複している")
    return rows, manifest


def records_from_rows(rows: list[dict]) -> tuple[list[BudgetProjectRecord], list[AnnualBudgetRecord], dict]:
    projects: list[BudgetProjectRecord] = []
    annual: list[AnnualBudgetRecord] = []
    projects_by_year: Counter[str] = Counter()
    initial_sums: Counter[str] = Counter()
    execution_2025_sum = 0
    project_ids: set[str] = set()

    for row in rows:
        raw_project_number = str(row.get("project_number") or "")
        if not raw_project_number.isascii() or not raw_project_number.isdigit():
            raise ValueError(f"ASCII数字以外のproject_number: {raw_project_number!r}")
        project_id = str(int(raw_project_number))
        if project_id in project_ids:
            raise ValueError(f"0埋め正規化後のproject_numberが重複: {project_id}")
        project_ids.add(project_id)

        budgets = row.get("budget_data") or []
        by_year: dict[str, dict] = {}
        for item in budgets:
            year = str(item["fiscal_year"])
            if year in by_year:
                raise ValueError(f"事業{project_id}の予算年度が重複: {year}")
            by_year[year] = item

        current_initial = by_year.get(str(SHEET_YEAR), {}).get(
            "initial_budgets_total_amount"
        )
        listed_current_initial = row.get("finalized_amount_for_initial_budget")
        if (
            current_initial is not None
            and listed_current_initial is not None
            and int(current_initial) != int(listed_current_initial)
        ):
            raise ValueError(
                f"事業{project_id}の2026当初予算が一覧と履歴で不一致: "
                f"{current_initial} != {listed_current_initial}"
            )
        if current_initial is None:
            current_initial = listed_current_initial

        projects.append(
            BudgetProjectRecord(
                project_id=project_id,
                fiscal_year=str(SHEET_YEAR),
                project_name=str(row.get("name") or ""),
                ministry_houjin_bangou=None,
                budget_amount=(int(current_initial) if current_initial is not None else None),
                basis_law_ids=(),
            )
        )

        previous_execution = row.get("previous_year_execution_amount")
        if previous_execution is not None:
            execution_2025_sum += int(previous_execution)

        for year, item in by_year.items():
            initial = item.get("initial_budgets_total_amount")
            initial = int(initial) if initial is not None else None
            executed = (
                int(previous_execution)
                if year == str(SHEET_YEAR - 1) and previous_execution is not None
                else None
            )
            annual.append(
                AnnualBudgetRecord(
                    project_id=project_id,
                    fiscal_year=str(SHEET_YEAR),
                    budget_fiscal_year=year,
                    initial_budget=initial,
                    supplementary_budget=None,
                    carried_over_from_previous_year=None,
                    reserve_fund=None,
                    total_budget_available=None,
                    executed_amount=executed,
                    carried_over_to_next_year=None,
                    next_year_request=None,
                )
            )
            projects_by_year[year] += 1
            if initial is not None:
                initial_sums[year] += initial

        if str(SHEET_YEAR - 1) not in by_year and previous_execution is not None:
            annual.append(
                AnnualBudgetRecord(
                    project_id=project_id,
                    fiscal_year=str(SHEET_YEAR),
                    budget_fiscal_year=str(SHEET_YEAR - 1),
                    initial_budget=None,
                    supplementary_budget=None,
                    carried_over_from_previous_year=None,
                    reserve_fund=None,
                    total_budget_available=None,
                    executed_amount=int(previous_execution),
                    carried_over_to_next_year=None,
                    next_year_request=None,
                )
            )

    stats = {
        "project_count": len(projects),
        "annual_budget_count": len(annual),
        "annual_budget_projects_by_year": dict(sorted(projects_by_year.items())),
        "initial_budget_sum_jpy_by_year": dict(sorted(initial_sums.items())),
        "projects_with_previous_year_execution": sum(
            row.get("previous_year_execution_amount") is not None for row in rows
        ),
        "previous_year_execution_sum_jpy": execution_2025_sum,
    }
    return projects, annual, stats


def build(snapshot_dir: Path, output_dir: Path) -> dict:
    rows, snapshot_manifest = load_rows(snapshot_dir)
    projects, annual, stats = records_from_rows(rows)
    source_hashes = [entry["sha256"] for entry in snapshot_manifest["pages"]]
    fetched_on = datetime.date.fromisoformat(snapshot_manifest["fetched_on"])
    dataset = emit_budget(
        projects=projects,
        expenditures=(),
        unresolved=(),
        source_id=SOURCE_ID,
        fetched_on=fetched_on,
        sha256=source_hashes,
        annual_budgets=annual,
    )
    validations = validate_dataset(dataset, ROOT / "schema/generated")
    failures = [result for result in validations if not result.conforms]
    if failures:
        raise RuntimeError("SHACL検証不合格: " + " / ".join(x.report_text for x in failures))

    data_graph_uri = (
        f"{get_settings().base_uri}/graph/{SOURCE_ID}/{fetched_on.isoformat()}"
    )
    data_graph = dataset.graph(data_graph_uri)
    type_counts = Counter(str(obj).rsplit("#", 1)[-1] for obj in data_graph.objects(None, RDF.type))
    quads = dataset.serialize(format="nquads", encoding="utf-8")
    if isinstance(quads, str):
        quads = quads.encode("utf-8")
    nquads = b"\n".join(sorted(line for line in quads.splitlines() if line.strip())) + b"\n"

    output_dir.mkdir(parents=True, exist_ok=True)
    nq_path = output_dir / "kg.nq"
    nq_path.write_bytes(nquads)
    compressed_path = output_dir / "kg.nq.gz"
    with compressed_path.open("wb") as raw_file:
        with gzip.GzipFile(fileobj=raw_file, mode="wb", mtime=0) as compressed:
            compressed.write(nquads)

    manifest = {
        "release": output_dir.name,
        "created_on": datetime.date.today().isoformat(),
        "source": SOURCE_ID,
        "source_url": "https://rssystem.go.jp/api/projects/",
        "query": snapshot_manifest["query"],
        "fetched_on": fetched_on.isoformat(),
        "source_pages": snapshot_manifest["pages"],
        "source_records_reported": snapshot_manifest["records_reported"],
        "source_records_saved": snapshot_manifest["records_saved"],
        "data_graph": data_graph_uri,
        "graph_type_counts": dict(sorted(type_counts.items())),
        "triple_count": len(nquads.splitlines()),
        "kg_nq_sha256": hashlib.sha256(nquads).hexdigest(),
        "kg_nq_gz_sha256": _sha256(compressed_path),
        "kg_nq_gz_bytes": compressed_path.stat().st_size,
        "record_counts": stats,
        "included": [
            "全6,423件の公開された2026年度予算事業一覧レコード",
            "一覧APIのbudget_dataが提供する各年度の当初予算額",
            "2026年度レビューシートが提供する前年度(2025年度)執行額",
        ],
        "limitations": [
            "一覧APIの応答だけを変換。15グループの詳細CSVは含まない",
            "支出先の全行・ブロック接続・法令・施策・点検評価等は含まない",
            "一覧APIにある府省名は既存KGの法人番号付き組織へ照合していない",
            "過年度予算はAPI一覧が返す当初予算額のみ。補正・繰越・予算現額等は含まない",
        ],
        "shacl_conforms": True,
        "shacl_graphs_checked": len(validations),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(json.dumps(build(args.snapshot_dir, args.out_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
