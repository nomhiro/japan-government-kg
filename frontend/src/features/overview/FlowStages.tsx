// トップページ再設計・第3節「資金の流れ: 実データの段」。
//
// `money_through_stages`(CQ13。20件)がこのKGで最も「グラフらしい」答え
// である——事業の中でお金が段(ExpenditureBlock)を経て流れ、**同じ額が
// 複数の段に記録されている**(裁定B97)。旧トップページはこの1件目だけを
// 文章で説明していた(`views/overview.ts`の`renderMoneyThroughStageExample`)
// ——ここでは複数事業を実際に繋がった小さな流れ図として出す。
//
// **足し算をしない(裁定B96)。** 段の金額を合計して1つの数字を作らない
// ——各段の金額は`amount`(その行が持つ値)をそのまま見せるだけで、
// このファイルには`reduce((s,r)=>s+r.amount, ...)`のような集計を書かない。
//
// **事業ページへのリンクについての注記。** `MoneyThroughStage`は事業の
// `id_path`を持たない(`project_name`は文字列のラベルのみ)——存在しない
// IDを推測して組み立てることはできない(裁定B59/B69: id_pathは常に
// APIが返した値をそのまま使う)。そのため「事業ページへ」のリンクは、
// 既存の検索(`#/search?q=…`)へのリンクにする——事業名で検索した結果へ
// 遷移する、という誠実な導線。
import type { JSX } from "react";
import type { MoneyThroughStage } from "../../api/client";
import { Amount } from "../../components/ui";
import { navigate } from "../../router";

export interface FlowNode {
  readonly id: string;
  readonly name: string;
  /** この段自身の金額。この段が「出どころ」としてしか現れない(=この
   *  事業のデータの中に、この段自身の行が無い)場合は`null`。 */
  readonly amount: number | null;
  /** この段が「国からの支払い」でもあるか。データに無ければ`null`。 */
  readonly paidByGovernment: boolean | null;
  /** 出どころから何段流れてきたか(0=出どころそのもの)。レイアウト用。 */
  readonly level: number;
}

export interface FlowLink {
  readonly fromId: string;
  readonly toId: string;
  readonly amount: number;
}

export interface ProjectFlow {
  readonly projectName: string;
  readonly nodes: readonly FlowNode[];
  readonly links: readonly FlowLink[];
}

/**
 * `rows`(CQ13)を事業ごとにグループ化し、`block_id`→`source_id`の対応を
 * 繋いで小さな流れ図の材料にする。
 *
 * **事業を手で選ばない。** 応答の並び順(`ORDER BY DESC(?amount)`)の先頭
 * から現れた事業を、現れた順に`maxProjects`件だけ使う——`money_through_stages`
 * の行の並びを信じる(既存`renderBars`等と同じ「降順を信じる」方針)。
 */
export function buildProjectFlows(
  rows: readonly MoneyThroughStage[],
  maxProjects = 4,
): ProjectFlow[] {
  const order: string[] = [];
  const byProject = new Map<string, MoneyThroughStage[]>();
  for (const row of rows) {
    let bucket = byProject.get(row.project_name);
    if (!bucket) {
      bucket = [];
      byProject.set(row.project_name, bucket);
      order.push(row.project_name);
    }
    bucket.push(row);
  }
  return order.slice(0, maxProjects).map((projectName) => buildFlow(projectName, byProject.get(projectName)!));
}

function buildFlow(projectName: string, rows: MoneyThroughStage[]): ProjectFlow {
  interface Draft {
    id: string;
    name: string;
    amount: number | null;
    paidByGovernment: boolean | null;
  }
  const drafts = new Map<string, Draft>();
  const links: FlowLink[] = [];

  for (const row of rows) {
    if (!drafts.has(row.block_id)) {
      drafts.set(row.block_id, {
        id: row.block_id,
        name: row.block_name ?? `段${row.block_id}`,
        amount: row.amount,
        paidByGovernment: row.paid_by_government,
      });
    }
    if (row.source_id) {
      if (!drafts.has(row.source_id)) {
        drafts.set(row.source_id, {
          id: row.source_id,
          name: row.source_name ?? `段${row.source_id}`,
          amount: null,
          paidByGovernment: null,
        });
      }
      links.push({ fromId: row.source_id, toId: row.block_id, amount: row.amount });
    }
  }

  // level(段) = 0(出どころを持たない)、または 1 + max(その段に流れ込む
  // 出どころのlevel)。同じ事業の中に閉路は無い前提(circular guardは
  // 無限ループの保険)。
  const levels = new Map<string, number>();
  function levelOf(id: string, guard: Set<string>): number {
    const cached = levels.get(id);
    if (cached !== undefined) return cached;
    if (guard.has(id)) return 0;
    guard.add(id);
    const incoming = links.filter((l) => l.toId === id);
    const level = incoming.length === 0 ? 0 : 1 + Math.max(...incoming.map((l) => levelOf(l.fromId, guard)));
    levels.set(id, level);
    return level;
  }
  for (const id of drafts.keys()) levelOf(id, new Set());

  const nodes: FlowNode[] = [...drafts.values()]
    .map((d) => ({ ...d, level: levels.get(d.id) ?? 0 }))
    .sort((a, b) => a.level - b.level || a.id.localeCompare(b.id));

  return { projectName, nodes, links };
}

export interface FlowStagesProps {
  rows: MoneyThroughStage[];
  sources: Record<string, string>;
}

export function FlowStages({ rows, sources }: FlowStagesProps): JSX.Element {
  const flows = buildProjectFlows(rows);
  const citation = sources.money_through_stages;

  if (flows.length === 0) {
    return <p className="jg-sm jg-muted">資金の流れのデータがありません。</p>;
  }

  return (
    <div className="jg-stack jg-stack--6">
      {flows.map((flow) => (
        <ProjectFlowDiagram key={flow.projectName} flow={flow} />
      ))}
      {citation ? <p className="jg-xs jg-muted">この事業名は検索で辿れます(事業自体の固有IDは/overviewの応答に含まれていません)。</p> : null}
    </div>
  );
}

function ProjectFlowDiagram({ flow }: { flow: ProjectFlow }): JSX.Element {
  const maxLevel = Math.max(0, ...flow.nodes.map((n) => n.level));
  const columns: FlowNode[][] = Array.from({ length: maxLevel + 1 }, () => []);
  for (const node of flow.nodes) columns[node.level]!.push(node);

  return (
    <div className="jg-flow">
      <button
        type="button"
        className="jg-flow__title"
        onClick={() => navigate({ name: "search", q: flow.projectName })}
      >
        {flow.projectName}
      </button>
      <div className="jg-flow__diagram">
        {columns.map((col, i) => (
          <div className="jg-flow__step" key={i}>
            {i > 0 ? <span className="jg-flow__arrow" aria-hidden="true">→</span> : null}
            <div className="jg-flow__col">
              {col.map((node) => (
                <div className="jg-flow__node" key={node.id}>
                  <span className="jg-flow__node-name">{node.name}</span>
                  <span className="jg-flow__node-amount jg-num">
                    {node.amount !== null ? <Amount yen={node.amount} /> : "—"}
                  </span>
                  {node.paidByGovernment ? <span className="jg-limit-tag">国が支払った段</span> : null}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
      <p className="jg-xs jg-ink2">
        矢印で繋がっている段には、同じお金が再記録されています。合計は表示していません(足すと二重計上になります)。
      </p>
    </div>
  );
}
