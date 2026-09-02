"""配信済みのサイトを、ビルド成果物(`site/`)と突き合わせて検証する本体。

**`scripts/verify-site.py` はこのモジュールを呼ぶだけの薄いCLIにする。**
理由: `tests/conftest.py` はネットワーク接続をsocketレベルで遮断するため、
比較ロジックのテストはHTTPをスタブして書く必要がある。ハイフンを含む
スクリプトファイル(`verify-site.py`)はPythonの`import`文で読めない
(`tests/test_check_site_build.py`参照)ので、テスト可能な本体はここに置く。

**裁定B63: 配信後の検証にハッシュ比較が無く、古い内容が有効なまま載っていても
通ってしまう。** `deploy`ジョブは配信の直前に`site/`をビルドしている
(`build-site.sh`)ので、配信後に各URLを取得して`site/`内の対応ファイルと
sha256を比べれば「デプロイが成功したこと」を初めて検証できる。

**裁定B65: HTMLはハッシュ比較できない。** Cloudflareのボット検出スクリプトが
HTML応答にのみ自動挿入されるため(実測: `</body>`直前に1行追加される)、
HTMLをハッシュ比較すると必ず落ちる検査になり「たまに赤くなるので無視される
検査」に退化する——検査が無いより悪い。**非HTMLはsha256の完全一致、HTMLは
構造検査**に分ける。

**裁定B64: 公開索引が配信済み5モジュールのうち2つを載せていない。** HTMLの
構造検査に「モジュール表の行の集合が`site.module_names()`と一致すること」
「各行に空でない説明文があること」を入れることで、B64とB63(HTMLの陳腐化
検出)が1つの仕組みで両方満たされる。

**裁定B66: 公開オントロジーにRFC 3986非適合のIRIが8件ある。** 列挙型の許容値
のURIが以前`{enum_uri}#{値}`という2つ目の"#"を持つ形で生成されていた
(`scripts/generate-schema.sh`の`gen-owl --enum-iri-separator /`で修正済み)。
再発を構造的に防ぐため、配信された`.ttl`に現れる全IRIのRFC 3986適合を
ここで検査する。

**比較対象は手書きのリストにしない。** `site/`を再帰的に走査して各ファイルの
URLを導出する(`served_files`)。拡張子なしのモジュールエイリアス
(`/def/core`)は`site.build()`が既に実ファイルとして作っているので、
「どのファイルがどのモジュールのエイリアスか」という規則をこちら側で
再実装する必要が無い——walkするだけで自動的に含まれる。
"""
import hashlib
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

import httpx
from rdflib import Graph, URIRef

from jgkg import build, site

# 配信物が名乗る名前空間。Content-Type や CORS と違い、これは**中身**の検査である。
# `scripts/*.py`は`jgkg.base_uri`のSOURCE_GLOBSに含まれるため、この文字列が
# 実際のベースURIとずれれば`uv run python -m jgkg.base_uri --check`が検出する
# (このモジュール専用の仕組みを別に作らない)。
NAMESPACE = "https://jgkg.norr-tech.com"

# Cloudflare Pagesは`_headers`/`_redirects`のようなアンダースコア始まりの
# ファイルを配信時の設定として消費するだけで、そのパス自体をコンテンツとして
# 配信しない。`site/`を再帰的に走査してURLを導出するとき、これらは対象から
# 除く(誤って`/_headers`というパスをコンテンツとして取得しにいかない)。
_RESERVED_ROOT_FILES = frozenset({"_headers", "_redirects", "_routes.json"})


# =============================================================================
# 取得: 失敗も値として返す(接続失敗で例外死させると、残りの項目が
# 「未検査」なのか「合格」なのか区別できなくなる。元の`_get`と同じ理由)。
# =============================================================================


@dataclass(frozen=True)
class FetchResult:
    status: int
    headers: dict[str, str]
    body: bytes


def fetch(client: httpx.Client, origin: str, path: str) -> FetchResult:
    """`origin + path`を取得する。**httpxを使う理由**: gzip等の
    Content-Encodingを既定で透過復号する(実測: `/robots.txt`はgzipで配信
    される。urllibは復号しないため生バイトのままだと比較が必ず不一致になる)。
    """
    try:
        r = client.get(origin + path, headers={"User-Agent": "jgkg-verify-site"})
        return FetchResult(r.status_code, dict(r.headers), r.content)
    except httpx.HTTPError as e:
        # 接続そのものが失敗した場合も値で返す(タイムアウト・TLS失敗等)。
        return FetchResult(0, {}, f"接続失敗: {e!r}".encode())


