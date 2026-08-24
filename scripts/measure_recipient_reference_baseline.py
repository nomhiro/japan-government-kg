"""Task 10 R2宿題: budget:recipient の参照整合違反の確定値を実データで測る。

task-7-review.md 指摘R2: 実装者の一回性スクリプトは違反54,909件、team-leadの
独立再計算は54,828件(81件差)と報告し、どちらもコミットされていないため
原因を特定できないまま「Task 10の結線後のコミットされた実行で確定させる」と
申し送られていた(裁定B25: 測定は使い捨てスクリプト禁止。scripts/にコミットし、
出力もdocsに全量転記する)。

このスクリプトは以下を実データ(2026-08-23取得のレイクスナップショット。
houjin-bangou全件データ 5,816,535行 + rs-system 5本)から**決定的に**再計算する:

1. 国の機関(法人種別=101)の法人番号集合(848件のはず) — フラグOFF時に
   pipeline.pyがOrganization型を実際にemitする範囲そのもの
2. rs-systemの支出(payee_payment_information)を`rs.build_projects`
   (name_index={}。B14の判断そのまま)で解決し、法人番号直結で解決された
   件数(=examined。budget:recipientが実際に検査対象になる件数)
3. 2のうち、1の集合に実在する件数(=型を持つ。参照整合ゲートを通る件数)
4. examined - 型を持つ = 参照整合ゲートの違反件数(確定値)

使い方:
    uv run python scripts/measure_recipient_reference_baseline.py

前提: data/lake/houjin-bangou/2026-08-23/ と data/lake/rs-system/2026-08-23/
に実データが存在すること(このリポジトリには既に存在する)。
"""
import datetime
from pathlib import Path

from jgkg import lake
from jgkg.connectors import houjin_bangou
from jgkg.transform import ministry as ministry_mod
from jgkg.transform import organization as org_mod
from jgkg.transform import rs as rs_mod

HOUJIN_DATE = datetime.date(2026, 8, 23)
RS_DATE = datetime.date(2026, 8, 23)
MINISTRY_REFERENCE = Path("data/reference/ministry-codes.csv")

REQUIRED_RS_GROUPS = rs_mod.REQUIRED_GROUPS


def _government_organs() -> tuple[list[org_mod.Organization], int]:
    """848件のはずの国の機関のOrganizationオブジェクト一覧。全件

    (5,816,535行)を1パスだけ流す(848件規模なのでリストで保持しても
    メモリは問題にならない。R19の禁止対象は全法人5.8M件の保持であって、
    国の機関848件はフラグOFF時のpipeline.pyが常時保持している規模と同じ)。
    フラグOFF時のpipeline.pyがOrganization型を実際にemitする範囲と完全に
    一致する(orgs = [o for o in parse_source(...) if o.is_government_organ])。
    """
    snapshot_path = lake.path_of("houjin-bangou", HOUJIN_DATE, houjin_bangou.FILENAME)
    if not snapshot_path.exists():
        raise FileNotFoundError(
            f"houjin-bangouの実データが無い: {snapshot_path}。"
            " このスクリプトは実データでの確定値を出すためのものであり、"
            " fixtureでは代用できない"
        )
    total = 0
    gov_organs: list[org_mod.Organization] = []
    for o in org_mod.parse_source(snapshot_path):
        total += 1
        if o.is_government_organ:
            gov_organs.append(o)
    return gov_organs, total


def _rs_group_paths() -> dict[str, Path]:
    snapshots = {s.path.name: s.path for s in lake.list_snapshots("rs-system") if s.fetched_on == RS_DATE}
    from jgkg.connectors import rs_system

    paths: dict[str, Path] = {}
    for group in REQUIRED_RS_GROUPS:
        filename = rs_system.filename_for(group, 2025)
        if filename not in snapshots:
            raise FileNotFoundError(
                f"rs-systemの実データにグループ{group!r}のファイルが無い: {filename}。"
                f" 検出したファイル: {sorted(snapshots)}"
            )
        paths[group] = snapshots[filename]
    return paths


