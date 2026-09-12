// エンティティ画面の純関数(裁定B106と同じ方針: DOM組み立てから分離し、
// テストで直接検査できるようにする)。
//
// **ここでやること**: `/entity` の応答(`EntityDetailResponse`)から、
// 画面が必要とする形を導く——型からの表示分岐(`kindOf`)・関係のフィルタと
// 除外(`relationshipsOfType`/`omitRelationshipTypes`)・出典の対応付け
// (`sectionSourceLines`/`valueSourceMarkers`)。
//
// **ここでやらないこと**: 表示名の合成(`labels.ts`の生成物をそのまま使う。
// 裁定B78/B88)・DOM/JSXの組み立て(呼び出し側のコンポーネントの仕事)。
import type { AttributeValue, EntityDetailResponse, EntityRef, Relationship } from "../../api/client";
import { sourceLines, type SourceLine } from "../../components/provenance";

// ---------------------------------------------------------------------------
// 型からの表示分岐
// ---------------------------------------------------------------------------

export type EntityKind = "ministry" | "project" | "organization" | "law" | "expenditure" | "generic";

/**
 * `Ministry`/`GovernmentOrgan`/`AbolishedGovernmentOrgan`は同じ見せ方
 * (所管する予算事業の一覧)を共有する——`schema/org.yaml`で3クラスとも
 * `GovernmentOrgan`の系譜であり、`ministry`(所管府省庁)の`range`は
 * `Organization`だが実データでこの3型が実際に現れる(裁定B36参照)。
 */
const MINISTRY_LIKE_TYPES: ReadonlySet<string> = new Set([
  "Ministry",
  "GovernmentOrgan",
  "AbolishedGovernmentOrgan",
]);

export function kindOf(type: string): EntityKind {
  if (MINISTRY_LIKE_TYPES.has(type)) return "ministry";
  if (type === "BudgetProject") return "project";
  if (type === "Organization") return "organization";
  if (type === "Law") return "law";
  if (type === "Expenditure") return "expenditure";
  return "generic";
}

// ---------------------------------------------------------------------------
// 属性
// ---------------------------------------------------------------------------

/**
 * 円のスロットの一覧(`schema/core.yaml`の`amount_jpy`、`schema/budget.yaml`の
 * `budgetAmount`/`initialBudget`等)。ここに載る述語の値は`<Amount>`で描く
 * ——手書きの表示ロジックが増えるたびにここへ追加する(値の解釈はここに
 * 1箇所だけ持つ)。
 */
export const AMOUNT_PREDICATES: ReadonlySet<string> = new Set([
  "budgetAmount",
  "amount_jpy",
  "initialBudget",
  "supplementaryBudget",
  "carriedOverFromPreviousYear",
  "reserveFund",
  "totalBudgetAvailable",
  "executedAmount",
  "nextYearRequest",
  "carriedOverToNextYear",
]);

export function isAmountPredicate(predicate: string): boolean {
  return AMOUNT_PREDICATES.has(predicate);
}

/** `predicate`の最初の値(単値スロット向け)。無ければ`undefined`(捏造しない)。 */
export function firstAttributeValue(
  entity: EntityDetailResponse,
  predicate: string,
): AttributeValue | undefined {
  return entity.attributes[predicate]?.[0];
}

// ---------------------------------------------------------------------------
// 関係
// ---------------------------------------------------------------------------

export interface RelationshipFilter {
  readonly predicate?: string;
  readonly direction?: "incoming" | "outgoing";
}

/**
 * `entity.relationships[typeName]`から、述語・向きで絞ったものを返す。
 * どちらも指定しなければその型のすべての関係(フィルタなし)。
 */
export function relationshipsOfType(
  entity: EntityDetailResponse,
  typeName: string,
  filter: RelationshipFilter = {},
): Relationship[] {
  const rows = entity.relationships[typeName] ?? [];
  return rows.filter(
    (r) =>
      (filter.predicate === undefined || r.predicate === filter.predicate) &&
      (filter.direction === undefined || r.direction === filter.direction),
  );
}

/**
 * 複数の候補型(例: 所管府省になり得る`Ministry`/`GovernmentOrgan`/
 * `AbolishedGovernmentOrgan`/`Organization`)にわたって同じ述語・向きの
 * 関係を集め、実際に存在した型だけをキーに持つオブジェクトを返す。
 * 該当する関係が1件も無い候補型はキーを作らない(空配列を混ぜない)。
 */
export function relationshipsGroupedFromTypes(
  entity: EntityDetailResponse,
  typeNames: readonly string[],
  filter: RelationshipFilter = {},
): EntityDetailResponse["relationships"] {
  const out: EntityDetailResponse["relationships"] = {};
  for (const typeName of typeNames) {
    const rows = relationshipsOfType(entity, typeName, filter);
    if (rows.length > 0) out[typeName] = rows;
  }
  return out;
}

/**
 * `omit`に挙げた型を除いた関係の一覧(型別の節が既に見せた関係を、汎用の
 * 「関係の一覧」で重複させないための引き算)。
 */
export function omitRelationshipTypes(
  relationships: EntityDetailResponse["relationships"],
  omit: readonly string[],
): EntityDetailResponse["relationships"] {
  const omitSet = new Set(omit);
  const out: EntityDetailResponse["relationships"] = {};
  for (const [k, v] of Object.entries(relationships)) {
    if (!omitSet.has(k)) out[k] = v;
  }
  return out;
}

export function totalRelationshipCount(relationships: EntityDetailResponse["relationships"]): number {
  return Object.values(relationships).reduce((n, rs) => n + rs.length, 0);
}

/**
 * 関係の型グループを件数の多い順に並べる(同数はローカル名の辞書順で
 * 決定的にする)。表示側が迷わないための唯一の並び順。
 */
