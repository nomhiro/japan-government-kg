// トップページ第1層(裁定B103)。**一般の利用者が「日本政府の予算と支出の
// 全体像」に一番近づけるのは、23府省の予算額を金額順に並べた1画面である**
// ——名前を知らない28個のノードのグラフより速い(レビュー済みモック
// `docs/mockups/top-page.html`の判断)。
//
// **このビューが出す数字はすべて`OverviewResponse`(=CQの答え)である。**
// 画面用の別集計はここに置かない(裁定B103・原則1)——`sources`から
// CQ番号を導出する形で出所を明示する(`overview-format.ts`の
// `sourceCitation`)。
//
// **このファイルはDOMを書く側なのでテストを置かない**(このリポジトリの
// 作法。`views/graph-merge.ts`と同じ分離——純粋な計算は`overview-format.ts`
// に切り出し、そちらを`overview-format.test.ts`で検査する)。DOMの動作は
// 実ブラウザで確認する(裁定B93: 「描画された」は「動く」ではない)。
import type { BudgetAndExecution, MinistryBudget, OverviewResponse } from "../api/client";
import { fetchOverview } from "../api/client";
import { esc, formatAmountFull, formatAmountRounded } from "../format";
import { typeLabel } from "../labels";
import { navigate } from "../router";
import {
  OVERVIEW_UNAVAILABLE_TEXT,
  barWidthPercent,
  distinctSheetYears,
  historyRowYearLabel,
  historySheetYearNote,
  latestFiscalYear,
  ministriesForFiscalYear,
  ministryDisplayName,
  mostRecentRow,
  scaleExcludingTopNote,
  sourceCitation,
  sumMinistryBudgets,
  topMinistryDominancePhrase,
  typeInstanceCount,
} from "./overview-format";

type Scale = "all" | "rest";

/**
 * トップページ第1層を`root`に描く。
 *
 * **`/overview`が503を返す場合を扱う(起動時の集約が失敗している状態)。**
 * `apiUnavailableReason()`(APIそのものが未配備)とは別の経路——
 * こちらはAPIは動いているが集約だけが無い状態であり、`OVERVIEW_UNAVAILABLE_TEXT`
 * (`apiUnavailableReason()`の文言とは異なる。裁定B84)を出す。利用者に
 * 内部事情(503・起動時の集約)は説明しないが、コンソールには`ApiError`の
 * 内容を出す(調査可能にする)。
 */
export async function renderOverview(root: HTMLElement): Promise<void> {
  root.innerHTML = '<p class="jgkg-muted">全体の数字を読み込み中…</p>';
  let data: OverviewResponse;
  try {
    data = await fetchOverview();
  } catch (e) {
    // 利用者には内部事情(503・起動時の集約)を出さないが、調査可能にするため
    // コンソールには`ApiError`の内容を出す(トップページ第1層ブリーフStep 3b)。
    console.error("トップページ第1層(/overview)の取得に失敗した", e);
    root.innerHTML = `<p class="jgkg-notice">${esc(OVERVIEW_UNAVAILABLE_TEXT)}</p>`;
    return;
  }
  renderContent(root, data);
}

function renderContent(root: HTMLElement, data: OverviewResponse): void {
  // **CQ15は年度で絞っていない**(ヘッダ「年度を固定で書き込むと来年の
  // データで黙って壊れる」)。混在したまま合計・府省数・帯グラフに使うと
  // 2年度分を静かに足すことになる(修正ラウンド1・レビューS5)——以後の
  // 集計はすべて`currentMinistries`(最新年度に絞った後)を通す。
  const fiscalYear = latestFiscalYear(data.ministries);
  const currentMinistries = ministriesForFiscalYear(data.ministries, fiscalYear);
  const yearSuffix = fiscalYear !== null ? `（${fiscalYear}年度）` : "";

  root.innerHTML = `
    <section class="jgkg-overview" aria-label="日本政府の予算と支出の全体像">
      ${renderHead(data, currentMinistries, fiscalYear)}

      <h2>府省ごとの予算額${esc(yearSuffix)}</h2>
      ${sourceCitationHtml(data.sources, "ministries")}
      ${renderDominanceNote(currentMinistries)}
      <div class="jgkg-ov-scale" role="group" aria-label="目盛り"></div>
      <p class="jgkg-ov-sub jgkg-ov-scale-note" aria-live="polite"></p>
      <div class="jgkg-ov-bars"></div>

      <h2>予算はいくら付いて、いくら使われたか(5年分)</h2>
      ${sourceCitationHtml(data.sources, "budget_and_execution")}
      <div class="jgkg-ov-history">${renderHistory(data.budget_and_execution)}</div>
    </section>
  `;

  wireBars(root, currentMinistries);
}

