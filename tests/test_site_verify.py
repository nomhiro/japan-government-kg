"""`jgkg.site_verify`(裁定B63/B64/B65/B66の検査本体)のテスト。

**実ネットワークは使わない**(`tests/conftest.py`が遮断する)。`httpx.MockTransport`で
「配信済みのサイト」を模擬し、ローカルの`site.build()`出力(`out_dir`)と比較する。
"""
import shutil
from pathlib import Path

import httpx
import pytest

from jgkg import site, site_verify
from jgkg.config import get_settings

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATED = REPO_ROOT / "schema" / "generated"
REAL_SITE = REPO_ROOT / "site"
#: 一覧ページ(裁定B81)のソース。`site/`の中には置かない
#: (`site/`全体がCloudflare Pagesの配信ルートなので、そこに置いたファイルは
#: 意図せず配信対象になる——実際に`site/def-index.html`という形で試し、
#: `/def-index.html`が誤って200を返すことをwrangler pages devで確認した)。
REAL_TEMPLATES = REPO_ROOT / "templates"
MODULES = sorted(site.module_names(GENERATED))


@pytest.fixture(autouse=True)
def _fixed_base(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "https://jgkg.norr-tech.com")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


#: `sync_app()`が期待する最小のVite dist形(index.html + 内容ハッシュ付き資産1本)。
#: npm/viteは使わず、`_full_build`がこの内容から`site/`上に模擬のアプリを作る。
_FAKE_APP_INDEX_HTML = (
    "<!doctype html><html><head><title>JGKG</title></head>"
    "<body>"
    '<p class="notice">このプロジェクトは日本国政府とは無関係です。'
    "日本国政府が公開するデータを第三者が構造化したものであり、"
    "政府による公式なデータセットではありません。</p>"
    '<div id="app"></div>'
    '<script type="module" src="/assets/index-fakehash123.js"></script>'
    '<link rel="stylesheet" href="/assets/index-fakehash456.css">'
    "</body></html>"
)


def _full_build(out_dir: Path) -> None:
    """`site.build()`(生成物)に、git管理下の静的ファイルと模擬アプリを足して

    本物の`site/`を再現する。

    `site.build()`自体は一覧ページ(`def/index.html`)/`robots.txt`を作らない
    (前者は手書きの静的ページ`templates/def-index.html`を`build-site.sh`が
    コピーする構成。後者もそのまま置かれた手書きファイル)。アプリ
    (`/`。裁定B81)は`site.sync_app()`を、実際のnpm/viteの代わりに
    `_FAKE_APP_INDEX_HTML`が指す資産を持つ最小のdistディレクトリに対して
    呼ぶことで再現する——このテストファイルはNode/npmに依存しない
    (`tests/conftest.py`のsubprocess許容とは無関係に、そもそも呼ばない)。
    """
    site.build(GENERATED, out_dir)
    shutil.copy2(REAL_TEMPLATES / "def-index.html", out_dir / "def" / "index.html")
    shutil.copy2(REAL_SITE / "robots.txt", out_dir / "robots.txt")

    dist_dir = out_dir.parent / (out_dir.name + "-fake-dist")
    (dist_dir / "assets").mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text(_FAKE_APP_INDEX_HTML, encoding="utf-8")
    (dist_dir / "assets" / "index-fakehash123.js").write_text("console.log('jgkg')", encoding="utf-8")
    (dist_dir / "assets" / "index-fakehash456.css").write_text("body{margin:0}", encoding="utf-8")
    site.sync_app(dist_dir, out_dir)


def _local_path_for(live_dir: Path, url_path: str) -> Path:
    """テスト用の擬似配信サーバが、`url_path`に対して返すべき実ファイルを解決する。

    `site_verify.served_files`と同じ規則(ディレクトリの既定ページは
    末尾スラッシュのパスに対応する。裁定B81でルート"/"だけの特別扱いから
    一般化した)をここでも適用する——適用しないと`live_dir / "".lstrip("/")`
    が`live_dir`自身(ディレクトリ)になり、"/"や"/def/"へのGETが常に
    404になる。
    """
    if url_path.endswith("/"):
        return live_dir / url_path.strip("/") / "index.html"
    return live_dir / url_path.lstrip("/")


def _content_type_for(url_path: str) -> str:
    if url_path.endswith(("/", ".html")):
        return "text/html; charset=utf-8"
    if url_path.endswith(".ttl") or (url_path.startswith("/def/") and "." not in url_path.rsplit("/", 1)[-1]):
        return "text/turtle; charset=utf-8"
    return "text/plain; charset=utf-8"


