// 検索ボックス起点(仕様§9.2)。
import { ApiError, apiUnavailableReason, search } from "../api/client";
import { SEARCH_LIMIT } from "../api/limits";
import { esc, truncationNotice } from "../format";
import { typeLabel } from "../labels";
import { navigate } from "../router";

// **検索はキー入力ごとに投げない(D-5ブリーフ実測: 1リクエストあたり
// 109,005件のラベル全走査。`ORDER BY`が全件計算を強制する)。** デバウンス
// を入れる。300msはこの規模のUIで一般的な値で、実測(0.25〜0.45秒)より
// 短いので「入力を止めてから結果が出るまで」の体感を大きく損なわない。
const DEBOUNCE_MS = 300;

//: KG本体のダウンロードへのリンク(生データは副次的な位置に。仕様§9.2)。
// APIが未配備のとき(下記)は同じリンクを主動線へ格上げする——手書きの
// 対応表を2箇所に持たないよう、この2件だけモジュール定数として共有する。
const _VOCAB_LINK = '<a href="/def/">語彙(オントロジー)の一覧</a>';
const _RELEASES_LINK =
  '<a href="https://github.com/nomhiro/japan-government-kg/releases" target="_blank" rel="noopener noreferrer">KG本体のダウンロード(GitHub Releases)</a>';

export function renderSearch(container: HTMLElement, initialQuery: string): void {
  // **裁定B82(2): APIが未配備なら検索ボックスを黙って置かない。**
  // D-6b(APIの配備先)が未決の間、本番デプロイでは`API_BASE`がループバック
  // を指したまま焼き込まれ、検索は打つたびに必ず失敗する——「動くもの」に
  // 見える入力欄を置いて実は毎回失敗するのは、このプロジェクトが繰り返し
  // 重い欠陥として扱ってきた「報告が嘘をつく」の体験版になる。
  const unavailable = apiUnavailableReason();
  if (unavailable) {
    container.innerHTML = `
      <section class="jgkg-search">
        <h1>日本政府ナレッジグラフ</h1>
        <p class="jgkg-notice">データ検索は準備中です。${esc(unavailable)}</p>
        <nav class="jgkg-primary-links">
          <p>${_VOCAB_LINK}</p>
          <p>${_RELEASES_LINK}</p>
        </nav>
      </section>
    `;
    return;
  }

  container.innerHTML = `
    <section class="jgkg-search">
      <h1>日本政府ナレッジグラフ</h1>
      <p class="jgkg-lead">法令・府省・予算事業・支出・法人を検索して、出典付きでつながりを辿れます。</p>
      <input type="search" class="jgkg-search-box" placeholder="例: 厚生労働省、年金、令和6年度の予算事業"
             value="${esc(initialQuery)}" autofocus>
      <div class="jgkg-search-results" aria-live="polite"></div>
      <footer class="jgkg-secondary">
        ${_VOCAB_LINK} ・ ${_RELEASES_LINK}
      </footer>
    </section>
  `;

  const input = container.querySelector<HTMLInputElement>(".jgkg-search-box")!;
  const results = container.querySelector<HTMLElement>(".jgkg-search-results")!;

  let timer: ReturnType<typeof setTimeout> | undefined;
  let latestQuery = "";

  async function run(q: string): Promise<void> {
    latestQuery = q;
    if (!q.trim()) {
      results.innerHTML = "";
      return;
    }
    results.innerHTML = '<p class="jgkg-muted">検索中…</p>';
    try {
      const res = await search(q, SEARCH_LIMIT.default);
      // デバウンス後も前のリクエストが遅れて返ることがある。最新の入力と
      // 食い違う応答を描かない(古い検索結果が新しい入力の上に残る事故を防ぐ)。
      if (q !== latestQuery) return;
      renderResults(res);
    } catch (e) {
      if (q !== latestQuery) return;
      results.innerHTML = `<p class="jgkg-error">検索に失敗しました: ${esc(e instanceof ApiError ? e.message : String(e))}</p>`;
    }
  }

  function renderResults(res: Awaited<ReturnType<typeof search>>): void {
    if (res.results.length === 0) {
      results.innerHTML = '<p class="jgkg-muted">見つかりませんでした。</p>';
      return;
    }
    const items = res.results
      .map(
        (hit) => `
        <li class="jgkg-hit" data-id-path="${esc(hit.id_path)}">
          <span class="jgkg-type-badge">${esc(typeLabel(hit.type))}</span>
          <span class="jgkg-hit-label">${esc(hit.label ?? "(表示名なし)")}</span>
          ${hit.summary ? `<span class="jgkg-hit-summary">${esc(hit.summary)}</span>` : ""}
        </li>`,
      )
      .join("");
    results.innerHTML = `<ul class="jgkg-hit-list">${items}</ul>${truncationNotice(res.truncated, res.limit, "検索結果")}`;
    results.querySelectorAll<HTMLElement>(".jgkg-hit").forEach((el) => {
      el.addEventListener("click", () => {
        const idPath = el.dataset.idPath!;
        navigate({ name: "entity", idPath });
      });
    });
  }

  input.addEventListener("input", () => {
    if (timer) clearTimeout(timer);
    const q = input.value;
    timer = setTimeout(() => run(q), DEBOUNCE_MS);
  });

  if (initialQuery) void run(initialQuery);
}