/** `sourceCitation`が`null`(引けるキーが1つも無かった)なら、出所の行自体を出さない(修正ラウンド1・レビューQ1)。 */
function sourceCitationHtml(sources: Record<string, string>, ...keys: string[]): string {
  const citation = sourceCitation(sources, ...keys);
  return citation ? `<p class="jgkg-ov-source">${esc(citation)}</p>` : "";
}

/**
 * 「棒の長さは金額そのまま…」の説明文。**府省名と割合は`ministries`から
 * 導出する**(手書きの「厚生労働省が全体の約4分の3」を廃止。修正ラウンド1・
 * レビューA2/S2)——隣の目盛り切替注記(`scaleExcludingTopNote`)と同じ
 * 精度(小数1桁の%)で揃える。府省が0件のときは事実の句を省く。
 */
function renderDominanceNote(ministries: MinistryBudget[]): string {
  const dominance = topMinistryDominancePhrase(ministries);
  const dominanceClause = dominance
    ? `<b>${esc(dominance)}</b>という事実が、目盛りをいじると消えてしまうからです。`
    : "";
  return `<p class="jgkg-ov-sub">棒の長さは金額そのままです(対数にしていません)。${dominanceClause}府省をクリックすると、その府省を中心にしたグラフへ移ります。</p>`;
}

/**
 * 「規模」——骨格の要約(裁定B103)。件数・金額は`type_counts`(CQ18)と
 * `ministries`(CQ15。呼び出し側が既に最新年度に絞ったもの)から導出する。
 * 対応表を手で書かない——**型の表示名は`typeLabel()`で引く**
 * (修正ラウンド1・レビューS1: 手書きの「法人」「支出の記録」が生成物の
 * 「組織」「支出」と食い違っていた。`typeLabel("Organization")`が
 * 「組織」で不適切だと考えるなら、直す場所はオントロジー側の
 * `dcterms:title @ja`であり、この画面ではない)。
 */
