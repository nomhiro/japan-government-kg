import { describe, expect, it } from "vitest";
import { parseHash, routeToHash } from "./router";

// =============================================================================
// トップページ第1層から第2層への遷移(トップページ第1層ブリーフTask5
// Step2)。**`id_path`はAPIが既にパーセントエンコード済みで返す**
// (`src/jgkg/uris.py`の`quote(name, safe="")`。裁定B59/B69/B73と同じ族の
// 欠陥——組み立て方が経路ごとに食い違うと`/entity/{id}`が存在しないIRIを
// 指す)。この画面(`views/overview.ts`)の府省の帯グラフは`id_path`を
// そのまま`navigate({name:"entity", idPath})`に渡す(`routeToHash`経由)。
//
// **ここで固定するのは「id_pathが再エンコードも再デコードもされずに
// 往復する」ことである。** `routeToHash`が`encodeURIComponent`を呼んだり、
// `parseHash`が`decodeURIComponent`を呼んだりすると、既にパーセント
// エンコードされた`id_path`が二重エンコード/二重デコードされ、
// `/entity/{id}`が実在しないパスになる(裁定B69が実際に踏んだ欠陥)。
// =============================================================================

describe("routeToHash → parseHash: entity route の id_path 往復", () => {
  it("**核心**: パーセントエンコード済みのid_path(廃止府省の例)が、二重エンコード/デコードされずに往復する", () => {
    // 実例(docs/decision-log.md 裁定B69・B73の対象): 「厚生省」(廃止府省)。
    const idPath = "org/abolished/%E5%8E%9A%E7%94%9F%E7%9C%81";
    const hash = routeToHash({ name: "entity", idPath });
    expect(hash).toBe(`#/entity/${idPath}`);
    // 二重エンコードされていれば"%25E5%8E..."のように"%25"が混じる。
    expect(hash).not.toContain("%25");
    expect(parseHash(hash)).toEqual({ name: "entity", idPath });
  });

  it("複数セグメントを含むid_path(unresolved配下)も往復する", () => {
    const idPath = "unresolved/jurisdiction/%E6%B3%95%E4%BB%A4123/%E5%90%8D%E7%A7%B0";
    const hash = routeToHash({ name: "entity", idPath });
    expect(parseHash(hash)).toEqual({ name: "entity", idPath });
  });

  it("パーセントエンコードが不要な素のid_path(数値のみの法人ID等)も往復する", () => {
    const idPath = "org/6000012070001";
    const hash = routeToHash({ name: "entity", idPath });
    expect(hash).toBe("#/entity/org/6000012070001");
    expect(parseHash(hash)).toEqual({ name: "entity", idPath });
  });
});