def main() -> None:
    print("=== Task 10 R2宿題: budget:recipient 参照整合違反の確定値 ===")
    print(f"houjin-bangou実データ取得日: {HOUJIN_DATE.isoformat()}")
    print(f"rs-system実データ取得日: {RS_DATE.isoformat()}")
    print()

    gov_organ_objects, total_organizations = _government_organs()
    gov_organs = {o.houjin_bangou for o in gov_organ_objects}
    print(f"houjin-bangou全件データ 非空行数: {total_organizations:,}")
    print(f"国の機関(法人種別101)の法人番号: distinct {len(gov_organs):,} 件")
    print()

    reference = ministry_mod.load_reference(MINISTRY_REFERENCE)
    ministries, unmatched = ministry_mod.build(gov_organ_objects, reference)
    print(f"府省参照表: {len(reference)}行 -> 突合 {len(ministries)} / 未突合 {len(unmatched)}")
    ministry_ref = {}
    for m in ministries:
        ministry_ref.setdefault(m.name, []).append(m)
    print()

    rs_paths = _rs_group_paths()
    rs_stats = rs_mod.RsParseStats()
    rows = list(rs_mod.parse_rs(rs_paths, stats=rs_stats))
    # B14: 名称正規化による支出先解決(name_index)は導入しない
    # (実データで解決0件と確定済み。pipeline.pyのrs-system結線と同じ判断)
    result = rs_mod.build_projects(rows, ministry_ref, laws_by_id={}, laws_by_title={}, name_index={})
    stats = result.stats

    print("=== rs.build_projects の実測(BuildStats) ===")
    print(f"projects_seen: {stats.projects_seen:,}")
    print(f"expenditures_seen: {stats.expenditures_seen:,}")
    print(f"expenditures_bundled: {stats.expenditures_bundled:,}")
    print(f"recipients_sentinel: {stats.recipients_sentinel:,}")
    print(f"recipients_resolved_by_houjin_bangou: {stats.recipients_resolved_by_houjin_bangou:,}")
    print(f"recipients_resolved_by_name: {stats.recipients_resolved_by_name:,}")
    print(f"recipients_unresolved: {stats.recipients_unresolved:,}")
    identity = (
        stats.expenditures_bundled
        + stats.recipients_sentinel
        + stats.recipients_resolved_by_houjin_bangou
        + stats.recipients_resolved_by_name
        + stats.recipients_unresolved
    )
    print(
        f"恒等式確認: 束ね+センチネル+直結+名称+未解決 = {identity:,} "
        f"(expenditures_seenと一致すべき: {'OK' if identity == stats.expenditures_seen else 'NG'})"
    )
    print()

    examined_pairs: set[tuple[str, str, int]] = set()
    examined = 0
    matched = 0
    for exp in result.expenditures:
        if exp.recipient_houjin_bangou is None:
            continue
        examined += 1
        key = (exp.project_id, exp.fiscal_year, exp.seq)
        examined_pairs.add(key)
        if exp.recipient_houjin_bangou in gov_organs:
            matched += 1
    violations = examined - matched

    print("=== budget:recipient 参照整合ゲート(確定値) ===")
    print(f"検査対象(examined。recipient_houjin_bangouがNoneでない件数): {examined:,}")
    # Task 10修正ラウンド1(観察5): 「ゲートの重複排除後の件数と一致するか」の
    # 確認として構築したが今まで印字していなかった(task-10-review.md観察5)。
    # ゲート(check_reference_integrity)は(subject, object)組で重複排除するため、
    # Expenditure URIが重複しなければexamined_pairsの件数はexaminedと一致するはず
    print(
        f"うちdistinct(project_id, fiscal_year, seq)組: {len(examined_pairs):,} "
        f"(examinedと一致すべき: {'OK' if len(examined_pairs) == examined else 'NG'})"
    )
    print(f"型を持つ(848件の国の機関のいずれかに一致): {matched:,}")
    print(f"違反(examined - 型を持つ): {violations:,}")
    print()
    print("=== 過去の報告値との比較 ===")
    print("実装者の一回性スクリプト(task-7-report.md): 違反54,909件(型を持つ=1,758件相当)")
    print("team-leadの独立再計算(task-7-review.md): 違反54,828件(型を持つ=1,839件相当)")
    print(f"このスクリプトの確定値: 違反{violations:,}件(型を持つ={matched:,}件)")
    if violations == 54909:
        print("-> 実装者の値(54,909)と一致した")
    elif violations == 54828:
        print("-> team-leadの値(54,828)と一致した")
    else:
        print(f"-> どちらとも一致しない(差: 実装者比{violations - 54909:+,} / team-lead比{violations - 54828:+,})")


if __name__ == "__main__":
    main()
