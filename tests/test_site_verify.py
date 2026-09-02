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
