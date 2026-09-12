// `views/overview.ts`(DOMを書く側)から抽出した純粋関数。**`graph-merge.ts`と
// 同じ理由でここに分離してある**——このリポジトリはvitestにDOM環境を持たない
// (jsdom/happy-dom未導入。トップページ第1層ブリーフのcontroller追記参照)ので、
// DOMを書く関数はテストできない。ここに置く関数はどれも`document`/`window`を
// 参照しない。

import type {
  BudgetAndExecution,
  MinistryBudget,
  RecipientIdentification,
  RequestExactlyGranted,
  TypeCount,
} from "../api/client";
import { formatAmountRounded } from "../format";

/**
 * 503(起動時の集約が失敗している状態。`app.state.overview is None`)を、
 * `apiUnavailableReason()`(APIそのものが未配備)と**取り違えないための
 * 別の文言**(裁定B84の教訓: 「対処が違う2つの原因を区別できないメッセージは
 * ゲートの欠陥」)。利用者に内部事情(503・集約・起動時)を説明しない
 * (トップページ第1層ブリーフStep 3b)。
 */
export const OVERVIEW_UNAVAILABLE_TEXT = "全体の数字をいま出せません。";

/**
 * 完全なIRIから型のローカル名を取り出す(例:
 * `https://jgkg.norr-tech.com/def/budget#BudgetProject` → `"BudgetProject"`)。
 *
 * **`src/jgkg/api/queries.py`の`_local_name`と同じ規則**(`#`優先・
 * 無ければ`/`)。`TypeCount.type`は完全IRIで返る仕様であり、ローカル名への
 * 切り出しは表示側の仕事だと`openapi-types.ts`のdocstringが明言している。
 */
export function localNameFromIri(iri: string): string {
  const hashIdx = iri.lastIndexOf("#");
  if (hashIdx !== -1) {
    const candidate = iri.slice(hashIdx + 1);
    if (candidate) return candidate;
  }
  const slashIdx = iri.lastIndexOf("/");
  if (slashIdx !== -1) {
    const candidate = iri.slice(slashIdx + 1);
    if (candidate) return candidate;
  }
  return iri;
}

/**
 * `type_counts`(CQ18)から、指定したローカル名の件数を引く。
 *
 * **複数のローカル名をフォールバック順に渡せる**が、呼び出し側は
 * 「この2つの型は同じ意味である」という業務知識を持っているときだけ
 * 使うこと。**`Law`/`LawRevision`のように意味が異なる型を、実データで
 * 件数が偶然一致するからといって束ねてはいけない**(修正ラウンド1・
 * レビューA4/S1で実際に踏んだ欠陥——`views/overview.ts`はいまこの引数を
 * 1つしか渡さない)。どのローカル名にも一致しなければ`null`(0で静かに
 * 間違えない。`overview.py`の`_int`と同じ方針)。
 */
export function typeInstanceCount(typeCounts: TypeCount[], ...localNames: string[]): number | null {
  for (const name of localNames) {
    const row = typeCounts.find((t) => localNameFromIri(t.type) === name);
    if (row) return row.instance_count;
  }
  return null;
}

/**
 * 府省の表示名。**`label`が`null`のときはIRIの経路形(`id_path`)を出す**——
 * 「(表示名なし)」のような合成文言ではなく、辿れる形にする(裁定B78/B88の
 * 「表示名を合成しない」に抵触しない。IRIは合成ではない)。
 */
export function ministryDisplayName(ministry: MinistryBudget): string {
  return ministry.label ?? ministry.id_path;
}

/** `ministries`(CQ15)の予算額を合計する。**合計してよいのは予算額だけ**(1事業1年度1値・重複なし。裁定B96)。 */
export function sumMinistryBudgets(ministries: MinistryBudget[]): number {
  return ministries.reduce((sum, m) => sum + m.total_budget, 0);
}

/**
 * `ministries`(CQ15)が答えている年度。**行ごとに書き込まれた値から読む**
 * ——画面側で「2025年度」のように書き込まない(手書きの契約と測定値を
 * 混同しない。controller補足3)。複数の年度が混在する場合は最大の年度
 * (最新)を返す。1行も無ければ`null`。
 */