def _handler_mirroring(
    live_dir: Path,
    *,
    overrides: dict[str, bytes] | None = None,
    stale_cache: dict[str, bytes] | None = None,
) -> "httpx.MockTransport":
    """`live_dir`を配信元として振る舞う`MockTransport`を作る(裁定B65のCORS/Content-Typeも模擬する)。

    `overrides`に指定したパスは、`live_dir`の実ファイルではなくこの値を返す
    (「配信済みの内容がビルド成果物と食い違っている」状態を作るため)。

    `stale_cache`に指定したパスは、**クエリ文字列が無いときだけ**この値を返し、
    クエリ文字列が付いていれば`live_dir`の実ファイルを返す(裁定B85)——
    「CDNのキャッシュに古い応答が居座っているが、配信元は正しい」状態の模擬。
    実際のCloudflareもクエリ文字列でキャッシュキーが変わる(実測 2026-09-02)。
    """
    overrides = overrides or {}
    stale_cache = stale_cache or {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in stale_cache and not request.url.query:
            body = stale_cache[path]
        elif path in overrides:
            body = overrides[path]
        else:
            local = _local_path_for(live_dir, path)
            if not local.is_file():
                return httpx.Response(404, content=b"not found")
            body = local.read_bytes()
        headers = {"content-type": _content_type_for(path)}
        if path.startswith("/def/"):
            headers["access-control-allow-origin"] = "*"
        return httpx.Response(200, content=body, headers=headers)

    return httpx.MockTransport(handler)


def _client(
    live_dir: Path,
    *,
    overrides: dict[str, bytes] | None = None,
    stale_cache: dict[str, bytes] | None = None,
) -> httpx.Client:
    return httpx.Client(
        transport=_handler_mirroring(live_dir, overrides=overrides, stale_cache=stale_cache)
    )


# =============================================================================
# served_files: URL↔ファイルの導出(比較対象を手書きにしない)
# =============================================================================


def test_served_files_maps_index_html_to_the_root_path(tmp_path):
    _full_build(tmp_path)
    served = site_verify.served_files(tmp_path)
    assert served["/"] == tmp_path / "index.html"
    assert "/index.html" not in served


def test_served_files_excludes_the_cloudflare_headers_file(tmp_path):
    """`_headers`はCloudflare Pagesが配信時の設定として消費するだけで、

    そのパス自体はコンテンツとして配信されない。含めると存在しないURLを
    比較対象にしてしまう。
    """
    site.build(GENERATED, tmp_path)
    site.write_headers(site.build(GENERATED, tmp_path), tmp_path)
    served = site_verify.served_files(tmp_path)
    assert "/_headers" not in served
    assert (tmp_path / "_headers").is_file(), "前提: _headersファイル自体は実在する"


def test_served_files_covers_every_module_alias_and_canonical_file(tmp_path):
    _full_build(tmp_path)
    served = site_verify.served_files(tmp_path)
    for module in MODULES:
        assert f"/def/{module}" in served
        assert f"/def/{module}.owl.ttl" in served
        assert f"/def/{module}.shacl.ttl" in served


def test_served_files_grows_when_a_file_is_added_to_the_build(tmp_path):
    """**この検査が導出を強制する核心。** `MODULES`のような手書きの一覧なら

    ファイルを1本足しても比較対象は増えない。`served_files`は`out_dir`を
    再帰的に見るので、足した分だけ自動的に増える。
    """
    _full_build(tmp_path)
    before = site_verify.served_files(tmp_path)

    (tmp_path / "def" / "extra-module.owl.ttl").write_bytes(b"# dummy\n")

    after = site_verify.served_files(tmp_path)
    assert len(after) == len(before) + 1
    assert "/def/extra-module.owl.ttl" in after


def test_is_html_path():
    assert site_verify.is_html_path("/")
    assert site_verify.is_html_path("/def/")
    assert site_verify.is_html_path("/about.html")
    assert not site_verify.is_html_path("/def/core.owl.ttl")
    assert not site_verify.is_html_path("/robots.txt")


def test_served_files_maps_def_index_html_to_the_def_directory_path(tmp_path):
    """`site.py`と対になる規則(裁定B81): `def/index.html`は`/def/`

    (末尾スラッシュ)に対応すること。`/def/index.html`という鍵は作らない
    ——`served_files`のこの規則が無いと、`/def/`(実際にブラウザ/検証が
    読みに行くパス)に対応する実ファイルが見つからない。
    """
    _full_build(tmp_path)
    served = site_verify.served_files(tmp_path)
    assert served["/def/"] == tmp_path / "def" / "index.html"
    assert "/def/index.html" not in served


# =============================================================================
# 裁定B66: RFC 3986のフラグメント適合検査
# =============================================================================


def test_fragment_conformance_violation_flags_a_second_hash():
    """実際の欠陥(2つ目の"#")を検出する。"""
    iri = "https://jgkg.norr-tech.com/def/core#UnresolvedReasonEnum#AMBIGUOUS"
    violation = site_verify.fragment_conformance_violation(iri)
    assert violation is not None
    assert "#" in violation or "適合しない" in violation


def test_fragment_conformance_violation_accepts_the_fixed_form():
    """修正後の形("/"区切り)は適合する。"""
    iri = "https://jgkg.norr-tech.com/def/core#UnresolvedReasonEnum/AMBIGUOUS"
    assert site_verify.fragment_conformance_violation(iri) is None


def test_fragment_conformance_violation_accepts_ordinary_hash_uris_and_percent_encoding():
    """実際に配信されている、問題の無いIRIで偽陽性を出さない(空虚な検査にしない)。"""
    assert site_verify.fragment_conformance_violation("https://jgkg.norr-tech.com/def/core#Agent") is None
    assert site_verify.fragment_conformance_violation("https://jgkg.norr-tech.com/def/law#lawId") is None
    # フラグメントに"/"を含むのはRFC 3986上合法(fragment = *( pchar / "/" / "?" ))
    assert site_verify.fragment_conformance_violation("https://example.test/x#a/b") is None
    # パーセントエンコードも合法
    assert site_verify.fragment_conformance_violation("https://example.test/x#a%20b") is None
    assert site_verify.fragment_conformance_violation("https://jgkg.norr-tech.com/def/core") is None


def test_iri_violations_scans_subjects_predicates_and_objects_and_deduplicates():
    from rdflib import RDF, Graph, Literal, URIRef

    bad = URIRef("https://jgkg.norr-tech.com/def/core#Enum#Value")
    ok = URIRef("https://jgkg.norr-tech.com/def/core#Agent")
    g = Graph()
    g.add((ok, RDF.type, bad))  # 目的語としても現れる
    g.add((bad, RDF.type, bad))  # 主語としても現れる(重複を1件にまとめられるか)

    violations = site_verify.iri_violations(g)
    assert [iri for iri, _ in violations] == [str(bad)]
    # Literalは対象外(そもそもIRIではない)
    g.add((ok, RDF.value, Literal("plain text")))
    assert len(site_verify.iri_violations(g)) == 1


def test_run_all_checks_flags_a_real_rfc3986_violation_in_the_live_owl(tmp_path):
    """`run_all_checks`が実際に配信されたTurtle本文からIRI違反を見つけること。

    (壊し確認: 手元のビルドは修正済みなので、ライブ側だけ旧・二重#の形に
    差し替えて壊す)。
    """
    _full_build(tmp_path)
    corrupted = (
        (tmp_path / "def" / "core.owl.ttl")
        .read_bytes()
        .replace(b"core#UnresolvedReasonEnum/AMBIGUOUS", b"core#UnresolvedReasonEnum#AMBIGUOUS")
    )
    assert corrupted != (tmp_path / "def" / "core.owl.ttl").read_bytes(), "前提: 実際に置換できている"

    client = _client(tmp_path, overrides={"/def/core.owl.ttl": corrupted, "/def/core": corrupted})
    report = site_verify.run_all_checks(
        "https://jgkg.norr-tech.com", tmp_path, GENERATED, client
    )
    iri_failures = [r for r in report.failures if "RFC 3986" in r.label and "/def/core.owl.ttl" in r.label]
    assert iri_failures, [r.label for r in report.failures]
    assert "UnresolvedReasonEnum#AMBIGUOUS" in iri_failures[0].detail


# =============================================================================
# 裁定B64/B65: HTMLの構造検査(モジュール表)
# =============================================================================

_PRE_B64_FIX_TABLE_HTML = """
<html><body>
  <table>
    <thead><tr><th>モジュール</th><th>URI</th><th>内容</th></tr></thead>
    <tbody>
      <tr>
        <td>core</td>
        <td class="mono"><a href="/def/core">/def/core</a></td>
        <td>6軸の基底クラスと、出典を表す用語</td>
      </tr>
      <tr>
        <td>org</td>
        <td class="mono"><a href="/def/org">/def/org</a></td>
        <td>組織・府省。法人番号を正準IDに使う</td>
      </tr>
      <tr>
        <td>all</td>
        <td class="mono"><a href="/def/all">/def/all</a></td>
        <td>全モジュールの統合(SHACL検証用)</td>
      </tr>
    </tbody>
  </table>
</body></html>
"""


def test_module_table_rows_ignores_the_header_row_and_reads_nested_tags():
    rows = site_verify.module_table_rows(_PRE_B64_FIX_TABLE_HTML)
    assert rows == [
        ["core", "/def/core", "6軸の基底クラスと、出典を表す用語"],
        ["org", "/def/org", "組織・府省。法人番号を正準IDに使う"],
        ["all", "/def/all", "全モジュールの統合(SHACL検証用)"],
    ]


def test_module_table_rows_raises_when_the_page_has_no_table():
    with pytest.raises(ValueError):
        site_verify.module_table_rows("<html><body>no table here</body></html>")


def test_module_table_rows_raises_when_the_page_has_two_tables():
    with pytest.raises(ValueError):
        site_verify.module_table_rows(_PRE_B64_FIX_TABLE_HTML + "<table><tr><td>x</td></tr></table>")


def test_module_table_problems_is_empty_for_the_current_def_index_html():
    """**空虚な検査にしない土台。** 修正済みの本物の一覧ページ

    (`templates/def-index.html`。裁定B81で`/def/`へ移した)に対しては合格すること。
    """
    html = (REAL_TEMPLATES / "def-index.html").read_text(encoding="utf-8")
    assert site_verify.module_table_problems(html, MODULES) == []


def test_module_table_problems_detects_the_actual_b64_defect_on_the_pre_fix_page():
    """**これが今回の欠陥そのもの。** 修正前のindex.html(law/budget無し)に対して、

    実際に配信されている5モジュールを期待値として渡すと落ちること。
    """
    problems = site_verify.module_table_problems(_PRE_B64_FIX_TABLE_HTML, MODULES)
    assert problems, "修正前のページに対して合格してしまっている(検査が空虚)"
    assert any("law" in p and "budget" in p for p in problems), problems


def test_module_table_problems_flags_a_stale_row_for_an_undeployed_module():
    html = _PRE_B64_FIX_TABLE_HTML  # "all" 行を含むが、期待値には"all"を入れない
    problems = site_verify.module_table_problems(html, {"core", "org"})
    assert any("all" in p for p in problems), problems


def test_module_table_problems_rejects_an_empty_description():
    html = """
    <table>
      <tr><th>モジュール</th><th>URI</th><th>内容</th></tr>
      <tr><td>core</td><td>/def/core</td><td>   </td></tr>
    </table>
    """
    problems = site_verify.module_table_problems(html, {"core"})
    assert any("core" in p and "説明文" in p for p in problems), problems


# =============================================================================
# 裁定B63/B65: run_all_checks(実際にhttpxで取得し、site/と比較する)
# =============================================================================


def test_run_all_checks_passes_when_live_exactly_mirrors_the_build(tmp_path):
    """**空虚な検査にしない土台。** 配信物がビルド成果物と完全に一致していれば全項目合格する。"""
    _full_build(tmp_path)
    live = tmp_path.parent / (tmp_path.name + "-live")
    shutil.copytree(tmp_path, live)

    client = _client(live)
    report = site_verify.run_all_checks("https://jgkg.norr-tech.com", tmp_path, GENERATED, client)
    assert report.ok, [f"{r.label}: {r.detail}" for r in report.failures]
    assert len(report.results) > 20, "検査項目が少なすぎる(空虚な合格の疑い)"


def test_run_all_checks_fails_when_a_single_byte_of_a_def_file_differs(tmp_path):
    """**配信内容が1バイト違うだけで落ちること。**

    末尾に改行を1つ追加するだけにする(構文は壊さない)——欠陥のあるバイトが
    Turtleの構文も一緒に壊すと、パース失敗やIRI適合検査など**他の検査が
    偶然検出してしまい**、sha256比較そのものが効いているのかが確認できない
    (実際にbyte[0]を反転させて試したところ、`@prefix`の先頭バイトが壊れて
    パース失敗経由で検出され、この検査の意図が確認できなかった)。
    """
    _full_build(tmp_path)
    live = tmp_path.parent / (tmp_path.name + "-live")
    shutil.copytree(tmp_path, live)

    target = live / "def" / "core.owl.ttl"
    corrupted = target.read_bytes() + b"\n"
    target.write_bytes(corrupted)
    (live / "def" / "core").write_bytes(corrupted)  # エイリアスも同じ内容にする(拡張子無し版)

    client = _client(live)
    report = site_verify.run_all_checks("https://jgkg.norr-tech.com", tmp_path, GENERATED, client)
    assert not report.ok
    byte_compare_failures = [r for r in report.failures if "同一バイト列" in r.label]
    assert any("/def/core.owl.ttl" in r.label for r in byte_compare_failures), [r.label for r in report.failures]
    # 末尾に改行を足しただけなので、構文は壊れていない——他の検査(パース可否・
    # IRI適合等)まで巻き込んで落ちていないことも確認する(この検査が
    # 単独で効いていることの証明)
    assert len(report.failures) == len(byte_compare_failures), [r.label for r in report.failures]


def test_run_all_checks_does_not_hash_compare_html_even_when_cloudflare_injects_a_script(tmp_path):
    """**裁定B65の核心。** HTMLにCloudflareのボット検出スクリプトが挿入されて

    ディスクの内容とバイト単位で食い違っていても、モジュール表の構造が
    正しければ合格すること(=HTMLはハッシュ比較の対象になっていない)。
    ハッシュ比較する実装に戻すと、この挿入で必ず落ちる。
    """
    _full_build(tmp_path)
    live = tmp_path.parent / (tmp_path.name + "-live")
    shutil.copytree(tmp_path, live)

    original = (live / "def" / "index.html").read_text(encoding="utf-8")
    injected = original.replace(
        "</body>",
        '<script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script></body>',
    )
    assert injected != original
    (live / "def" / "index.html").write_text(injected, encoding="utf-8")

    client = _client(live)
    report = site_verify.run_all_checks("https://jgkg.norr-tech.com", tmp_path, GENERATED, client)
    assert report.ok, [f"{r.label}: {r.detail}" for r in report.failures]


def test_run_all_checks_detects_a_module_missing_from_the_live_def_index_html(tmp_path):
    """裁定B64の再発防止を`run_all_checks`レベルでも確認する。"""
    _full_build(tmp_path)
    live = tmp_path.parent / (tmp_path.name + "-live")
    shutil.copytree(tmp_path, live)
    (live / "def" / "index.html").write_text(_PRE_B64_FIX_TABLE_HTML, encoding="utf-8")

    client = _client(live)
    report = site_verify.run_all_checks("https://jgkg.norr-tech.com", tmp_path, GENERATED, client)
    assert not report.ok
    assert any("モジュール表" in r.label for r in report.failures), [r.label for r in report.failures]


# =============================================================================
# 裁定B81: アプリ(`/`)の資産の陳腐化検出(HTMLハッシュ比較の代わり)
# =============================================================================


def test_referenced_app_asset_urls_finds_script_src_and_link_href():
    urls = site_verify.referenced_app_asset_urls(_FAKE_APP_INDEX_HTML)
    assert urls == {"/assets/index-fakehash123.js", "/assets/index-fakehash456.css"}


def test_stale_app_asset_urls_is_empty_when_every_reference_exists(tmp_path):
    _full_build(tmp_path)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    served = site_verify.served_files(tmp_path)
    assert site_verify.stale_app_asset_urls(html, served) == set()


def test_stale_app_asset_urls_flags_a_hash_the_current_build_no_longer_has(tmp_path):
    """**アプリの陳腐化検出の核心。** 本番HTMLが指すハッシュ付きファイルが、

    いま手元で作った最新ビルドには存在しない(=新しいデプロイでハッシュが
    変わったのに、本番のHTMLだけ古いハッシュを参照し続けている)状態を
    検出できること。
    """
    _full_build(tmp_path)
    served = site_verify.served_files(tmp_path)
    stale_html = _FAKE_APP_INDEX_HTML.replace("index-fakehash123.js", "index-oldhash999.js")
    stale = site_verify.stale_app_asset_urls(stale_html, served)
    assert stale == {"/assets/index-oldhash999.js"}


def test_run_all_checks_detects_a_stale_app_deploy(tmp_path):
    """`run_all_checks`レベルでも、本番の`/`が古いハッシュを参照していれば落ちること

    (裁定B81「アプリの陳腐化検出」がverify-site.py経由で実際に効くことの確認)。
    """
    _full_build(tmp_path)
    live = tmp_path.parent / (tmp_path.name + "-live")
    shutil.copytree(tmp_path, live)
    stale_html = _FAKE_APP_INDEX_HTML.replace("index-fakehash123.js", "index-oldhash999.js")
    (live / "index.html").write_text(stale_html, encoding="utf-8")

    client = _client(live)
    report = site_verify.run_all_checks("https://jgkg.norr-tech.com", tmp_path, GENERATED, client)
    assert not report.ok
    assert any("陳腐化検出" in r.label and "index-oldhash999.js" in r.detail for r in report.failures), [
        f"{r.label}: {r.detail}" for r in report.failures
    ]


# =============================================================================
# リトライ(裁定B63: 配信伝播待ちの偽陽性を吸収するが、最終的には落ちる)
# =============================================================================


def test_run_all_checks_with_retries_absorbs_a_transient_mismatch(tmp_path):
    """1回目は不一致でも、2回目までに直っていれば合格し、実際にsleepが呼ばれたこと。"""
    _full_build(tmp_path)
    live = tmp_path.parent / (tmp_path.name + "-live")
    shutil.copytree(tmp_path, live)

    target = live / "def" / "core.owl.ttl"
    good = target.read_bytes()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/def/core.owl.ttl":
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(200, content=b"stale", headers={"content-type": "text/turtle"})
        local = _local_path_for(live, path)
        if not local.is_file():
            return httpx.Response(404, content=b"not found")
        headers = {"content-type": _content_type_for(path)}
        if path.startswith("/def/"):
            headers["access-control-allow-origin"] = "*"
        return httpx.Response(200, content=local.read_bytes(), headers=headers)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    report = site_verify.run_all_checks_with_retries(
        "https://jgkg.norr-tech.com", tmp_path, GENERATED, client,
        attempts=3, delay_seconds=10.0, sleep=sleeps.append,
    )
    assert report.ok, [f"{r.label}: {r.detail}" for r in report.failures]
    assert sleeps, "リトライが実際に発生していない(初回で偶然合格した可能性)"
    assert good == target.read_bytes(), "前提: ローカル側は変更していない"


def test_run_all_checks_with_retries_gives_up_after_the_last_attempt(tmp_path):
    """常に不一致を返すスタブに対しては、指定回数リトライした上で最終的に落ちること。"""
    _full_build(tmp_path)
    live = tmp_path.parent / (tmp_path.name + "-live")
    shutil.copytree(tmp_path, live)
    (live / "def" / "core.owl.ttl").write_bytes(b"permanently wrong")
    (live / "def" / "core").write_bytes(b"permanently wrong")

    client = _client(live)
    sleeps: list[float] = []
    report = site_verify.run_all_checks_with_retries(
        "https://jgkg.norr-tech.com", tmp_path, GENERATED, client,
        attempts=3, delay_seconds=10.0, sleep=sleeps.append,
    )
    assert not report.ok
    assert sleeps == [10.0, 10.0], f"attempts=3なら2回リトライするはず: {sleeps}"
    assert any("/def/core.owl.ttl" in r.label for r in report.failures), [r.label for r in report.failures]


def test_run_all_checks_with_retries_defaults_to_a_single_attempt(tmp_path):
    """既定(`attempts`省略)ではリトライしないこと(ローカル実行を遅くしないため)。"""
    _full_build(tmp_path)
    live = tmp_path.parent / (tmp_path.name + "-live")
    shutil.copytree(tmp_path, live)
    (live / "def" / "core.owl.ttl").write_bytes(b"wrong")
    (live / "def" / "core").write_bytes(b"wrong")

    client = _client(live)
    calls: list[float] = []
    report = site_verify.run_all_checks_with_retries(
        "https://jgkg.norr-tech.com", tmp_path, GENERATED, client, sleep=calls.append
    )
    assert not report.ok
    assert calls == [], "既定でリトライしてしまっている"


def _asset_byte_failure(report):
    """資産のsha256比較の失敗を1件返す(無ければAssertionError)。"""
    hits = [
        r
        for r in report.failures
        if "同一バイト列" in r.label and "/assets/" in r.label
    ]
    assert len(hits) == 1, [f"{r.label}: {r.detail}" for r in report.failures]
    return hits[0]


def test_byte_mismatch_says_whether_the_body_was_an_html_fallback(tmp_path):
    """**sha256不一致が「HTMLフォールバックか否か」を言うこと(裁定B84)。**

    2026-09-02、配信直後の本番検査で `/assets/index-*.js` の不一致だけが
    6回連続で報告されたが、詳細は `status=200 live_sha256=… local_sha256=…`
    しか無く、**「反映が終わっていない(欠落パスにHTMLが200で返る)」のか
    「配備されたバイト列が本当に違う」のかを切り分けられなかった。**
    前者は待てば消え、後者は待っても消えない——対処が正反対である。

    Cloudflare Pages は欠落パスに index.html を 200 で返し、`_headers` の
    Content-Type を被せるので、**ヘッダでは判定できない**(裁定B63の実測)。
    だから本文で判定する。
    """
    _full_build(tmp_path)
    live = tmp_path.parent / (tmp_path.name + "-live")
    shutil.copytree(tmp_path, live)

    # 欠落パスへのHTMLフォールバックを再現する(本文をindex.htmlにする)。
    # 配信元にも実物が無い状態なので、キャッシュを迂回しても一致しない。
    (live / "assets" / "index-fakehash123.js").write_text(
        _FAKE_APP_INDEX_HTML, encoding="utf-8"
    )

    client = _client(live)
    report = site_verify.run_all_checks("https://jgkg.norr-tech.com", tmp_path, GENERATED, client)
    assert not report.ok
    failure = _asset_byte_failure(report)
    assert "本文がHTML" in failure.detail, failure.detail
    assert "キャッシュを迂回しても一致しない" in failure.detail, failure.detail
    assert "配備が伝播していない、または配信漏れ" in failure.detail, failure.detail
    # 生のsha256も落とさずに残っていること(診断に両方必要)
    assert "live_sha256=" in failure.detail and "local_sha256=" in failure.detail, failure.detail


def test_byte_mismatch_distinguishes_a_stale_cdn_cache_from_a_missing_deploy(tmp_path):
    """**配信元は正しいのにCDNが古いフォールバックを持っている場合を見分けること
    (裁定B85)。**

    2026-09-02に実際に起きた形: 配備が伝播する前にあるPoPが資産パスを要求し、
    Cloudflareが**200 + HTML**を返した。`_headers` の
    `/assets/* Cache-Control: max-age=31536000, immutable` がそのHTMLにも
    付いたため、**そのPoPは1年間その古いHTMLを資産として返し続けた**
    (CI実行2回・20分離れて同一sha256。別PoPからは正しいJSが返った)。

    **この状態は「待てば消える」ものではない** ——
    「伝播していない」と同じ文言で報告してはならない。対処が違う
    (内容ハッシュを変える、またはCDNのキャッシュを消す)。
    """
    _full_build(tmp_path)
    live = tmp_path.parent / (tmp_path.name + "-live")
    shutil.copytree(tmp_path, live)

    # 配信元(live)は正しいまま。キャッシュだけが古いHTMLを返す
    client = _client(
        live,
        stale_cache={"/assets/index-fakehash123.js": _FAKE_APP_INDEX_HTML.encode("utf-8")},
    )
    report = site_verify.run_all_checks("https://jgkg.norr-tech.com", tmp_path, GENERATED, client)
    assert not report.ok, "CDNが壊れた資産を配っているのに合格させてはならない"
    failure = _asset_byte_failure(report)
    assert "配信元には正しいバイト列がある" in failure.detail, failure.detail
    assert "CDNが古いフォールバックを保持している" in failure.detail, failure.detail
    assert "待っても直らない" in failure.detail, failure.detail
    # **「伝播していない」側の文言と混ざっていないこと**(混ざれば切り分けにならない)
    assert "キャッシュを迂回しても一致しない" not in failure.detail, failure.detail
    assert "配備が伝播していない、または配信漏れ" not in failure.detail, failure.detail


def test_byte_mismatch_says_the_bytes_really_differ_when_the_body_is_not_html(tmp_path):
    """**HTMLでない不一致は「実際に違う」と言うこと(裁定B84)。**

    こちらは待っても消えない種類なので、`本文がHTML` と**同じ文言にしては
    いけない**——同じなら切り分けの役に立たない。
    """
    _full_build(tmp_path)
    live = tmp_path.parent / (tmp_path.name + "-live")
    shutil.copytree(tmp_path, live)

    # 構文もHTMLでもない、ただ違うバイト列にする
    (live / "assets" / "index-fakehash123.js").write_text(
        "console.log('別のビルド')", encoding="utf-8"
    )

    client = _client(live)
    report = site_verify.run_all_checks("https://jgkg.norr-tech.com", tmp_path, GENERATED, client)
    assert not report.ok
    failure = _asset_byte_failure(report)
    assert "本文はHTMLではない" in failure.detail, failure.detail
    assert "本文がHTML(" not in failure.detail, failure.detail


def test_byte_match_detail_stays_quiet(tmp_path):
    """一致しているときは診断文を足さないこと(OK行を騒がしくしない)。"""
    _full_build(tmp_path)
    live = tmp_path.parent / (tmp_path.name + "-live")
    shutil.copytree(tmp_path, live)

    client = _client(live)
    report = site_verify.run_all_checks("https://jgkg.norr-tech.com", tmp_path, GENERATED, client)
    assert report.ok, [f"{r.label}: {r.detail}" for r in report.failures]
    asset_checks = [
        r for r in report.results if "同一バイト列" in r.label and "/assets/" in r.label
    ]
    assert len(asset_checks) == 2, [r.label for r in asset_checks]
    for r in asset_checks:
        assert r.detail.startswith("sha256="), r.detail
        assert "本文" not in r.detail, r.detail


# =============================================================================
# 配備の伝播待ち(裁定B107): **検証が自分でキャッシュを汚さないこと**
# =============================================================================

_FALLBACK_HTML = b'<!doctype html><html><head><title>JGKG</title></head><body>fallback</body></html>'


def _self_poisoning_transport(live_dir: Path, state: dict, missing_status: int = 404):
    """本番で起きたことを模擬する配信元。

    Cloudflare Pages は存在しないパスに `index.html` を **200 text/html** で
    返し(実測 2026-08-23)、Cloudflare はその応答を**実利用者と同じ
    キャッシュキー**に保存する(実測 2026-09-12。裁定B107)。

    - `state["live"]` が偽のあいだ、配信元はどのパスにもフォールバックHTMLを返す
    - **クエリ文字列が無い取得**の応答は `state["cache"]` に焼き付き、
      以後 `live` が真になっても**そのパスは古い応答を返し続ける**
    - クエリ文字列付きの取得はキャッシュキーが別なので、常に配信元の
      いまの状態を返す
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        bare = not request.url.query
        if bare and path in state["cache"]:
            body = state["cache"][path]
        status = 200
        if bare and path in state["cache"]:
            body, status = state["cache"][path]
        else:
            local = _local_path_for(live_dir, path)
            if state["live"] and local.is_file():
                body = local.read_bytes()
            else:
                # **未知パス(または伝播前)の挙動は引数で切り替える。**
                # 裁定B113で `404.html` を置くまでは「200 + アプリのHTML」
                # だった(それがキャッシュ汚染の前提)。置いた後は404になる。
                body = _FALLBACK_HTML
                status = missing_status
            if bare:
                state["cache"][path] = (body, status)
        state["asked"].append(str(request.url))
        headers = {"content-type": _content_type_for(path)}
        if path.startswith("/def/"):
            headers["access-control-allow-origin"] = "*"
        return httpx.Response(status, content=body, headers=headers)

    return httpx.MockTransport(handler)


def _poisoning_setup(tmp_path: Path, missing_status: int = 404):
    """配信元(`live_dir`)・可変状態・そこに繋がるクライアントを用意する。

    戻すのは state と client だけ——`live_dir`はクライアント越しにしか
    触らないので、呼び出し側に渡すと使われない変数になる。
    """
    _full_build(tmp_path)
    live_dir = tmp_path.parent / (tmp_path.name + "-live")
    shutil.copytree(tmp_path, live_dir)
    state: dict = {"live": False, "cache": {}, "asked": []}
    return state, httpx.Client(
        transport=_self_poisoning_transport(live_dir, state, missing_status)
    )


def test_the_wait_never_requests_a_bare_url(tmp_path):
    """**待ち合わせの取得は必ずクエリ文字列を付ける。**

    素のURLで取ると、伝播前の応答が実利用者と同じキャッシュキーに焼き付く。
    """
    state, client = _poisoning_setup(tmp_path)
    site_verify.wait_until_deployment_is_live(
        client, "https://jgkg.norr-tech.com", tmp_path, attempts=1,
    )
    assert state["asked"], "前提: 取得が行われている"
    bare = [u for u in state["asked"] if "?" not in u]
    assert bare == [], bare
    assert state["cache"] == {}, "素の取得をしていないのだからキャッシュは空"


def test_the_wait_uses_a_different_nonce_each_attempt(tmp_path):
    """迂回用URL自身がキャッシュされても次の試行に影響しないこと。"""
    state, client = _poisoning_setup(tmp_path)
    site_verify.wait_until_deployment_is_live(
        client, "https://jgkg.norr-tech.com", tmp_path,
        attempts=3, delay_seconds=0, sleep=lambda _s: None,
    )
    queries = {u.split("?", 1)[1] for u in state["asked"]}
    assert len(queries) == 3, queries


def test_the_wait_becomes_live_when_the_deployment_propagates(tmp_path):
    """伝播が終われば合格し、何回目で確かめられたかを返すこと。"""
    state, client = _poisoning_setup(tmp_path)

    def propagate(_seconds: float) -> None:
        state["live"] = True

    wait = site_verify.wait_until_deployment_is_live(
        client, "https://jgkg.norr-tech.com", tmp_path,
        attempts=5, delay_seconds=0, sleep=propagate,
    )
    assert wait.live
    assert wait.attempts_used == 2
    assert wait.mismatched == ()


def test_the_wait_reports_the_paths_that_do_not_match(tmp_path):
    """伝播しないまま試行を使い切ったら、一致しなかったパスを返すこと。"""
    _state, client = _poisoning_setup(tmp_path)
    wait = site_verify.wait_until_deployment_is_live(
        client, "https://jgkg.norr-tech.com", tmp_path,
        attempts=2, delay_seconds=0, sleep=lambda _s: None,
    )
    assert not wait.live
    assert wait.attempts_used == 2
    assert "/assets/index-fakehash123.js" in wait.mismatched
    assert all(not site_verify.is_html_path(p) for p in wait.mismatched)


def test_the_wait_lets_the_real_checks_pass_after_propagation(tmp_path):
    """**先に待てば、検査は通る。** 裁定B107の対処が効くことの確認。"""
    state, client = _poisoning_setup(tmp_path)

    def propagate(_seconds: float) -> None:
        state["live"] = True

    wait = site_verify.wait_until_deployment_is_live(
        client, "https://jgkg.norr-tech.com", tmp_path,
        attempts=5, delay_seconds=0, sleep=propagate,
    )
    assert wait.live
    report = site_verify.run_all_checks("https://jgkg.norr-tech.com", tmp_path, GENERATED, client)
    assert report.ok, [f"{r.label}: {r.detail}" for r in report.failures]


def test_fetching_before_propagation_poisons_the_cache_permanently(tmp_path):
    """**待たずに素の取得をすると、伝播が終わっても永久に一致しない。**

    2026-09-12に本番で起きたことそのもの(CI実行 34707640573): 配信直後の
    1回目が「200 + HTML」を受け取り、以後10回・5分間同じsha256を返し続けた。
    **窓を広げる対処が効かない**ことを、この検査が固定する。
    """
    # **旧挙動(未知パスに200 + HTML)を明示して模す。** これが汚染の前提で
    # あり、裁定B113で `404.html` を置いて構造的に消した ——
    # このテストは「なぜその対処が要ったか」を記録として残す。
    state, client = _poisoning_setup(tmp_path, missing_status=200)

    # 伝播前に素の取得をしてしまう(裁定B84までのCIの振る舞い)。
    first = site_verify.run_all_checks("https://jgkg.norr-tech.com", tmp_path, GENERATED, client)
    assert not first.ok

    # 配備は届いた。それでも素のURLは古いHTMLを返し続ける。
    state["live"] = True
    after = site_verify.run_all_checks("https://jgkg.norr-tech.com", tmp_path, GENERATED, client)
    assert not after.ok, "待てば直る、という想定が誤りであることの確認"
    # 2本の資産(js/css)がどちらも焼き付いている。診断文は「配信元は正しい」
    # ——つまり待つのではなく、内容ハッシュを変えるかキャッシュを消すしかない。
    poisoned = [
        r for r in after.failures if "同一バイト列" in r.label and "/assets/" in r.label
    ]
    assert len(poisoned) == 2, [r.label for r in after.failures]
    for r in poisoned:
        assert "配信元には正しいバイト列がある" in r.detail, r.detail

    # 同じ状態でも、迂回した取得なら配信元の正しさが分かる。
    wait = site_verify.wait_until_deployment_is_live(
        client, "https://jgkg.norr-tech.com", tmp_path, attempts=1,
    )
    assert wait.live


def test_the_wait_refuses_to_pass_when_there_is_nothing_to_compare(tmp_path):
    """**比較対象が0件なら合格にしない。**

    空集合に対する全称命題は自明に真なので、ここを合格にすると
    「何も確かめずに配信元は正しいものを配っている」と言えてしまう
    ——`run_all_checks` が「配信物(site/)に検査対象のファイルがある」を
    最初に問うのと同じ理由。**実際に踏んだ**(2026-09-13。存在しない
    `--out-dir` を渡したら `live=True` が0.4秒で返った)。
    """
    state, client = _poisoning_setup(tmp_path)
    state["live"] = True
    empty = tmp_path.parent / (tmp_path.name + "-empty")
    empty.mkdir()

    wait = site_verify.wait_until_deployment_is_live(
        client, "https://jgkg.norr-tech.com", empty, attempts=3,
        delay_seconds=0, sleep=lambda _s: None,
    )
    assert not wait.live
    assert wait.probed == 0
    assert state["asked"] == [], "1件も取得していないこと(待つ意味が無いので即座に返る)"


def test_the_wait_reports_how_many_paths_it_compared(tmp_path):
    """「配っている」と言うときは、何件突き合わせたのかを一緒に返すこと。"""
    state, client = _poisoning_setup(tmp_path)
    state["live"] = True
    wait = site_verify.wait_until_deployment_is_live(
        client, "https://jgkg.norr-tech.com", tmp_path, attempts=1,
    )
    assert wait.live
    assert wait.probed == len(site_verify.comparable_paths(tmp_path))
    assert wait.probed > 0


# =============================================================================
# 未知パスは404で返す(裁定B113)
# =============================================================================


def test_an_unknown_asset_path_must_return_404_not_html(tmp_path):
    """**欠落した資産のURLに「200 + HTML」を返す配信を赤にする。**

    Cloudflare Pages は `404.html` が無いと未知パスに「200 + アプリの
    index.html」を返し、CDNはそれを**成功応答として**保存する。
    2026-09-02(裁定B85)・2026-09-12(裁定B107)・2026-09-13 の3回、
    `/assets/index-*.js` がHTMLを返す状態が実際に起きた。状態コードを
    404にすれば、CDNの既定TTLも短くなり、ブラウザも素直に失敗する。
    """
    _full_build(tmp_path)
    live = tmp_path.parent / (tmp_path.name + "-live")
    shutil.copytree(tmp_path, live)

    # 旧挙動(未知パスに200 + アプリのHTML)を模す配信元。
    state = {"live": True, "cache": {}, "asked": []}
    client = httpx.Client(transport=_self_poisoning_transport(live, state, missing_status=200))
    report = site_verify.run_all_checks("https://jgkg.norr-tech.com", tmp_path, GENERATED, client)

    failures = [r for r in report.failures if site_verify.NOT_FOUND_PROBE in r.label]
    assert failures, "未知パスが200でHTMLを返しても赤にならない"
    assert any("404を返す" in r.label for r in failures)


def test_an_unknown_asset_path_returning_404_passes(tmp_path):
    """404で返る配信は通ること(上の検査が常時赤にならないことの正の対照)。"""
    _full_build(tmp_path)
    live = tmp_path.parent / (tmp_path.name + "-live")
    shutil.copytree(tmp_path, live)

    client = _client(live)  # 未知パスは404 + "not found"
    report = site_verify.run_all_checks("https://jgkg.norr-tech.com", tmp_path, GENERATED, client)
    probe_results = [r for r in report.results if site_verify.NOT_FOUND_PROBE in r.label]
    assert len(probe_results) == 2, [r.label for r in probe_results]
    assert all(r.ok for r in probe_results), [f"{r.label}: {r.detail}" for r in probe_results]


def test_the_404_page_itself_is_not_required_to_return_200(tmp_path):
    """`/404.html` 自身に「200で返る」を要求しないこと。

    このファイルを直接要求したときに Cloudflare Pages が200を返すか404を
    返すかは実装依存で、どちらでも配信としては正しい。確かめたいのは
    「未知パスに対して404でこれが返る」ことだけである。
    """
    _full_build(tmp_path)
    (tmp_path / "404.html").write_text(
        "<!DOCTYPE html><html><body><p>政府による公式なデータセットではありません</p></body></html>",
        encoding="utf-8",
    )
    live = tmp_path.parent / (tmp_path.name + "-live404")
    shutil.copytree(tmp_path, live)

    client = _client(live)
    report = site_verify.run_all_checks("https://jgkg.norr-tech.com", tmp_path, GENERATED, client)
    # 404ページについて「200 + text/html」を要求する検査が作られていないこと。
    assert not [r for r in report.results if r.label.startswith("/404.html が 200")], [
        r.label for r in report.results if "/404.html" in r.label
    ]
    assert report.ok, [f"{r.label}: {r.detail}" for r in report.failures]


def test_the_unknown_path_check_bypasses_the_cdn_cache(tmp_path):
    """**未知パスの検査はキャッシュを迂回して取る**(裁定B113の訂正)。

    確かめたいのは「配信元が未知パスに何を返すか」であり、そこにCDNの
    状態を混ぜると別の話になる。実際に混ざった: この検査を入れた最初の
    配備はフロントのバンドルが変わっていなかったため、伝播待ちが新旧の
    配備を区別できず、素の探索が旧配備(404.htmlを持たない)に当たって
    200+HTMLがエッジに焼き付いた。

    ここでは「素のURLで要求されたものは古い応答を返す」配信元を使い、
    **迂回した取得で正しく404を見られること**を固定する。
    """
    _full_build(tmp_path)
    live = tmp_path.parent / (tmp_path.name + "-live")
    shutil.copytree(tmp_path, live)

    # 素のURLには「200 + アプリのHTML」を焼き付けておく(旧配備の残り)。
    state = {
        "live": True,
        "cache": {site_verify.NOT_FOUND_PROBE: (_FAKE_APP_INDEX_HTML.encode("utf-8"), 200)},
        "asked": [],
    }
    client = httpx.Client(transport=_self_poisoning_transport(live, state))
    report = site_verify.run_all_checks("https://jgkg.norr-tech.com", tmp_path, GENERATED, client)

    probe_results = [r for r in report.results if site_verify.NOT_FOUND_PROBE in r.label]
    assert len(probe_results) == 2, [r.label for r in probe_results]
    assert all(r.ok for r in probe_results), [f"{r.label}: {r.detail}" for r in probe_results]
    # 迂回した取得(クエリ文字列付き)を使ったことを、要求のURLで確かめる。
    probe_requests = [u for u in state["asked"] if site_verify.NOT_FOUND_PROBE in u]
    assert probe_requests, "探索そのものが行われていない"
    assert all("?" in u for u in probe_requests), probe_requests