function renderHead(data: OverviewResponse, currentMinistries: MinistryBudget[], fiscalYear: number | null): string {
  const totalBudget = sumMinistryBudgets(currentMinistries);
  const projectCount = typeInstanceCount(data.type_counts, "BudgetProject");
  // **`Law`のみ(`LawRevision`へのフォールバックを消した)**(修正ラウンド1・
  // レビューA4)。実データでは両方9,550件で偶然一致しているだけで、
  // 「法令」の件数として`LawRevision`(法令の改正版)を代わりに出す判断を
  // この画面が下してはいけない。
  const lawCount = typeInstanceCount(data.type_counts, "Law");
  const orgCount = typeInstanceCount(data.type_counts, "Organization");
  const expenditureCount = typeInstanceCount(data.type_counts, "Expenditure");
  // **一致する年度が無ければ項目を出さない**(修正ラウンド1・レビューS3/A3)。
  // 先頭行へのフォールバックは、「{fiscalYear}年度のみ」というバッジの下に
  // 別の年度の額を出してしまう——`lawCount`等と同じ「nullなら出さない」
  // 規律に揃える。
  const governmentPaidRow =
    fiscalYear !== null ? data.government_paid.find((r) => r.fiscal_year === fiscalYear) : undefined;

  const yearBadge = fiscalYear !== null ? `<span class="jgkg-ov-year">${fiscalYear}年度のみ</span><br>` : "";
  const projectsPhrase = projectCount !== null ? `${projectCount.toLocaleString("ja-JP")}件` : "件数不明";

  const facts: string[] = [`<span>予算額の合計 <b>${esc(formatAmountFull(totalBudget))}</b></span>`];
  facts.push(`<span>府省 <b>${currentMinistries.length}</b></span>`);
  if (lawCount !== null) {
    facts.push(`<span>${esc(typeLabel("Law"))} <b>${lawCount.toLocaleString("ja-JP")}</b></span>`);
  }
  if (orgCount !== null) {
    facts.push(`<span>${esc(typeLabel("Organization"))} <b>${orgCount.toLocaleString("ja-JP")}</b></span>`);
  }
  if (expenditureCount !== null) {
    facts.push(`<span>${esc(typeLabel("Expenditure"))} <b>${expenditureCount.toLocaleString("ja-JP")}</b></span>`);
  }
  if (governmentPaidRow) {
    // **「下限」であることを一語添える**(修正ラウンド1・レビューS4)。
    // `GovernmentPaidTotal`のdocstringが「画面に『正確な総額』と書くな」
    // と明記している——第4節(次のタスク)が入るまで、この画面がこの数字を
    // 出す唯一の場所であり、無注記のままにはできない。`title`に正確な値を
    // 併記する(修正ラウンド1・レビューQ3)。
    facts.push(
      `<span title="正確には ${esc(formatAmountFull(governmentPaidRow.government_paid))}">` +
        `国が支払った額(下限) <b>${esc(formatAmountRounded(governmentPaidRow.government_paid))}</b></span>`,
    );
  }

  return `
    <div class="jgkg-ov-head">
      <p class="jgkg-ov-lede">${yearBadge}国の予算事業 <b>${esc(projectsPhrase)}</b>・<b>${esc(formatAmountRounded(totalBudget))}</b>を、根拠になった法令と、お金が渡った先まで結び付けたものです。</p>
      <p class="jgkg-ov-facts">${facts.join("")}</p>
      ${sourceCitationHtml(data.sources, "government_paid", "ministries", "type_counts")}
      <p class="jgkg-ov-sub">前の年度は入っていないので、<b>増えた・減ったは分かりません</b>。この画面が答えられるのは「いま、どの府省の、どの事業に、いくら付いていて、それが誰に渡ったか」です。</p>
    </div>
  `;
}

/**
 * 府省の帯グラフ+目盛り切替を組み立てる。
 *
 * **全23府省すべてを出す(「上位N件+残りM府省」にしない)。** 目盛りの
 * 既定は「全府省」(最大=厚労省を棒いっぱいに)、切替後は先頭(=最大)の
 * 府省を除いた残りで取り直す。**対数目盛りにしない**——対数は集中の事実
 * (厚労省が全体の約3/4)を静かに消してしまう。この判断はレビュー済みの
 * モック(`docs/mockups/top-page.html`)が持っている(理由ごと)。
 */
function wireBars(root: HTMLElement, ministries: MinistryBudget[]): void {
  const scaleControlsEl = root.querySelector<HTMLElement>(".jgkg-ov-scale");
  const scaleNoteEl = root.querySelector<HTMLElement>(".jgkg-ov-scale-note");
  const barsEl = root.querySelector<HTMLElement>(".jgkg-ov-bars");
  if (!scaleControlsEl || !scaleNoteEl || !barsEl) return;

  let scale: Scale = "all";

  function refresh(): void {
    renderBars(barsEl!, ministries, scale);
    renderScaleNote(scaleNoteEl!, ministries, scale);
  }

  // **府省が2件未満なら「除いて見る」に意味が無いので切替自体を出さない。**
  if (ministries.length >= 2) {
    const top = ministries[0]!;
    scaleControlsEl.innerHTML = `
      <button type="button" data-scale="all" aria-pressed="true">全${ministries.length}府省</button>
      <button type="button" data-scale="rest" aria-pressed="false">${esc(ministryDisplayName(top))}を除いて見る</button>
    `;
    const buttons = Array.from(scaleControlsEl.querySelectorAll<HTMLButtonElement>("button"));
    for (const btn of buttons) {
      btn.addEventListener("click", () => {
        scale = btn.dataset.scale === "rest" ? "rest" : "all";
        for (const b of buttons) b.setAttribute("aria-pressed", String(b === btn));
        refresh();
      });
    }
  }

  refresh();
}