export function latestFiscalYear(ministries: MinistryBudget[]): number | null {
  if (ministries.length === 0) return null;
  return Math.max(...ministries.map((m) => m.fiscal_year));
}

/**
 * `ministries`(CQ15)を、指定した年度の行だけに絞る。**さらに府省IDで
 * 重複を除く**(修正ラウンド1・レビューS5)。
 *
 * **CQ15は年度で絞っていない**(`?y`でもGROUP BYするだけ。ヘッダ「年度を
 * 固定で書き込むと来年のデータで黙って壊れる」参照)。複数年度が混在した
 * まま`sumMinistryBudgets`/`.length`/帯グラフに渡すと、合計が2年度分を
 * 足した値になり、府省数が行数(=府省数×年度数)になり、帯グラフに同じ
 * 府省が2本並ぶ——**この画面の全ての集計がこの関数を通ってから行われる
 * 前提を置く**。`fiscalYear`が`null`(=行が1件も無い)なら空配列を返す。
 */
export function ministriesForFiscalYear(
  ministries: MinistryBudget[],
  fiscalYear: number | null,
): MinistryBudget[] {
  if (fiscalYear === null) return [];
  const seen = new Set<string>();
  const out: MinistryBudget[] = [];
  for (const m of ministries) {
    if (m.fiscal_year !== fiscalYear) continue;
    if (seen.has(m.id)) continue;
    seen.add(m.id);
    out.push(m);
  }
  return out;
}

/**
 * 「{最大の府省}が全体の{割合}%」という句。**府省名も割合も`ministries`
 * (CQ15)から導出する**(修正ラウンド1・レビューA2/S2)。
 *
 * 当初の実装は「厚生労働省が全体の約4分の3」という文言をモックから
 * そのまま書き込んでいた——同じ画面の目盛り切替注記(`scaleExcludingTopNote`)
 * は同じ2つの値を動的に計算しているので、データが変われば本文とボタンが
 * 食い違う(裁定B103違反)。丸めた分数表現(「4分の3」)を再現する代わりに、
 * `scaleExcludingTopNote`と同じ精度(小数1桁の%)で揃える——2箇所が別の
 * 丸め方をしていると、それ自体が食い違いに見える。
 *
 * `ministries`が空、または合計予算が0以下(=割合が計算できない)なら`null`。
 */
export function topMinistryDominancePhrase(ministries: MinistryBudget[]): string | null {
  const top = ministries[0];
  if (!top) return null;
  const total = sumMinistryBudgets(ministries);
  if (total <= 0) return null;
  const pct = ((top.total_budget / total) * 100).toFixed(1);
  return `${ministryDisplayName(top)}が全体の${pct}%`;
}

/**
 * `sources`(`OverviewResponse.sources`)から「出所: CQ15」のような注記を作る。
 *
 * **CQ番号は`sources`のファイル名から導出する。対応表を手で書かない**
 * (controller補足1: 再発欠陥1と同型)。複数の項目にまたがる節は
 * 複数キーを渡せる(呼び出し側が渡した順で並べる)。
 */
export function cqNumberFromFilename(filename: string): string {
  const m = /^cq(\d+)-/.exec(filename);
  return m ? `CQ${Number(m[1])}` : filename;
}

/**
 * **`sources`に無いキーは黙って落とさない**(修正ラウンド1・レビューQ1)。
 * `sources`の型は`{ [key: string]: string }`(生成物`openapi-types.ts`が
 * インデックス型で返す)なので、TypeScriptはキーの誤り(呼び出し側の
 * typo・APIが`OVERVIEW_QUERIES`のキーを改名した場合)を検出できない。
 *
 * 引けなかったキーは`console.error`に出す(調査可能にする)——**それでも
 * 引けた分の出所は出す**(1項目消えたからといって残りの出所表示まで
 * 消すと、`renderHead`のように複数キーを1行にまとめている箇所で
 * 「一見正しいが実は1つ欠けている」出所表示になるより、欠落自体は
 * コンソールで分かる形にする)。**1件も引けなければ`null`を返し、
 * 呼び出し側はその節の出所行自体を出さない**(「出所: 」という空の
 * 主張を画面に残さない)。
 */
