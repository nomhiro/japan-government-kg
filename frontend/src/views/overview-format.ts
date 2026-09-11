// `views/overview.ts`(DOMを書く側)から抽出した純粋関数。**`graph-merge.ts`と
// 同じ理由でここに分離してある**——このリポジトリはvitestにDOM環境を持たない
// (jsdom/happy-dom未導入。トップページ第1層ブリーフのcontroller追記参照)ので、
// DOMを書く関数はテストできない。ここに置く関数はどれも`document`/`window`を
// 参照しない。

import type { MinistryBudget, TypeCount } from "../api/client";
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
 * **複数のローカル名をフォールバック順に渡せる**——例えば「法令」の件数は
 * `Law`が本来の対象だが、無ければ`LawRevision`で代える、という判断を
 * 呼び出し側(`views/overview.ts`)が選べるようにする(実データでは両方
 * 同じ件数だが、それを前提に決め打ちしない)。どのローカル名にも一致
 * しなければ`null`(0で静かに間違えない。`overview.py`の`_int`と同じ方針)。
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

export function sourceCitation(sources: Record<string, string>, ...keys: string[]): string {
  const labels = keys
    .map((k) => sources[k])
    .filter((f): f is string => f !== undefined)
    .map(cqNumberFromFilename);
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