class _FetchCache:
    """1回分の検査(`run_all_checks`の1ラウンド)の中で、同じURLを2度取得しない。"""

    def __init__(self, client: httpx.Client, origin: str) -> None:
        self._client = client
        self._origin = origin
        self._cache: dict[str, FetchResult] = {}

    def get(self, path: str) -> FetchResult:
        if path not in self._cache:
            self._cache[path] = fetch(self._client, self._origin, path)
        return self._cache[path]


# =============================================================================
# URL↔ファイルの対応の導出(裁定B63/B40と同じ原則: 手書きの対応表を作らない)
# =============================================================================


def served_files(out_dir: Path) -> dict[str, Path]:
    """`out_dir`(ビルド済み`site/`)を再帰的に走査し、URLパス→実ファイルの対応を返す。

    **拡張子なしのモジュールエイリアスを再実装しない。** `site.build()`が
    `/def/core`のようなエイリアスを既に実ファイルとしてコピーしているので、
    ここでの走査は「どのファイルがどのURLに対応するか」を知る必要が無く、
    実在するファイルをそのままURLに変換するだけでよい。モジュールを追加した
    ときにこの集合が自動的に増える(手書きの一覧なら増えない)。

    **ディレクトリの`index.html`は、そのディレクトリ自身(末尾スラッシュ)に
    対応する**(裁定B81)——ルートの`index.html`が`/`に対応するのと同じ規則を
    `def/index.html`にも一般化し、`/def/`(一覧ページ)がブラウザ/検証が
    実際に読みに行くパスと一致するようにする。CloudflarePagesの
    ディレクトリインデックス配信を模した規則であり、実測は
    `wrangler pages dev`のローカル再現で確認する(このモジュールの
    テスト・呼び出し側のdocstring参照)。それ以外は`out_dir`からの
    相対パスをそのままURLパスにする。
    """
    served: dict[str, Path] = {}
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(out_dir)
        if len(rel.parts) == 1 and rel.name in _RESERVED_ROOT_FILES:
            continue
        if rel.name == "index.html":
            dir_parts = rel.parts[:-1]
            served["/" + "/".join(dir_parts) + ("/" if dir_parts else "")] = path
            continue
        served[f"/{rel.as_posix()}"] = path
    return served


def is_html_path(url_path: str) -> bool:
    """このパスがHTML(構造検査の対象)かどうか。非HTMLはsha256比較の対象。

    `/`(アプリ)・`/def/`(一覧ページ)はどちらも末尾スラッシュのディレクトリ
    インデックスなので`.endswith("/")`で一括して捕まえる(裁定B81。
    以前は`url_path == "/"`だけの特別扱いだった)。
    """
    return url_path.endswith(("/", ".html"))


# =============================================================================
# 診断: Turtleとしてパースできるか / HTMLフォールバックか
# (元`scripts/verify-site.py`の`_parse_turtle`/`_is_html_fallback`を移設)
# =============================================================================


def is_html_fallback(body: bytes) -> bool:
    """本文がHTMLかを判定する。

    Cloudflare Pages は存在しないパスに index.html を 200 で返し、しかも
    `_headers` の `/def/*` 規則が本文の内容に関係なく Content-Type: text/turtle を
    被せる。**状態コードもContent-Typeも欠落を隠す**(実測 2026-08-23)。
    """
    return body.lstrip()[:64].lower().startswith(b"<!doctype html")


def parse_turtle(body: bytes) -> Graph | None:
    """配信されたバイト列をTurtleとしてパースする。失敗は None を返す(例外死させない)。"""
    try:
        g = Graph()
        g.parse(data=body.decode("utf-8"), format="turtle")
        return g
    except Exception:  # noqa: BLE001 — 「RDFとして読めない」の判定が目的で、
        # rdflibが投げる例外型を列挙すると内部実装に結合してしまう。
        return None


# =============================================================================
# 裁定B66: 公開物の全IRIがRFC 3986に適合していることを検査する
# =============================================================================