export function sourceCitation(sources: Record<string, string>, ...keys: string[]): string | null {
  const labels: string[] = [];
  for (const key of keys) {
    const filename = sources[key];
    if (filename === undefined) {
      console.error(`overview: sources に "${key}" が無い(出所の表示が欠落する)`, sources);
      continue;
    }
    labels.push(cqNumberFromFilename(filename));
  }
  if (labels.length === 0) return null;
  return `出所: ${labels.join("・")}`;
}

/**
 * 目盛りを「厚労省を除いて見る」に切り替えたときの注記文。
 *
 * **モック(`docs/mockups/top-page.html:1258`付近)の文言をそのまま使う**
 * ——対数目盛りにしない判断(「対数は集中の事実を静かに消す」)を持っている
 * のはこの文言自身であり、書き直さない。数値(除いた府省の名前・金額・
 * 割合・残りの件数)はすべて引数から計算し、手書きしない。
 */
export interface ScaleExcludingTopNoteInput {
  /** 除かれる府省(いまは全体最大)の表示名 */
  excludedName: string;
  /** 除かれる府省の予算額 */
  excludedBudget: number;
  /** 全府省の予算額の合計(除かれる府省を含む) */
  totalBudget: number;
  /** 除いた後に最大になる府省の表示名 */
  newMaxName: string;
  /** 除いた後の府省数(=全府省数-1) */
  restCount: number;
  /** 全府省数 */
  totalCount: number;
}

export function scaleExcludingTopNote(input: ScaleExcludingTopNoteInput): string {
  const pct = ((input.excludedBudget / input.totalBudget) * 100).toFixed(1);
  return (
    "目盛りを取り直しています——" +
    `${input.excludedName}（${formatAmountRounded(input.excludedBudget)}・全体の ${pct}%）を` +
    `除いた${input.restCount}府省のうち最大（${input.newMaxName}）を棒いっぱいにしています。` +
    `府省どうしの比較はこちらが読みやすく、全体に対する割合は「全${input.totalCount}府省」が正確です。`
  );
}

/**
 * 帯グラフの幅(%)。**線形**(`amount / max * 100`。0〜100にクランプする)。
 *
 * **対数目盛りにしないという判断の実体はこの計算そのものである**
 * (`docs/mockups/top-page.html`のコメント: 「対数は集中の事実を静かに消す」)。
 * 以前は`renderBars`/`renderHistory`(DOMを書く側)にこの式が直接埋め込まれ、
 * 「対数という語を含まない」というテストで守ろうとしていたが、それは
 * **文言を見ていて計算を見ていない**(実装を`Math.log(...)`に変えても
 * その種のテストは緑のままになる。修正ラウンド1・レビューQ2)。
 * ここに切り出し、**線形であること自体**(半分の値は必ず50%になる)を
 * 直接固定する。
 *
 * `max`が0以下(=比較対象が無い/計算できない)なら常に0。
 * `amount`が`max`を超えても100で止める(0%〜100%の外に出さない)。
 */
export function barWidthPercent(amount: number, max: number): number {
  if (!(max > 0)) return 0;
  const pct = (amount / max) * 100;
  return Math.min(100, Math.max(0, pct));
}

/**
 * `budget_and_execution`(CQ14)の行から、重複を除いた`sheet_year`を
 * 昇順で返す(修正ラウンド1・レビューS5)。
 *
 * **`sheet_year`は「そのレビューシート自体の年度」であり、
 * `budget_fiscal_year`(そのシートが語る予算年度)とは別の軸**
 * (`BudgetAndExecution`のdocstring参照)。将来2枚目のシートが増えると、
 * 同じ`budget_fiscal_year`について`sheet_year`が違う2行が現れうる——
 * この関数はその混在を検出するための土台。
 */
export function distinctSheetYears(rows: BudgetAndExecution[]): number[] {
  return [...new Set(rows.map((r) => r.sheet_year))].sort((a, b) => a - b);
}

