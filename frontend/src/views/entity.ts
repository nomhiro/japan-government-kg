// エンティティページ(型別レイアウト。仕様§9.2)。
//
// **属性にも出典が付く**(裁定B82(4a)で仕様§9.2の未達を直した)。以前は
// `attributes: dict[述語, 値の一覧(素の文字列)]`で、どの名前付きグラフ由来か
// を保持していなかった——関係(relationships)には出典が付くのに属性には
// 付かない、仕様§9.2「全表示要素に一次資料へのリンクと取得日時を出す」の
// 未達だった。APIが`attributes: dict[述語, AttributeValue[]]`
// (`AttributeValue = { value, graphs }`)を返すようになったので、ここで
// 実際のリンクに置き換える。
//
// **`graphs`が単数ではなく複数(`AttributeValue.graphs: string[]`)な理由**:
// 同じ値を複数の名前付きグラフが主張することがある(`models.py`の
// `AttributeValue`docstring参照)——その場合は値ごとに複数の一次資料リンクを
// 並べる。
import type { AttributeValue, EntityDetailResponse, Relationship } from "../api/client";
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

/**
 * 属性の1つの値(`AttributeValue`)を、値そのものと出典リンクで描く。
 *
 * **`available === false`のときは空リンクを描かない**(`provenanceHtml`が
 * 既に守る。D-5と同じ扱い。裁定B82)。`graphs`が複数あれば
 * (同じ値を複数の名前付きグラフが主張する場合)一次資料リンクを複数並べる。
 */
function attributeValueHtml(av: AttributeValue, graphs: EntityDetailResponse["graphs"]): string {
  const provenances = av.graphs.map((g) => provenanceHtml(graphs[g])).join(" / ");
  return (
    `<span class="jgkg-attr-value">${esc(av.value)}</span>` +
    `<span class="jgkg-muted jgkg-attr-prov"> (${provenances})</span>`
  );
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
          `<tr><th>${esc(predicateLabel(pred))}</th><td>${values
            .map((v) => attributeValueHtml(v, entity!.graphs))
            .join("、")}</td></tr>`,
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