# RFC 3986 §3.5: fragment = *( pchar / "/" / "?" )
#               pchar     = unreserved / pct-encoded / sub-delims / ":" / "@"
#               unreserved  = ALPHA / DIGIT / "-" / "." / "_" / "~"
#               sub-delims  = "!" / "$" / "&" / "'" / "(" / ")" / "*" / "+" / "," / ";" / "="
# "#" は gen-delim に属し、pchar にも sub-delims にも含まれない。
# `urllib.parse.urlsplit`は最初の"#"だけをフラグメントの区切りとして扱うため、
# 2つ目以降の"#"はフラグメント文字列の中にそのまま残る——Turtleの字句規則は
# これを通す(rdflibも読める)が、URIとしては非適合になる(裁定B66の実例:
# 列挙型許容値のURIが`{enum_uri}#{値}`という形で2つ目の"#"を持っていた)。
_FRAGMENT_RE = re.compile(r"(?:[A-Za-z0-9\-._~!$&'()*+,;=:@/?]|%[0-9A-Fa-f]{2})*\Z")


def fragment_conformance_violation(iri: str) -> str | None:
    """IRIのフラグメント部がRFC 3986のfragment文法に適合しない理由を返す。適合なら None。"""
    from urllib.parse import urlsplit

    fragment = urlsplit(iri).fragment
    if fragment and not _FRAGMENT_RE.match(fragment):
        return f"フラグメントがRFC 3986のfragment文法(pchar / \"/\" / \"?\")に適合しない: {fragment!r}"
    return None


def iri_violations(graph: Graph) -> list[tuple[str, str]]:
    """グラフに現れる全IRI(主語・述語・目的語のURIRef)のRFC 3986適合を確認する。

    リテラル・空白ノードは対象外(そもそもIRIではない)。同じ非適合IRIが
    複数のトリプルに現れても1件にまとめて返す。
    """
    violations: dict[str, str] = {}
    for s, p, o in graph:
        for term in (s, p, o):
            if not isinstance(term, URIRef):
                continue
            iri = str(term)
            if iri in violations:
                continue
            reason = fragment_conformance_violation(iri)
            if reason:
                violations[iri] = reason
    return sorted(violations.items())


# =============================================================================
# 裁定B64/B65: HTMLの構造検査(ハッシュ比較の代わり)
# =============================================================================


class _TableExtractor(HTMLParser):
    """HTML中の各`<table>`について、データ行(全セルが`<td>`の行)のセル文字列を集める。

    ヘッダ行(`<th>`を含む行)は対象に含めない。ネストした`<table>`は
    このページに現れないため対応しない(現れたら`tables`の対応関係が
    崩れるが、そのような構造はこのプロジェクトの索引ページには無い)。
    """

    def __init__(self) -> None:
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._table_stack: list[list[list[str]]] = []
        self._row: list[tuple[str, str]] | None = None
        self._cell_tag: str | None = None
        self._cell_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            table: list[list[str]] = []
            self.tables.append(table)
            self._table_stack.append(table)
        elif tag == "tr" and self._table_stack:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell_tag = tag
            self._cell_chunks = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._table_stack:
            self._table_stack.pop()
        elif tag == "tr" and self._row is not None:
            cell_tags = {t for t, _ in self._row}
            if self._row and cell_tags == {"td"} and self._table_stack:
                self._table_stack[-1].append([text for _, text in self._row])
            self._row = None
        elif tag in ("td", "th") and self._cell_tag == tag:
            text = "".join(self._cell_chunks).strip()
            if self._row is not None:
                self._row.append((tag, text))
            self._cell_tag = None

    def handle_data(self, data: str) -> None:
        if self._cell_tag is not None:
            self._cell_chunks.append(data)


def module_table_rows(html: str) -> list[list[str]]:
    """索引ページのモジュール表(データ行=セルが全て`<td>`の行)を抜き出す。

    **ページの`<table>`が1個であることを前提にする。** 0個や2個以上なら、
    どの表がモジュール表か機械的に決められないため例外にする——黙って
    誤った表を読むより、想定が崩れたことに気づけるほうが安全(このプロジェクトの
    `schema_lang.sort_rdf_lists`が未知の述語で例外にするのと同じ考え方)。
    """
    parser = _TableExtractor()
    parser.feed(html)
    if len(parser.tables) != 1:
        raise ValueError(
            f"index.htmlの<table>が1個ではない({len(parser.tables)}個)。"
            "モジュール表の検査はどの表を見るべきか機械的に決められない"
        )
    return parser.tables[0]


_ASSET_URL_RE = re.compile(r'(?:src|href)="(/assets/[^"]+)"')


