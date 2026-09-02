import { describe, expect, it } from "vitest";
import { computeApiUnavailableReason } from "./client";

// =============================================================================
// 裁定B82(2): APIが未配備であることを、ネットワークを叩かずに判定する
// =============================================================================

describe("computeApiUnavailableReason", () => {
  it("APIがlocalhostを指し、ページもlocalhostから配信されているとき(開発時)は null", () => {
    expect(computeApiUnavailableReason("http://localhost:8000", "localhost")).toBeNull();
  });

  it("APIが127.0.0.1を指し、ページも127.0.0.1から配信されているときは null", () => {
    expect(computeApiUnavailableReason("http://127.0.0.1:8000", "127.0.0.1")).toBeNull();
  });

  it("**核心**: APIがlocalhostを指すのに、ページが本番ホストから配信されているとき理由を返す", () => {
    const reason = computeApiUnavailableReason("http://localhost:8000", "jgkg.norr-tech.com");
    expect(reason).not.toBeNull();
    expect(reason).toContain("配備先");
  });

  it("APIが127.0.0.1を指すのに、ページが本番ホストから配信されているときも同様", () => {
    expect(computeApiUnavailableReason("http://127.0.0.1:8000", "jgkg.norr-tech.com")).not.toBeNull();
  });

  it("APIが本番ホストを指しているとき(D-6b解決後)は、ページのホストに関わらず null", () => {
    expect(computeApiUnavailableReason("https://api.jgkg.norr-tech.com", "jgkg.norr-tech.com")).toBeNull();
    expect(computeApiUnavailableReason("https://api.jgkg.norr-tech.com", "localhost")).toBeNull();
  });

  it("APIのURLが不正な形式でも例外にせず null を返す(この判定自体でクラッシュしない)", () => {
    expect(computeApiUnavailableReason("not a url", "jgkg.norr-tech.com")).toBeNull();
  });
});