export function sortedRelationshipGroups(
  relationships: EntityDetailResponse["relationships"],
): Array<readonly [string, Relationship[]]> {
  return Object.entries(relationships).sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
}

/**
 * パンくずの「所管」——`ministry`(所管府省庁)/`jurisdiction`(所管府省)を
 * outgoing で持つ関係から、最初の1件を返す(裁定: 表示名を合成しない。
 * `/entity`の応答が既に持つ関係から引くだけ)。
 *
 * 見つからない型(例: `Ministry`自身——所管の所管は無い)は`undefined`。
 */
const MINISTRY_REF_PREDICATES: readonly string[] = ["ministry", "jurisdiction"];
const MINISTRY_REF_TYPES: readonly string[] = ["Ministry", "GovernmentOrgan", "AbolishedGovernmentOrgan", "Organization"];

export function breadcrumbMinistryRef(entity: EntityDetailResponse): EntityRef | undefined {
  for (const predicate of MINISTRY_REF_PREDICATES) {
    for (const typeName of MINISTRY_REF_TYPES) {
      const hit = relationshipsOfType(entity, typeName, { predicate, direction: "outgoing" })[0];
      if (hit) return hit.related;
    }
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// 出典の対応付け(裁定B86: 節ごとに1行へまとめつつ、辿れることは失わない)
// ---------------------------------------------------------------------------

/**
 * 節に出てくる値(`AttributeValue`。`graphs`だけを見る)の一覧から、
 * `SourceNote`と同じ畳み方(`sourceLines`)で節全体の出典行を作る。
 */
export function sectionSourceLines(
  graphs: EntityDetailResponse["graphs"],
  values: readonly Pick<AttributeValue, "graphs">[],
): SourceLine[] {
  const onlyGraphs = [...new Set(values.flatMap((v) => v.graphs))];
  return sourceLines(graphs, onlyGraphs);
}

/**
 * `value`がどの出典行(`lines`の何番目。1始まり)から来ているかを返す。
 *
 * **節の出典行が1つしかないときは印を付けない**(`[]`を返す)——
 * その1行がその節のすべての値に当てはまるので、印を振ってもどれも同じ数字
 * になり、意味を持たない。行が2つ以上に分かれて初めて、どの値がどの行の
 * 主張かを示す印が要る。
 */
export function valueSourceMarkers(
  graphs: EntityDetailResponse["graphs"],
  lines: readonly SourceLine[],
  value: Pick<AttributeValue, "graphs">,
): number[] {
  if (lines.length <= 1) return [];
  const indices = new Set<number>();
  for (const g of value.graphs) {
    const prov = graphs[g];
    const available = prov ? prov.available !== false : false;
    const idx = lines.findIndex((l) =>
      available
        ? l.available && l.url === prov?.source && l.fetchedOn === prov?.fetched_on && l.license === prov?.license
        : !l.available && l.graph === g,
    );
    if (idx !== -1) indices.add(idx + 1);
  }
  return [...indices].sort((a, b) => a - b);
}

const MARKER_GLYPHS = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳";

/** 印の見た目(丸数字。21以上は`(21)`のように括弧数字へ落とす)。 */
export function markerGlyph(n: number): string {
  return n >= 1 && n <= MARKER_GLYPHS.length ? MARKER_GLYPHS.charAt(n - 1) : `(${n})`;
}

// ---------------------------------------------------------------------------
// 関係1行の表示(相手の名前・向き)
// ---------------------------------------------------------------------------

/** 表示名が無いノードの既定文言(裁定B78/B88: 名前を合成しない)。 */
export const NO_LABEL = "(表示名なし)";

export function displayLabel(ref: EntityRef): string {
  return ref.label ?? NO_LABEL;
}

/** 関係の向きを表す矢印(旧実装と同じ規則。incoming = 相手からこちらへ)。 */
export function directionArrow(direction: Relationship["direction"]): "→" | "←" {
  return direction === "outgoing" ? "→" : "←";
}

// ---------------------------------------------------------------------------
// 見出し直下の説明文(型ごとの固定コピー。データではなく画面の判断)
// ---------------------------------------------------------------------------

const KIND_ONE_LINER: Readonly<Record<EntityKind, string>> = {
  ministry: "この機関が所管する予算事業を、グラフと一覧で確認できます。",
  project: "この予算事業の金額・所管府省・根拠法令・支出の流れを確認できます。",
  organization: "この組織が支出を受け取った記録を確認できます。",
  law: "この法令の所管府省と、根拠として引く予算事業を確認できます。",
  expenditure: "この支出の金額・支払先・属する段を確認できます。",
  generic: "この項目の属性と、他の項目とのつながりを確認できます。",
};

/** ヘッダ帯に出す「その型の要点1行」。データの値ではなく画面の固定コピー。 */
export function kindOneLiner(kind: EntityKind): string {
  return KIND_ONE_LINER[kind];
}

const GRAPH_CAVEAT_COMMON =
  "色は6軸(誰が/何を/どこで/いつ/いくらで/何について)を表します。出典が取れていない関係にはリンクを描きません(裁定B86)。";

/**
 * グラフの下に置く注記(裁定: グラフを説明文で押し出さない。注記はグラフの後)。
 * `Law`だけ、改正記録が近傍に現れない既知の限界を明示する(観察O10)。
 */
export function graphCaveatText(kind: EntityKind): string {
  if (kind === "law") {
    return `${GRAPH_CAVEAT_COMMON} 法令の改正記録(LawRevision)はナレッジグラフ上で辺を持たないため、この近傍には現れません。`;
  }
  return GRAPH_CAVEAT_COMMON;
}