/**
 * 表の年度ラベル。**シートが2種類以上混在しているときだけ`sheet_year`を
 * 併記する**(1種類だけなら`budget_fiscal_year`だけで区別できるので、
 * 冗長な注記を出さない)。混在しているのに`budget_fiscal_year`だけを
 * 出すと、2枚のシートが同じ年度を語る行が見分けられなくなる
 * (`BudgetAndExecution.sheet_year`をAPI側の型に足した理由そのもの)。
 */
export function historyRowYearLabel(row: BudgetAndExecution, sheetYears: number[]): string {
  return sheetYears.length > 1
    ? `${row.budget_fiscal_year}年度(${row.sheet_year}年度シート)`
    : `${row.budget_fiscal_year}年度`;
}

/**
 * 「この5年分は{年度}年度のレビューシートが記録しているもの」という
 * 注記。**シートが1種類のときだけこの文言が真になる**——2種類以上
 * 混在しているのに「{先頭行の年度}のシートが記録している」と書くと、
 * 他のシートの行についてはその文が偽になる(修正ラウンド1・レビューS5)。
 * 混在時は、正直に「複数のシートが混在している」と書く(数値は
 * `distinctSheetYears`からそのまま列挙するので手書きしない)。
 */
export function historySheetYearNote(sheetYears: number[]): string {
  const year = sheetYears[0];
  if (sheetYears.length <= 1) {
    return year !== undefined
      ? `この5年分は${year}年度のレビューシートが記録しているものです。年度ごとに別のシートを取ってきて並べたのではありません。`
      : "";
  }
  return (
    `この表には複数のレビューシート(${sheetYears.join("・")}年度)の主張が混在しています。` +
    "年度ラベルの隣に、どのシートの主張かを示しています。"
  );
}

/**
 * `budget_and_execution`(CQ14)の行のうち、`budget_fiscal_year`が最大の行。
 *
 * **配列の並び順(`rows[rows.length - 1]`)を信じない**(修正ラウンド1・
 * レビューS5)。CQ14は`ORDER BY ?sheetYear ?budgetYear`——シートが1種類
 * だけなら末尾行が最新の予算年度と一致するが、2枚目のシートが増えると
 * `sheetYear`が主なソート鍵になり、末尾行は必ずしも最新の予算年度では
 * なくなる。1行も無ければ`undefined`。
 */
export function mostRecentRow(rows: BudgetAndExecution[]): BudgetAndExecution | undefined {
  return rows.reduce<BudgetAndExecution | undefined>((best, r) => {
    if (!best || r.budget_fiscal_year > best.budget_fiscal_year) return r;
    return best;
  }, undefined);
}

/**
 * 「いくら要求して、いくら付いたか」の1行(表示用に整形済み)。
 *
 * `requestVsGrantedRows`が`RequestExactlyGranted`(CQ20)からそのまま
 * 組み立てる。**すべてのフィールドが「両方の年度に存在する事業だけ」という
 * 同じ母集団から来ている**(裁定「導出の母集団が正しくなければならない」。
 * `docs/decision-log.md`参照)——`RequestAndInitial`(CQ16)の全事業合計は
 * ここでは使わない。
 */
export interface RequestVsGrantedRow {
  /** 要求した年度(=`RequestExactlyGranted.request_fiscal_year`) */
  requestYear: number;
  /** 付いた当初予算の年度(=`requestYear + 1`。CQ16/CQ20のヘッダ参照) */
  grantedYear: number;
  /** 両方の年度に存在する事業だけの要求額の合計(`requested_both`) */
  requested: number;
  /** 同じ母集団の当初予算の合計(`initial_both`) */
  initial: number;
  /** 両方の年度に存在する事業の件数(分母) */
  projectsInBothYears: number;
  /** 額が完全一致した事業の件数 */
  exactMatches: number;
}

