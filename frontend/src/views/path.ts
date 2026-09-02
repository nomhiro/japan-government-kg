// パス探索(仕様§9.2「近傍サブグラフ展開 → パス探索」)。
import type { GraphEdge, PathResponse, SearchHit } from "../api/client";
import { findPath, search } from "../api/client";
import { PATH_FANOUT_LIMIT, PATH_MAX_DEPTH, PATH_VISIT_BUDGET } from "../api/limits";
import { esc, provenanceHtml } from "../format";
import { predicateLabel, typeLabel } from "../labels";
import { navigate } from "../router";

const DEBOUNCE_MS = 300;

/** 検索ボックス+候補一覧の小さな部品(検索ビューと同じデバウンス方針)。 */
function mountPicker(
  root: HTMLElement,
  initialIdPath: string | undefined,
  onPick: (hit: { id_path: string; label: string | null }) => void,
): void {
  root.innerHTML = `
    <input type="search" class="jgkg-picker-box" placeholder="エンティティ名で検索">
    <div class="jgkg-picker-results"></div>
    <p class="jgkg-picker-selected jgkg-muted"></p>
  `;
  const input = root.querySelector<HTMLInputElement>(".jgkg-picker-box")!;
  const results = root.querySelector<HTMLElement>(".jgkg-picker-results")!;
  const selected = root.querySelector<HTMLElement>(".jgkg-picker-selected")!;

  if (initialIdPath) {
    selected.textContent = `選択中: ${initialIdPath}`;
  }

  let timer: ReturnType<typeof setTimeout> | undefined;
  input.addEventListener("input", () => {
    if (timer) clearTimeout(timer);
    const q = input.value;
    timer = setTimeout(() => void run(q), DEBOUNCE_MS);
  });

  async function run(q: string): Promise<void> {
    if (!q.trim()) {
      results.innerHTML = "";
      return;
    }
    try {
      const res = await search(q, 10);
      results.innerHTML = res.results
        .map(
          (hit: SearchHit) => `
          <li class="jgkg-picker-hit" data-id-path="${esc(hit.id_path)}" data-label="${esc(hit.label ?? "")}">
            <span class="jgkg-type-badge">${esc(typeLabel(hit.type))}</span> ${esc(hit.label ?? "(表示名なし)")}
          </li>`,
        )
        .join("");
      results.querySelectorAll<HTMLElement>(".jgkg-picker-hit").forEach((el) => {
        el.addEventListener("click", () => {
          const idPath = el.dataset.idPath!;
          const label = el.dataset.label || null;
          selected.textContent = `選択中: ${label ?? idPath}`;
          results.innerHTML = "";
          input.value = "";
          onPick({ id_path: idPath, label });
        });
      });
    } catch {
      results.innerHTML = '<p class="jgkg-error">検索に失敗しました。</p>';
    }
  }
}

function edgeRow(edge: GraphEdge, graphs: PathResponse["graphs"]): string {
  return `<li><span class="jgkg-rel-predicate">${esc(predicateLabel(edge.predicate))}</span> ${provenanceHtml(graphs[edge.graph])}</li>`;
}

function reasonText(res: PathResponse): string {
  const reasons: string[] = [];
  if (res.budget_exhausted) reasons.push(`訪問予算(${res.visit_budget}件)を使い切りました`);
  if (res.depth_limited) reasons.push(`探索の深さ上限(${res.max_depth})に達しました`);
  if (res.fanout_truncated) reasons.push("分岐数の上限で一部の経路を切り落としました");
  return reasons.join("・");
}

function renderResult(container: HTMLElement, res: PathResponse): void {
  if (res.found) {
    const nodeNames = res.nodes.map((n) => n.label ?? typeLabel(n.type)).join(" → ");
    container.innerHTML = `
      <p class="jgkg-path-found">経路が見つかりました(${res.nodes.length}ノード・訪問${res.visited}件・深さ${res.searched_depth})</p>
      <p>${esc(nodeNames)}</p>
      <ul class="jgkg-rel-list">${res.edges.map((e) => edgeRow(e, res.graphs)).join("")}</ul>
      ${res.undirected ? '<p class="jgkg-muted">辺の向きを無視して探索した経路を含みます。</p>' : ""}
    `;
    return;
  }

  // **found=falseの読み方(裁定B77の族)。** exhaustive=trueのときだけ
  // 「経路は存在しない」と言ってよい。それ以外は「この深さ・この予算では
  // 見つからなかった」であり、「無い」と混同してはならない。
  if (res.exhaustive) {
    container.innerHTML = `
      <p class="jgkg-path-not-found">
        経路は存在しません(深さ${res.max_depth}以内・予算${res.visit_budget}訪問まで探索を尽くしました)。
      </p>`;
    return;
  }
  const reason = reasonText(res);
  container.innerHTML = `
    <p class="jgkg-path-inconclusive">
      見つかりませんでした(この深さ・この予算では見つかりませんでした。「存在しない」とは言えません)。
    </p>
    ${reason ? `<p class="jgkg-muted">${esc(reason)}</p>` : ""}`;
}

export function renderPath(container: HTMLElement, initialFrom?: string, initialTo?: string): void {
  container.innerHTML = `
    <p><a href="#/">&larr; 検索に戻る</a></p>
    <h1>経路を探す</h1>
    <p class="jgkg-lead">2つのエンティティ間のつながりを探します(例: 法令↔法人)。</p>
    <div class="jgkg-path-form">
      <div class="jgkg-path-from"><h3>始点</h3></div>
      <div class="jgkg-path-to"><h3>終点</h3></div>
    </div>
    <p><button type="button" class="jgkg-path-submit" disabled>探す</button></p>
    <div class="jgkg-path-result"></div>
  `;

  let from = initialFrom;
  let to = initialTo;
  const submit = container.querySelector<HTMLButtonElement>(".jgkg-path-submit")!;
  const result = container.querySelector<HTMLElement>(".jgkg-path-result")!;

  function refreshSubmit(): void {
    submit.disabled = !from || !to;
  }

  mountPicker(container.querySelector<HTMLElement>(".jgkg-path-from")!, initialFrom, (hit) => {
    from = hit.id_path;
    refreshSubmit();
  });
  mountPicker(container.querySelector<HTMLElement>(".jgkg-path-to")!, initialTo, (hit) => {
    to = hit.id_path;
    refreshSubmit();
  });
  refreshSubmit();

  submit.addEventListener("click", () => {
    if (!from || !to) return;
    navigate({ name: "path", from, to });
    void run(from, to);
  });

  async function run(f: string, t: string): Promise<void> {
    result.innerHTML = '<p class="jgkg-muted">探索中…</p>';
    try {
      const res = await findPath(f, t, {
        max_depth: PATH_MAX_DEPTH.default,
        visit_budget: PATH_VISIT_BUDGET.default,
        fanout_limit: PATH_FANOUT_LIMIT.default,
      });
      if (!res) {
        result.innerHTML = '<p class="jgkg-error">始点または終点のエンティティが見つかりませんでした。</p>';
        return;
      }
      renderResult(result, res);
    } catch (e) {
      result.innerHTML = `<p class="jgkg-error">探索に失敗しました: ${esc(String(e))}</p>`;
    }
  }

  if (initialFrom && initialTo) void run(initialFrom, initialTo);
}