function renderBars(container: HTMLElement, ministries: MinistryBudget[], scale: Scale): void {
  if (ministries.length === 0) {
    container.innerHTML = '<p class="jgkg-muted">府省ごとの予算額のデータがありません。</p>';
    return;
  }
  // **既定は全府省。「除いて見る」は先頭(=予算額が最大)を除いた残り。**
  // `ministries`は`sources.ministries`(CQ15)が既に予算額の降順で返す
  // (`queries/cq/cq15-ministry-budget-ranking.rq`の`ORDER BY DESC(?totalBudget)`)
  // ——ここで並べ替え直さない。**この順序を信じる方針を最大値の取得にも
  // 揃える**(修正ラウンド1・レビューQ4): 先頭(`base[0]`)が常に最大なので
  // `Math.max`で防御的に取り直さない——防御と信頼が1つの関数の中で
  // 混在すると、「除く対象」と「最大値」がずれる余地を生む。
  const base = scale === "rest" ? ministries.slice(1) : ministries;
  if (base.length === 0) {
    container.innerHTML = "";
    return;
  }
  const max = base[0]!.total_budget;
  container.innerHTML = base
    .map((m) => {
      const name = ministryDisplayName(m);
      // **最低幅を持たせる(下位の府省が幅0で消えない)。** 幅そのものは
      // CSS側の`min-width`(`.jgkg-ov-bar-fill`)が守る——ここでは0%を
      // 許して構わない。
      const pct = barWidthPercent(m.total_budget, max);
      return `
        <button type="button" class="jgkg-ov-bar" data-id-path="${esc(m.id_path)}"
                title="${esc(name)} ${esc(formatAmountFull(m.total_budget))}">
          <span class="jgkg-ov-bar-name">${esc(name)}</span>
          <span class="jgkg-ov-bar-track"><span class="jgkg-ov-bar-fill" style="width:${pct.toFixed(3)}%"></span></span>
          <span class="jgkg-ov-bar-amt">${esc(formatAmountRounded(m.total_budget))}</span>
          <span class="jgkg-ov-bar-cnt">${m.project_count.toLocaleString("ja-JP")}事業</span>
        </button>`;
    })
    .join("");

  // **府省の棒をクリックしたらエンティティビューに飛ぶ**(トップページ第1層
  // ブリーフStep 6)。`id_path`をそのまま渡す(裁定B59/B69。ここでURLを
  // 組み立て直さない)。
  container.querySelectorAll<HTMLButtonElement>(".jgkg-ov-bar").forEach((btn) => {
    btn.addEventListener("click", () => {
      const idPath = btn.dataset.idPath;
      if (idPath) navigate({ name: "entity", idPath });
    });
  });
}

/** 目盛りを「除いて見る」に切り替えたときの注記(いま何を見ているかを画面に書く)。 */
function renderScaleNote(noteEl: HTMLElement, ministries: MinistryBudget[], scale: Scale): void {
  if (scale !== "rest" || ministries.length < 2) {
    noteEl.textContent = "";
    return;
  }
  // **降順を信じる(`renderBars`と同じ方針。修正ラウンド1・レビューQ4)。**
  // `rest[0]`(=先頭を除いた次)が常に残りの最大なので、`reduce`で
  // 取り直さない——取り直すと「除く対象はslice(1)基準・最大値はreduce
  // 基準」という2つの信頼度が1関数の中で混在する。
  const top = ministries[0]!;
  const rest = ministries.slice(1);
  const newMax = rest[0]!;
  noteEl.textContent = scaleExcludingTopNote({
    excludedName: ministryDisplayName(top),
    excludedBudget: top.total_budget,
    totalBudget: sumMinistryBudgets(ministries),
    newMaxName: ministryDisplayName(newMax),
    restCount: rest.length,
    totalCount: ministries.length,
  });
}

/**
 * 「予算はいくら付いて、いくら使われたか(5年分)」(裁定B99)。
 *
 * **正しい分母は歳出予算現額であり、当初予算ではない。** 当初予算と執行額を
 * 並べると「予算の1.2倍使った」のように誤読される年度がある——補正予算・
 * 前年度繰越・予備費を加えた歳出予算現額が正しい分母である。この説明
 * (裁定B99)はモックの文言をそのまま持ってくる。
 *
 * **`budget_and_execution`(CQ14)にある行だけを使う。** 「5年度すべてで
 * 差0円」「減額補正589件…」のような、この応答に無いフィールド(事業ごとの
 * 補正・予備費の内訳件数)に基づく主張はここに書かない——第1層に出す数字
 * はCQの答えでなければならない(裁定B103)。**ただし「必ず増えるとは
 * 限らない」という件数を伴わない判断は残す**(修正ラウンド1・裁定S7:
 * controllerが「1を復活させる。ただし件数は書かない」と裁定)。
 *
 * **複数のレビューシート(`sheet_year`)が混在する場合を受け止める**
 * (修正ラウンド1・レビューS5)。`rows`の並び順(`ORDER BY ?sheetYear
 * ?budgetYear`)を「末尾行が最新の予算年度」だと信じない——`mostRecentRow`
 * で`budget_fiscal_year`が最大の行を明示的に探す。
 */