/**
 * `request_exactly_granted`(CQ20)から、「年度Yの要求 → 年度Y+1の当初予算」
 * という表示用の行を組み立てる。
 *
 * **母集団を混ぜない。** 以前の実装は`RequestAndInitial`(CQ16。年度Yの
 * *全*要求と年度Y+1の*全*当初予算の合計)を`requested`/`initial`に使い、
 * CQ20の`exactMatches`/`projectsInBothYears`だけを添える形だった——
 * これは2つの異なる母集団(全事業/両方の年度に存在する事業だけ)を
 * 同じ行に混在させ、**新規事業(前年の要求を持たない)が当初予算側だけを
 * 膨らませる分だけ比率を水増しする**(実測: 2022→2023年度がCQ16基準で
 * 104.1%という「要求より多く付いた」ように誤読させる値になった。原因は
 * 5.5兆円分の新規事業)。**CQ20が`requestedBoth`/`initialBoth`を足した
 * ことで、この行のすべての数字を「両方の年度に存在する事業だけ」という
 * 単一の母集団に揃えられる**——年度のマップ引き直しはもう要らない
 * (CQ20の結合が既に正しい母集団で計算している)。
 *
 * 返す行は`requestYear`昇順。
 */
export function requestVsGrantedRows(exactlyGranted: RequestExactlyGranted[]): RequestVsGrantedRow[] {
  return exactlyGranted
    .map((r) => ({
      requestYear: r.request_fiscal_year,
      grantedYear: r.request_fiscal_year + 1,
      requested: r.requested_both,
      initial: r.initial_both,
      projectsInBothYears: r.projects_in_both_years,
      exactMatches: r.exact_matches,
    }))
    .sort((a, b) => a.requestYear - b.requestYear);
}

/**
 * `row`の「要求額に対して当初予算が何%付いたか」(両方の年度に存在する
 * 事業だけの合計での比率)。**分母(要求額)が0以下(=計算できない)なら
 * `null`**(`topMinistryDominancePhrase`と同じ方針。0%という誤った確定値を
 * 出さない)。
 */
export function requestGrantedPercent(row: RequestVsGrantedRow): number | null {
  if (!(row.requested > 0)) return null;
  return (row.initial / row.requested) * 100;
}

/**
 * `row`の「両方の年度に存在する事業のうち、額が完全一致した事業の割合」
 * (CQ20)。分母(`projectsInBothYears`)が0以下なら`null`。
 */
export function exactMatchRatioPercent(row: RequestVsGrantedRow): number | null {
  if (!(row.projectsInBothYears > 0)) return null;
  return (row.exactMatches / row.projectsInBothYears) * 100;
}

/**
 * 複数の%値を「96.9〜99.4%」のような範囲表記にする。**モックは固定の
 * 範囲文言(「96.9〜99.4%」「3〜4割」)を書いていたが、これは特定の実測時点の
 * 値の手書きである**——年度が増えれば範囲も変わるので、この画面は
 * `request_exactly_granted`の全行から範囲を導出する
 * (controller補足3「測定値は導出する」)。
 *
 * 全ての値が同じ(または1件しかない)なら範囲ではなく単一の%を返す。
 * 非有限値(`requestGrantedPercent`等が`null`を返した行)は呼び出し側で
 * 除いてから渡すこと——この関数は空配列なら`null`を返す。
 */
export function percentRangeText(percents: number[], digits = 1): string | null {
  if (percents.length === 0) return null;
  const min = Math.min(...percents).toFixed(digits);
  const max = Math.max(...percents).toFixed(digits);
  return min === max ? `${min}%` : `${min}〜${max}%`;
}

/**
 * `recipient_identification`(CQ17)の4区分を合計した金額。**合計してよい
 * 理由**: この4区分は同じ集合(`?e budget:recipientMatchCategory ?category`
 * を持つ`Expenditure`)を排他的に分割したものであり(`GROUP BY ?category`)、
 * 重複が無い(`sumMinistryBudgets`と同じ「合計してよい条件」)。
 */
export function recipientTotalAmount(rows: RecipientIdentification[]): number {
  return rows.reduce((sum, r) => sum + r.total_amount, 0);
}

/**
 * `rows`から指定した`category`(裸の区分名。`resolved`等)の件数を引く。
 * **`typeInstanceCount`と同じ方針**: 見つからなければ0ではなく`null`
 * (区分が実データから消えた場合に0件と偽って言わない)。
 */
export function recipientCountForCategory(rows: RecipientIdentification[], category: string): number | null {
  const row = rows.find((r) => r.category === category);
  return row ? row.expenditure_count : null;
}
