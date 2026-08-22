"""配信されたオントロジーを、RDFの利用者の立場から検証する。

    uv run python scripts/verify-site.py                       # ローカル再現(wrangler)
    uv run python scripts/verify-site.py https://jgkg.norr-tech.com   # 公開先

**「ファイルが置けたか」ではなく「利用者が解釈できるか」を検査する。**
静的ファイルを置くだけでも、Content-Type が text/plain なら RDF クライアントは
解釈しないし、CORS が閉じていればブラウザ内のクライアントから使えない。
どちらもファイルの存在検査では出ない。

デプロイ前(ローカル再現)とデプロイ後(公開先)で同じものを流せるようにしてある。
"""
import sys
import urllib.error
import urllib.request

from rdflib import Graph, URIRef

DEFAULT_ORIGIN = "http://localhost:8788"
# 配信物が名乗る名前空間。Content-Type や CORS と違い、これは**中身**の検査である。
NAMESPACE = "https://jgkg.norr-tech.com"

MODULES = ("core", "org", "all")


def _is_html_fallback(body: bytes) -> bool:
    """本文がHTMLかを判定する。**欠落の直接の検出手段はこれだけである。**

    Cloudflare Pages は存在しないパスに index.html を 200 で返し、しかも
    `_headers` の `/def/*` 規則が本文の内容に関係なく Content-Type: text/turtle を
    被せる。**状態コードもContent-Typeも欠落を隠す**(実測 2026-08-23)。
    """
    return body.lstrip()[:64].lower().startswith(b"<!doctype html")


def _parse_turtle(body: bytes) -> Graph | None:
    """配信されたバイト列をTurtleとしてパースする。失敗は None を返す(例外死させない)。

    **Cloudflare Pages は存在しないパスに index.html を 200 で返す**(実測 2026-08-23)。
    つまり配信物が欠落しても 404 にならず、**「200が返る」だけの検査は欠落を合格と判定する。**
    Content-Type とパース可能性の両方を見ることで、この静かな失敗を捕まえる。
    """
    try:
        g = Graph()
        g.parse(data=body.decode("utf-8"), format="turtle")
        return g
    except Exception:  # noqa: BLE001 — 「RDFとして読めない」を判定するのが目的であり、
        # rdflib が投げる例外型を列挙すると内部実装に結合してしまう。
        return None


def _get(origin: str, path: str) -> tuple[int, dict[str, str], bytes]:
    """取得する。**404等でも例外死させず、状態コードを返して検査を続ける。**

    途中で落ちると残りの項目が「未検査」なのか「合格」なのか区別できなくなる。
    見えない未検査を作らないために、失敗も値として返す。
    """
    req = urllib.request.Request(origin + path, headers={"User-Agent": "jgkg-verify-site"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, {k: v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k: v for k, v in e.headers.items()}, e.read()


def main(argv: list[str]) -> int:
    origin = (argv[1] if len(argv) > 1 else DEFAULT_ORIGIN).rstrip("/")
    print(f"検証先: {origin}\n")
    failures: list[str] = []

    def check(label: str, cond: bool, detail: str = "") -> None:
        print(("OK " if cond else "NG ") + label + (f"  ({detail})" if detail else ""))
        if not cond:
            failures.append(label)

    for module in MODULES:
        alias = f"/def/{module}"
        canonical = f"/def/{module}.owl.ttl"

        status, headers, body = _get(origin, alias)
        check(f"{alias} が 200", status == 200, str(status))

        ct = headers.get("Content-Type", "")
        check(f"{alias} の Content-Type が text/turtle", ct.startswith("text/turtle"), ct or "無し")
        check(f"{alias} の CORS が開いている", headers.get("Access-Control-Allow-Origin") == "*",
              headers.get("Access-Control-Allow-Origin") or "無し")

        _, _, canonical_body = _get(origin, canonical)
        check(f"{alias} と {canonical} が同一バイト列", body == canonical_body,
              f"{len(body)} vs {len(canonical_body)} bytes")

        # **HTTP越しに取得したものをパースする。** ディスク上のファイルではなく、
        # 実際に配信された結果を検査する(charset や改行の変換が入り得る)。
        g = _parse_turtle(body)
        check(f"{alias} がTurtleとしてパースできる", g is not None,
              f"{len(g)} triples" if g is not None else "パース失敗(HTMLが返っている可能性)")

        declared = ({str(sub) for sub in set(g.subjects()) if str(sub).startswith(NAMESPACE)}
                    if g is not None else set())
        check(f"{alias} が {NAMESPACE} 配下のIRIを語っている", bool(declared),
              f"{len(declared)} 件")
        check(f"{alias} に開発用ドメインが残っていない", b"localhost" not in body)
        check(f"{alias} がHTMLフォールバックではない", not _is_html_fallback(body))

    # SHACL形状。検証ゲートの実体なので、公開物として引けることを確かめる
    status, headers, body = _get(origin, "/def/all.shacl.ttl")
    check("/def/all.shacl.ttl が 200 + text/turtle",
          status == 200 and headers.get("Content-Type", "").startswith("text/turtle"))
    check("/def/all.shacl.ttl がHTMLフォールバックではない", not _is_html_fallback(body))
    g = _parse_turtle(body)
    shapes = ({o for o in g.objects(None, URIRef("http://www.w3.org/ns/shacl#targetClass"))}
              if g is not None else set())
    check("SHACL形状が対象クラスを持っている", bool(shapes), f"{len(shapes)} クラス")

    # 人向けの入口と、非公式であることの明示
    status, headers, body = _get(origin, "/")
    check("/ が 200 + text/html",
          status == 200 and "text/html" in headers.get("Content-Type", ""))
    check("入口に非公式であることの明示がある",
          "政府による公式なデータセットではありません" in body.decode("utf-8"))

    for path in ("/robots.txt", "/sitemap.txt"):
        status, _, body = _get(origin, path)
        check(f"{path} が 200", status == 200, str(status))

    _, _, sitemap = _get(origin, "/sitemap.txt")
    listed = sitemap.decode("utf-8").count("/def/")
    check("sitemap が全モジュールの配信物を列挙している", listed == len(MODULES) * 3,
          f"{listed} 件 / 期待 {len(MODULES) * 3} 件")

    print()
    if failures:
        print(f"失敗 {len(failures)} 件:")
        for f in failures:
            print("  -", f)
        return 1
    print("すべて合格")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
