// エンティティページ(型別レイアウト。仕様§9.2)。
//
// **属性(attributes)には出典が付けられない(気になる点)。** D-4までのAPIは
// `attributes: dict[述語, 値の一覧]`だけを返し、どの名前付きグラフから来た
// リテラルかを保持していない(`queries.py`の`_build_attributes_query`は
// `GRAPH`句を使わない設計)。関係(relationships)・近傍サブグラフの辺には
// `graph`があるが、属性には無い——したがって属性の値については
// 「一次資料へのリンクと取得日時を出す」(仕様§9.2)を今のAPI応答からは
// 満たせない。ここでは無いものを捏造せず、その旨を明示する
// (このプロジェクトの「報告が嘘をつく」を避ける方針と同じ理由)。
import type { EntityDetailResponse, Relationship } from "../api/client";
import { apiUnavailableReason, entityDetail } from "../api/client";
import { esc, provenanceHtml, truncationNotice } from "../format";
import type { GraphController } from "./graph";
import { renderNeighborhoodGraph } from "./graph";
import { predicateLabel, typeLabel } from "../labels";
import { navigate } from "../router";

function relationshipRow(rel: Relationship, graphs: EntityDetailResponse["graphs"]): string {
  const arrow = rel.direction === "outgoing" ? "→" : "←";
  const label = rel.related.label ?? `(${esc(typeLabel(rel.related.type))}。表示名なし)`;
  return `
    <li>
      <span class="jgkg-rel-predicate">${arrow} ${esc(predicateLabel(rel.predicate))}</span>
      <a href="#" class="jgkg-rel-target" data-id-path="${esc(rel.related.id_path)}">${esc(label)}</a>
      <span class="jgkg-muted jgkg-rel-prov">${provenanceHtml(graphs[rel.graph])}</span>
    </li>`;
}

export interface EntityViewController {
  destroy(): void;
}

export function renderEntity(container: HTMLElement, idPath: string): EntityViewController {
  // 裁定B82(2)と同じ判断: APIが未配備なら、失敗するとわかっている取得を
  // 試みない(検索ビューと同じ理由)。
  const unavailable = apiUnavailableReason();
  if (unavailable) {
    container.innerHTML = `
      <p class="jgkg-notice">データ検索は準備中です。${esc(unavailable)}</p>
      <p><a href="#/">検索に戻る</a></p>`;
    return { destroy(): void {} };
  }

  container.innerHTML = '<p class="jgkg-muted">読み込み中…</p>';
  let graphController: GraphController | undefined;
  // 画面遷移で描画中に離脱した場合、後から届く応答でDOM/Sigmaを触らない
  // (別のビューのDOMに書き込む・WebGLコンテキストが残る、を防ぐ)。
  let cancelled = false;

  void (async () => {
    let entity: EntityDetailResponse | null;
    try {
      entity = await entityDetail(idPath);
    } catch (e) {
      if (cancelled) return;
      container.innerHTML = `<p class="jgkg-error">読み込みに失敗しました: ${esc(String(e))}</p>`;
      return;
    }
    if (cancelled) return;
    if (!entity) {
      container.innerHTML = `
        <p class="jgkg-error">このエンティティは見つかりませんでした。</p>
        <p><a href="#/">検索に戻る</a></p>`;
      return;
    }

    const attrRows = Object.entries(entity.attributes)
      .map(
        ([pred, values]) =>
          `<tr><th>${esc(predicateLabel(pred))}</th><td>${values.map((v) => esc(v)).join("、")}</td></tr>`,
      )
      .join("");

    const relGroups = Object.entries(entity.relationships)
      .map(
        ([typeName, rels]) => `
        <div class="jgkg-rel-group">
          <h3>${esc(typeLabel(typeName))}(${rels.length}件)</h3>
          <ul class="jgkg-rel-list">${rels.map((r) => relationshipRow(r, entity!.graphs)).join("")}</ul>
        </div>`,
      )
      .join("");

    container.innerHTML = `
      <p><a href="#/">&larr; 検索に戻る</a></p>
      <span class="jgkg-type-badge">${esc(typeLabel(entity.type))}</span>
      <h1>${esc(entity.label ?? "(表示名なし)")}</h1>

      ${attrRows ? `<table class="jgkg-attr-table">${attrRows}</table>` : ""}
      <p class="jgkg-muted jgkg-attr-note">
        属性の一次資料へのリンクはAPIからまだ提供されていません(気になる点として報告済み)。
        下の関係・近傍サブグラフの出典は表示されます。
      </p>

      <h2>関係${truncationNotice(entity.relationships_truncated, entity.relationships_limit, "関係")}</h2>
      ${relGroups || '<p class="jgkg-muted">関係はありません。</p>'}

      <p class="jgkg-secondary">
        <button type="button" class="jgkg-find-path-from">ここから経路を探す</button>
      </p>

      <h2>近傍サブグラフ</h2>
      <div class="jgkg-graph-container"></div>
    `;

    container.querySelectorAll<HTMLAnchorElement>(".jgkg-rel-target").forEach((a) => {
      a.addEventListener("click", (ev) => {
        ev.preventDefault();
        navigate({ name: "entity", idPath: a.dataset.idPath! });
      });
    });
    container.querySelector<HTMLButtonElement>(".jgkg-find-path-from")?.addEventListener("click", () => {
      navigate({ name: "path", from: idPath });
    });

    const graphContainer = container.querySelector<HTMLElement>(".jgkg-graph-container")!;
    graphController = renderNeighborhoodGraph(graphContainer, {
      id: entity.id,
      id_path: entity.id_path,
      type: entity.type,
      label: entity.label,
    });
  })();

  return {
    destroy(): void {
      cancelled = true;
      graphController?.destroy();
    },
  };
}