def referenced_app_asset_urls(html: str) -> set[str]:
    """アプリのHTML(`/`)が`<script src=...>`/`<link href=...>`で参照する

    `/assets/`配下のURLの集合(裁定B81)。Viteは資産のファイル名に内容の
    ハッシュを埋め込むので、この集合は「そのビルドが実際に要求している
    正確なファイル名」そのものになる。
    """
    return set(_ASSET_URL_RE.findall(html))


def stale_app_asset_urls(html: str, served: dict[str, Path]) -> set[str]:
    """本番のHTML(`html`)が参照しているのに、`served`(いま手元で作った

    最新のビルド成果物)には存在しないURL(裁定B81「アプリの陳腐化検出」)。

    **部分集合の判定にする理由。** Viteは動的import由来のチャンクを
    エントリHTMLの`<script>`/`<link>`には出さないことがある
    (コード分割)——ビルド成果物の`/assets/`配下ファイル全部とHTML参照の
    完全一致を要求すると、そうした正当な「HTMLからは参照されないが
    実在する」ファイルを誤検出する。ここで検出したいのは「本番HTMLが
    指すハッシュ付きファイルが、いま作った最新ビルドに存在しない」という
    一方向の食い違い(=新しいビルドで名前が変わったのに本番が古い名前を
    まだ指している)だけなので、部分集合の判定で十分であり、かつ
    過剰検出を避けられる。
    """
    return {u for u in referenced_app_asset_urls(html) if u not in served}


def module_table_problems(html: str, expected_modules: Iterable[str]) -> list[str]:
    """モジュール表が`expected_modules`(通常は`site.module_names()`)と一致するかを確認する。

    **行の集合の一致**(裁定B64: 配信されているのに載っていないモジュールも、
    配信されていないのに残っている行も検出する)と、**各行の説明文が空でない
    こと**(裁定B64(2): 空欄で通してはならない)の両方を見る。
    """
    problems: list[str] = []
    try:
        rows = module_table_rows(html)
    except ValueError as e:
        return [str(e)]

    by_name: dict[str, list[str]] = {}
    for row in rows:
        if not row:
            continue
        by_name[row[0]] = row

    expected = set(expected_modules)
    missing = expected - by_name.keys()
    if missing:
        problems.append(f"モジュール表に無いモジュール: {sorted(missing)}")
    extra = by_name.keys() - expected
    if extra:
        problems.append(f"配信されていないモジュールの行がモジュール表にある: {sorted(extra)}")

    for name, row in sorted(by_name.items()):
        if name not in expected:
            continue
        if len(row) != 3:
            problems.append(f"モジュール{name!r}の行の列数が3ではない: {row}")
            continue
        description = row[2].strip()
        if not description:
            problems.append(f"モジュール{name!r}の説明文が空")

    return problems


# =============================================================================
# 全検査を1ラウンド実行する。リトライで包むのはこの関数全体
# (advisor指摘: モジュール追加自体も配信伝播待ちのレースの対象になるため、
# 新規チェックだけでなく既存チェックも含めた全体をリトライで包む)。
# =============================================================================


@dataclass(frozen=True)
class CheckResult:
    label: str
    ok: bool
    detail: str = ""


@dataclass(frozen=True)
class Report:
    results: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.results)

    @property
    def failures(self) -> list[CheckResult]:
        return [r for r in self.results if not r.ok]