function renderHistory(rows: BudgetAndExecution[]): string {
  if (rows.length === 0) {
    return '<p class="jgkg-muted">年度ごとの予算と執行のデータがありません。</p>';
  }
  const sheetYears = distinctSheetYears(rows);
  const maxAvailable = Math.max(...rows.map((r) => r.total_budget_available));
  const trs = rows
    .map((r) => {
      const widthPct = barWidthPercent(r.total_budget_available, maxAvailable);
      const execPct = barWidthPercent(r.executed_amount, r.total_budget_available);
      const initPct = barWidthPercent(r.initial_budget, r.total_budget_available);
      // **執行額0は「執行率0%」ではなく「まだ執行されていない」。** 空欄
      // (「—」)にする——0%という誤った確定値を出さない(mock/renderHistory
      // と同じ判断)。
      const executedText = r.executed_amount > 0 ? esc(formatAmountRounded(r.executed_amount)) : "—";
      const rateText =
        r.total_budget_available > 0 && r.executed_amount > 0
          ? `${((r.executed_amount / r.total_budget_available) * 100).toFixed(1)}%`
          : "—";
      // **歳出予算現額・執行額にも正確な値を`title`で併記する**
      // (修正ラウンド1・レビューQ3。当初予算は縦線=tickのtitleに既にある)。
      const availableTitle = esc(formatAmountFull(r.total_budget_available));
      const executedTitle = r.executed_amount > 0 ? ` title="${esc(formatAmountFull(r.executed_amount))}"` : "";
      return `
        <tr>
          <th>${esc(historyRowYearLabel(r, sheetYears))}</th>
          <td class="jgkg-ov-histbar">
            <span class="jgkg-ov-track" style="width:${widthPct.toFixed(2)}%">
              <span class="jgkg-ov-fill" style="width:${execPct.toFixed(2)}%"></span>
              <span class="jgkg-ov-tick" style="left:${initPct.toFixed(2)}%" title="当初予算 ${esc(formatAmountFull(r.initial_budget))}"></span>
            </span>
          </td>
          <td class="jgkg-ov-num">${esc(formatAmountRounded(r.initial_budget))}</td>
          <td class="jgkg-ov-num" title="${availableTitle}">${esc(formatAmountRounded(r.total_budget_available))}</td>
          <td class="jgkg-ov-num"${executedTitle}>${executedText}</td>
          <td class="jgkg-ov-num">${rateText}</td>
        </tr>`;
    })
    .join("");

  const latest = mostRecentRow(rows);
  const notYetExecutedNote =
    latest && latest.executed_amount === 0
      ? ` <b>${latest.budget_fiscal_year}年度の執行額が空欄なのは、まだ執行されていないから</b>です(執行率0%ではありません)。`
      : "";

  return `
    <table class="jgkg-ov-history-table">
      <thead><tr><th></th><th></th><th>当初予算</th><th>歳出予算現額</th><th>執行額</th><th>執行率</th></tr></thead>
      <tbody>${trs}</tbody>
    </table>
    <p class="jgkg-ov-sub">帯の全体が<b>歳出予算現額</b>(その年度に実際に使える額)、塗った部分が<b>執行額</b>、縦線が<b>当初予算</b>の位置です。当初予算より使える額が大きいのは、<b>補正予算・前年度からの繰越し・予備費</b>が加わるためです。ただし、これらは事業ごとに見ると<b>負になることもあります</b>(必ず増えるとは限りません)。${notYetExecutedNote}</p>
    <p class="jgkg-ov-sub">${esc(historySheetYearNote(sheetYears))}</p>
  `;
}
