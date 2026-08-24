r"""Task 11修正ラウンド2 要修正5(裁定B33): §5の中核証拠をスクリプト化する。

`docs/measurements-phase1.md` §5の「nquads_sha256の不一致は内容の差ではなく
行順の差」という主張は、完了条件Cの判定を支える最も重い測定だが、
これを出したスクリプトが `scripts/` に無かった(B25違反)。RS-2024取得に
より`lake.latest_before`の「直近」が変わったため、同じ入力での
リリースBの再構築はもう再現できない——`data/artifact/2026-08-25/`と
`2026-08-26/`のkg.nqが両方残っている**間だけ**この検査は再現できる。

このスクリプトは2つのリリースディレクトリを取り、名前付きグラフごとに
行をソートしてsha256を突き合わせる(行の多重集合としての同一性を見る。
順序には依存しない)。**残余行(manifestが列挙するどのグラフにも属さない
行)が0であることも検査する**——グラフ数の一致だけでは、あるグラフの
行が別の名前で紛れ込むような取りこぼしを見逃す。

グラフ項の抽出: N-Quadsの1行は `<subject> <predicate> object <graph> .`
の形で終わる。**素朴な正規表現(`<[^>]*>\s*\.\s*$`で最後のIRIを取る)では
不十分だった**——IRI自体は生の`>`を含められないが、**objectのリテラルは
生の`<`を含められる**(N-Quadsのリテラルエスケープ規則は`"`・`\`・制御文字
しか要求せず、`<`/`>`は対象外)。実データに実例がある:
`"<こどもの事故防止に関する取組の経費＞ ..."`という値(全角の「＞」で
閉じているがASCIIの`<`で開いている)を持つ行があり、この生の`<`から
実際のグラフ項の`>`までを1つの(誤った)IRIとして正規表現が食ってしまう
ことを実行して発見した。**引用符の内外を状態として追う簡易トークナイザ**
(`_graph_of`)でこれを避ける——リテラル内部の`<`/`>`は構造として解釈しない。

**使い捨てにしない**(裁定B25)。出力は docs/measurements-phase1.md に転記する。

使い方:
    uv run python scripts/compare_releases.py data/artifact/2026-08-25 data/artifact/2026-08-26
"""
import argparse
import hashlib
from pathlib import Path

from jgkg import build

RESIDUAL_KEY = "(残余: グラフ項を抽出できない、またはmanifestに無いグラフ)"


def _graph_of(line: str) -> str | None:
    """N-Quadsの1行から末尾のグラフ項(IRI)を取り出す。

    引用符(`"`)の内外を状態として1文字ずつ追う。リテラルの内部にある
    `<`/`>`を構造(IRIの開始・終了)として誤読しないようにするため
    (モジュールdocstring参照。実データにこの罠の実例がある)。
    **このプロジェクトの成果物は名前付きグラフを常にIRIで書く**ため、
    グラフ項が空白ノード(`_:...`)である行は扱わない(該当行があれば
    IRIが見つからず`None`になり、残余行として検出される——気付かれずに
    無視される経路にはならない)。
    """
    in_literal = False
    i = 0
    n = len(line)
    last_iri: str | None = None
    last_iri_end = -1
    while i < n:
        c = line[i]
        if in_literal:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_literal = False
            i += 1
            continue
        if c == '"':
            in_literal = True
            i += 1
            continue
        if c == "<":
            j = line.find(">", i + 1)
            if j == -1:
                break
            last_iri = line[i + 1 : j]
            last_iri_end = j + 1
            i = j + 1
            continue
        i += 1
    if last_iri is None:
        return None
    # 見つけた最後のIRIの直後が空白と"."だけであること(=行の最後の項で
    # あること)を確認する。そうでなければグラフ項ではない(例:
    # objectのIRI自体が行の最後に来ることは無いはずだが、念のため)
    if line[last_iri_end:].strip() != ".":
        return None
    return last_iri


def _lines_by_graph(kg_nq: Path) -> dict[str, list[str]]:
    """kg.nqを1行ずつ読み、グラフ項ごとに行を集める(全体をメモリに一括
    ロードはするが、rdflibのDataset.parseのようなグラフモデルの構築は
    しない——このリリース規模〔数十万行〕ではリスト保持で十分軽い)。
    """
    by_graph: dict[str, list[str]] = {}
    with kg_nq.open(encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            graph = _graph_of(line)
            by_graph.setdefault(graph, []).append(line)
    return by_graph


def _sorted_sha256(lines: list[str]) -> str:
    h = hashlib.sha256()
    for line in sorted(lines):
        h.update(line.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("release_a", type=Path, help="例: data/artifact/2026-08-25")
    parser.add_argument("release_b", type=Path, help="例: data/artifact/2026-08-26")
    args = parser.parse_args()

    manifest_a = build.read_manifest(args.release_a / build.MANIFEST_NAME)
    manifest_b = build.read_manifest(args.release_b / build.MANIFEST_NAME)
    declared_graphs = set(manifest_a.graphs) | set(manifest_b.graphs)

    print("=" * 78)
    print(f"リリース比較(グラフ別ソート済みsha256): {args.release_a} vs {args.release_b}")
    print("=" * 78)
    print(f"manifest graphs A ({len(manifest_a.graphs)}): {sorted(manifest_a.graphs)}")
    print(f"manifest graphs B ({len(manifest_b.graphs)}): {sorted(manifest_b.graphs)}")
    print()

    by_graph_a = _lines_by_graph(args.release_a / "kg.nq")
    by_graph_b = _lines_by_graph(args.release_b / "kg.nq")

    # グラフ項をNoneで抽出できなかった行、またはmanifestに載っていない
    # グラフ名は「残余」としてまとめる(既知グラフの一覧に依存しない
    # 取りこぼし検査)
    all_keys = set(by_graph_a) | set(by_graph_b)
    residual_keys = {k for k in all_keys if k is None or k not in declared_graphs}
    named_graphs = sorted(k for k in all_keys if k not in residual_keys)

    mismatches: list[str] = []
    for g in named_graphs:
        lines_a = by_graph_a.get(g, [])
        lines_b = by_graph_b.get(g, [])
        sha_a = _sorted_sha256(lines_a)
        sha_b = _sorted_sha256(lines_b)
        same = sha_a == sha_b
        print(f"{'SAME  ' if same else 'DIFFER'} {g}")
        print(f"        A: {len(lines_a):>7,} 行  sha256={sha_a}")
        print(f"        B: {len(lines_b):>7,} 行  sha256={sha_b}")
        if not same:
            mismatches.append(g)

    residual_count_a = sum(len(by_graph_a.get(k, [])) for k in residual_keys)
    residual_count_b = sum(len(by_graph_b.get(k, [])) for k in residual_keys)
    print()
    print(f"残余行(いずれのmanifest記載グラフにも属さない行): "
          f"A={residual_count_a} / B={residual_count_b}")
    if residual_keys:
        print(f"  残余として検出されたグラフ項/キー: {sorted(str(k) for k in residual_keys)}")
    print(f"内容が一致しないグラフ: {len(mismatches)} 件 {mismatches}")

    if residual_count_a or residual_count_b or mismatches:
        print("判定: 不一致あり(**既定は失敗**)")
        return 1
    print(f"判定: 全{len(named_graphs)}グラフの内容が一致し、残余行も0件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