def run_all_checks(
    origin: str,
    out_dir: Path,
    generated_dir: Path,
    client: httpx.Client,
) -> Report:
    """1ラウンド分の全検査(既存項目+B63/B64/B65/B66の新規項目)を行う。"""
    results: list[CheckResult] = []

    def check(label: str, cond: bool, detail: str = "") -> None:
        results.append(CheckResult(label, cond, detail))

    cache = _FetchCache(client, origin)
    modules = site.module_names(generated_dir)
    served = served_files(out_dir)

    check("配信物(site/)に検査対象のファイルがある", bool(served), f"{len(served)} 件")

    # --- 裁定B63: 非HTMLは配信物とビルド成果物のsha256が完全一致すること ------
    # `jgkg.build.file_sha256`(tarball/kg.nqの照合で既に使っている公開API。
    # 裁定B26)と同じ手段で比較する——「sha256比較」という同じ概念を
    # このプロジェクトの中で2つの実装に分けない。
    for url_path, local_path in sorted(served.items()):
        if is_html_path(url_path):
            continue
        fr = cache.get(url_path)
        expected_sha256 = build.file_sha256(local_path)
        actual_sha256 = hashlib.sha256(fr.body).hexdigest()
        # 不一致のとき、**それがHTMLフォールバックかどうかを言う**(裁定B84)。
        # 2026-09-02、`/assets/index-*.js` の不一致だけが6回連続で報告され、
        # 「status=200 で sha256 が違う」以外の情報が無かったため、
        # 「配備が伝播していない(欠落パスにHTMLが200で返る)」のか
        # 「配備されたバイト列が本当に違う」のかを切り分けられなかった。
        # 前者は待てば消えるが後者は待っても消えない——対処が正反対である。
        # `is_html_fallback` は本文で判定する(CloudflareがContent-Typeを
        # 被せるので、ヘッダでは判定できない。裁定B63の実測)。
        detail = f"sha256={expected_sha256}"
        if actual_sha256 != expected_sha256 or fr.status != 200:
            detail = f"status={fr.status} live_sha256={actual_sha256} local_sha256={expected_sha256}"
            if is_html_fallback(fr.body):
                # **配信元にあるのか、CDNのキャッシュが古いのかを分ける**
                # (裁定B85)。クエリ文字列を付けるとキャッシュキーが変わるので、
                # 配信元まで問い合わせが届く(実測 2026-09-02)。
                # **この追加取得は失敗時にしか走らない。**
                probe = fetch(client, origin, f"{url_path}?jgkg-cache-probe=1")
                probe_sha256 = hashlib.sha256(probe.body).hexdigest()
                if probe.status == 200 and probe_sha256 == expected_sha256:
                    detail += (
                        " ← 本文がHTML(欠落パスへのフォールバック)だが、"
                        "**配信元には正しいバイト列がある**"
                        "(キャッシュを迂回した取得は一致した)。"
                        "CDNが古いフォールバックを保持している"
                        "——待っても直らない。内容ハッシュを変えるか、"
                        "CDNのキャッシュを消すこと"
                    )
                else:
                    detail += (
                        " ← 本文がHTML(欠落パスへのフォールバック)で、"
                        "**キャッシュを迂回しても一致しない**"
                        f"(probe status={probe.status} sha256={probe_sha256})。"
                        "配備が伝播していない、または配信漏れ"
                    )
            else:
                detail += " ← 本文はHTMLではない。配備されたバイト列が実際に違う"
        check(
            f"{url_path} が配信物(site/)と同一バイト列(sha256一致)",
            fr.status == 200 and actual_sha256 == expected_sha256,
            detail,
        )

    # --- 裁定B66: 配信された.ttl全件のIRIがRFC 3986に適合していること --------
    for url_path in sorted(served):
        if not url_path.endswith(".ttl"):
            continue
        fr = cache.get(url_path)
        g = parse_turtle(fr.body)
        if g is None:
            check(f"{url_path} の全IRIがRFC 3986に適合している", False, "Turtleとしてパースできない")
            continue
        violations = iri_violations(g)
        check(
            f"{url_path} の全IRIがRFC 3986に適合している",
            not violations,
            "; ".join(f"{iri} — {reason}" for iri, reason in violations) if violations else "",
        )

    # --- モジュールごとの診断的検査(Content-Type/CORS/名前空間等) -----------
    for module in modules:
        alias = f"/def/{module}"
        fr = cache.get(alias)
        check(f"{alias} が 200", fr.status == 200, str(fr.status))

        ct = fr.headers.get("content-type", "")
        check(f"{alias} の Content-Type が text/turtle", ct.startswith("text/turtle"), ct or "無し")
        check(
            f"{alias} の CORS が開いている",
            fr.headers.get("access-control-allow-origin") == "*",
            fr.headers.get("access-control-allow-origin") or "無し",
        )

        g = parse_turtle(fr.body)
        check(
            f"{alias} がTurtleとしてパースできる",
            g is not None,
            f"{len(g)} triples" if g is not None else "パース失敗(HTMLが返っている可能性)",
        )
        declared = (
            {str(sub) for sub in set(g.subjects()) if str(sub).startswith(NAMESPACE)}
            if g is not None
            else set()
        )
        check(f"{alias} が {NAMESPACE} 配下のIRIを語っている", bool(declared), f"{len(declared)} 件")
        check(f"{alias} に開発用ドメインが残っていない", b"localhost" not in fr.body)
        check(f"{alias} がHTMLフォールバックではない", not is_html_fallback(fr.body))

    # --- SHACL形状: 検証ゲートの実体なので、公開物として引けることを確かめる ---
    shacl = cache.get("/def/all.shacl.ttl")
    check(
        "/def/all.shacl.ttl が 200 + text/turtle",
        shacl.status == 200 and shacl.headers.get("content-type", "").startswith("text/turtle"),
    )
    check("/def/all.shacl.ttl がHTMLフォールバックではない", not is_html_fallback(shacl.body))
    g = parse_turtle(shacl.body)
    shapes = (
        {o for o in g.objects(None, URIRef("http://www.w3.org/ns/shacl#targetClass"))}
        if g is not None
        else set()
    )
    check("SHACL形状が対象クラスを持っている", bool(shapes), f"{len(shapes)} クラス")

    # --- 裁定B64/B65/B81: 人向けの入口(HTML)は構造検査(ハッシュ比較しない) ---
    # `/`(アプリ。裁定B81)と`/def/`(語彙の一覧ページ)は役割が違うので、
    # 検査も分ける——`/`にモジュール表を要求したり、`/def/`に資産の
    # 陳腐化検査を要求したりすると、両方とも常にNGになる(空虚化どころか
    # 常時赤くなる検査になってしまう)。
    for url_path in sorted(served):
        if not is_html_path(url_path):
            continue
        fr = cache.get(url_path)
        check(f"{url_path} が 200 + text/html", fr.status == 200 and "text/html" in fr.headers.get("content-type", ""))
        try:
            text = fr.body.decode("utf-8")
        except UnicodeDecodeError:
            check(f"{url_path} の本文が読める(UTF-8)", False, "本文がUTF-8でない")
            continue
        check(
            f"{url_path} に非公式であることの明示がある",
            "政府による公式なデータセットではありません" in text,
        )

        if url_path == "/def/":
            problems = module_table_problems(text, modules)
            check(
                f"{url_path} のモジュール表が module_names() と一致し、説明文が揃っている",
                not problems,
                "; ".join(problems),
            )
        elif url_path == "/":
            referenced = referenced_app_asset_urls(text)
            check(f"{url_path} が /assets/ 配下の資産を参照している(空虚化防止)", bool(referenced), f"{len(referenced)} 件")
            stale = stale_app_asset_urls(text, served)
            check(
                f"{url_path} が参照する資産は、いまビルドした成果物に存在する(アプリの陳腐化検出)",
                not stale,
                f"存在しない参照: {sorted(stale)}" if stale else f"{len(referenced)} 件",
            )

    for path in ("/robots.txt", "/sitemap.txt"):
        fr = cache.get(path)
        check(f"{path} が 200", fr.status == 200, str(fr.status))

    return Report(results)


