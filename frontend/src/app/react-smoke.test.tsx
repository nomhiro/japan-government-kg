// @vitest-environment jsdom
// React + jsdom + Testing Library が実際に描画・検索できることの煙テスト。
// 「依存を入れた」ではなく「描いて読めた」を Phase 0 の最初の緑にする
// (裁定B93: 描画された≠動く。ここでは最低限「描画された」を機械で確かめる)。
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

describe("React の土台", () => {
  it("コンポーネントを jsdom に描き、テキストで見つけられる", () => {
    render(<p>土台の煙テスト</p>);
    expect(screen.getByText("土台の煙テスト")).toBeTruthy();
  });
});