def run_all_checks_with_retries(
    origin: str,
    out_dir: Path,
    generated_dir: Path,
    client: httpx.Client,
    *,
    attempts: int = 1,
    delay_seconds: float = 10.0,
    sleep: Callable[[float], None] = time.sleep,
    on_retry: Callable[[int, int], None] | None = None,
) -> Report:
    """`run_all_checks`を最大`attempts`回試し、合格したら即座に返す。

    **既定は`attempts=1`(リトライ無し)。** ローカルのwrangler previewや
    手元での実行では、壊れていれば即座に赤くなってほしい(70秒待たされたくない)。
    **リトライが要るのはCI側**(`site-check.yml`)——直前のpushの配信が
    まだ伝播中の偽陽性を、`deploy`ジョブの検証と同じ回数だけ吸収する
    (裁定B63)。呼び出し側が明示的に`attempts`を渡す。

    **モジュール追加そのものも配信伝播待ちのレースになる**(法令/予算モジュールを
    追加した直後、まだ伝播していない本番に対しては`/def/law`の200判定すら
    一時的に落ちうる)。そのため新規チェック(sha256/HTML構造)だけでなく
    既存チェック全体をこの関数でリトライで包む。

    **リトライしても最終的に不一致なら落とす。** 最後の試行の結果をそのまま返す
    (途中の失敗の詳細は捨てる——`ci.yml`の既存のbashループと同じ考え方)。
    """
    report = run_all_checks(origin, out_dir, generated_dir, client)
    attempt = 1
    while not report.ok and attempt < attempts:
        if on_retry is not None:
            on_retry(attempt, attempts)
        sleep(delay_seconds)
        attempt += 1
        report = run_all_checks(origin, out_dir, generated_dir, client)
    return report
