"""静的配信物の整合テスト。

**このテストが守るのは「生成物が解決を要求しているURLが、配信物に必ず存在する」こと。**
要求されるパスは生成物から導出する(ハードコードしない)。モジュールを増やしたときに
検査対象から黙って抜け落ちる、という型がこのプロジェクトで3回起きているため。
"""
from pathlib import Path

import pytest

from jgkg import site
from jgkg.config import get_settings

GENERATED = Path(__file__).resolve().parent.parent / "schema" / "generated"


@pytest.fixture(autouse=True)
def _fixed_base(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "https://jgkg.norr-tech.com")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_required_paths_is_not_empty():
    """空集合に対する検査は常に通る(空振り)。まず対象があることを主張する。"""
    required = site.required_paths(GENERATED)
    assert len(required) >= 5, f"導出できたパスが少なすぎる: {sorted(required)}"
    # モジュール名だけのIRIと、ファイル名付きのIRIの両方が現れるはず
    assert any(p.endswith(".owl.ttl") for p in required), sorted(required)
    assert any(not p.endswith(".ttl") for p in required), sorted(required)


def test_build_covers_every_required_path(tmp_path):
    made = site.build(GENERATED, tmp_path)
    assert made, "配信物が1件も作られていない"
    missing = site.missing_paths(GENERATED, tmp_path)
    assert missing == set(), f"生成物が要求しているのに配信物に無い: {sorted(missing)}"


def test_missing_path_is_detected(tmp_path):
    """**この検査は何があれば落ちるか。** 1つ消したら検出できることを確かめる。"""
    site.build(GENERATED, tmp_path)
    required = sorted(site.required_paths(GENERATED))
    victim = tmp_path / required[0].lstrip("/")
    victim.unlink()
    missing = site.missing_paths(GENERATED, tmp_path)
    assert required[0] in missing, "ファイルを消しても検出されない(検査が空振りしている)"


def test_served_files_use_the_configured_base_uri(tmp_path):
    """配信物の中身が別のドメインを名乗っていたら公開してはならない。"""
    site.build(GENERATED, tmp_path)
    base = get_settings().base_uri.rstrip("/")
    core = (tmp_path / "def" / "core.owl.ttl").read_text(encoding="utf-8")
    assert base in core, f"配信物に {base} が現れない"
    assert "localhost" not in core, "開発用のドメインが配信物に残っている"


# =============================================================================
# 最終レビュー要修正1/要修正2(裁定B40): module_names()の導出、
# _headersの手書きワイルドカードを構造的な生成に置き換える
# =============================================================================


def test_module_names_derives_all_five_phase1_modules():
    """`module_names()`が`*.owl.ttl`から5モジュール全部を導出すること。

    何があれば落ちるか: `scripts/verify-site.py`が以前手書きしていた
    `("core", "org", "all")`のように固定の一覧に戻すと、`law`/`budget`が
    抜けたままこのテストが落ちる(実際に起きた欠陥そのもの)。
    """
    assert set(site.module_names(GENERATED)) == {"core", "org", "law", "budget", "all"}


def test_build_and_module_names_agree_on_the_module_alias_paths(tmp_path):
    """`build()`が実際に作るモジュールエイリアスのパスの集合が、

    `module_names()`が返す集合と完全に一致すること(要修正2の「二度と
    乖離できない形」——両者が同じ関数を呼んでいるため、原理的に一致する
    はずだが、それをここで実際に確認する)。
    """
    made = site.build(GENERATED, tmp_path)
    # モジュールエイリアス(`/def/core`)は最後のパス片に拡張子が無い
    # (`.ttl`ファイルのコピー`/def/core.owl.ttl`等と区別する)
    alias_paths = {
        p for p in made if p.startswith("/def/") and "." not in p.rsplit("/", 1)[-1]
    }
    assert alias_paths == {f"/def/{m}" for m in site.module_names(GENERATED)}


def test_build_headers_gives_each_made_path_its_own_block_not_a_wildcard(tmp_path):
    """`_headers`が`/def/*`のようなワイルドカードを含まず、

    `made`にある各パスへ個別のブロックを与えること(要修正1)。

    何があれば落ちるか: 生成ロジックが以前のワイルドカード
    (`/def/*\\n  Content-Type: ...`)に戻ると、このテストの
    `"/def/*" not in content`が落ちる。
    """
    made = site.build(GENERATED, tmp_path)
    content = site.build_headers(made)

    assert "/def/*" not in content, "ワイルドカードのブロックが残っている"
    for path in made:
        if path == "/sitemap.txt":
            continue
        assert f"{path}\n" in content, f"{path} 用のブロックが無い: {content!r}"
    assert "Content-Type: text/turtle; charset=utf-8" in content
    assert "Access-Control-Allow-Origin: *" in content
    # 共通ブロック(全パス向け。ワイルドカードだがContent-Typeを含まないので安全)
    assert "/*\n  X-Content-Type-Options: nosniff" in content


def test_build_headers_gives_no_block_to_a_path_that_was_never_made():
    """`made`に含まれないパスには、`_headers`に一致するブロックが無いこと

    (要修正1の核心——欠落したパスがturtleを名乗れないことの直接証明)。

    何があれば落ちるか: 個別パスのブロックではなく`/def/*`的な
    ワイルドカードに戻すと、実在しない`/def/law`のようなパスも
    (作られていないのに)このブロックにマッチしてしまい、このテストの
    `"/def/law" not in content`が落ちる。
    """
    content = site.build_headers({"/def/core", "/def/core.owl.ttl"})
    assert "/def/law" not in content
    assert "/def/core\n" in content


def test_write_headers_writes_the_file_to_out_dir(tmp_path):
    made = site.build(GENERATED, tmp_path)
    path = site.write_headers(made, tmp_path)
    assert path == tmp_path / "_headers"
    assert path.read_text(encoding="utf-8") == site.build_headers(made)


# =============================================================================
# 最終レビュー⚠️B/⚠️C: verify-site.pyの手書きの乗数(`len(MODULES) * 3`)と
# build_headers()の手書きの除外リスト(`!= "/sitemap.txt"`)を導出に置き換える
# =============================================================================


def test_build_headers_gives_no_turtle_block_to_a_non_def_path():
    """`/def/`で始まらないパス(`/robots.txt`等)には、turtleのブロックを

    与えないこと(最終レビュー⚠️C。要修正1の除外リストを`!= "/sitemap.txt"`
    という1要素の手書きから`p.startswith("/def/")`という構造の判定に
    変えたため。以前の実装は`/sitemap.txt`以外の非`/def/`パスが増えたとき、
    除外リストへの追記漏れで誤ってturtleを名乗らせてしまう可能性があった)。
    """
    content = site.build_headers({"/def/core", "/robots.txt", "/sitemap.txt"})
    assert "/def/core\n" in content
    assert "/robots.txt\n" not in content
    assert "/sitemap.txt\n" not in content


def test_def_entry_count_agrees_with_the_actual_def_paths_build_makes(tmp_path):
    """`def_entry_count()`が主張する件数が、`build()`が実際に作る

    `/def/`配下パスの実数と一致すること(要修正2と同じ「二度と乖離できない
    形」を、この乗数にも適用する)。

    何があれば落ちるか: `build()`側にモジュールあたりの生成ファイルを
    増やす/減らす変更が入っても`def_entry_count()`側の式を更新しないと、
    この一致テストが落ちる(`scripts/verify-site.py`が黙って誤った
    期待値を持つ、という実際の欠陥の再発を防ぐ)。
    """
    made = site.build(GENERATED, tmp_path)
    actual_def_paths = len([p for p in made if p.startswith("/def/")])
    assert site.def_entry_count(GENERATED) == actual_def_paths


# =============================================================================
# A-2: `scripts/check-site-build.py` が使う観測用の関数
# (built_def_paths/headers_declared_paths/sitemap_declared_paths)。
# `build()`/`build_headers()`の内部計算を再利用せず、実際に書かれたファイル・
# テキストを読み直すだけであること(循環検証にしないための土台)を確認する。
# =============================================================================


def test_built_def_paths_matches_the_def_paths_build_actually_makes(tmp_path):
    made = site.build(GENERATED, tmp_path)
    expected = {p for p in made if p.startswith("/def/")}
    assert site.built_def_paths(tmp_path) == expected


def test_built_def_paths_is_empty_when_there_is_no_def_directory(tmp_path):
    """空虚な合格を作らない土台: ビルドされていない`out_dir`では空集合を返す

    (`_headers`/`sitemap.txt`との一致比較が「0件同士で一致」という
    見た目だけの合格にならないよう、`scripts/check-site-build.py`側で
    この空集合自体を明示的に検査する――実測: 空の`out_dir`に対して
    実行すると、`missing_paths`とこの非空検査の2件がNGになり、
    `_headers`/`sitemap`の一致検査だけは「0件同士で一致」してOKになる
    ことを確認した。全体としては失敗になるので空虚な合格にはならない)。
    """
    assert site.built_def_paths(tmp_path) == set()


def test_headers_declared_paths_matches_built_def_paths_after_a_real_build(tmp_path):
    made = site.build(GENERATED, tmp_path)
    site.write_headers(made, tmp_path)
    assert site.headers_declared_paths(tmp_path) == site.built_def_paths(tmp_path)


def test_sitemap_declared_paths_matches_built_def_paths_after_a_real_build(tmp_path):
    site.build(GENERATED, tmp_path)
    assert site.sitemap_declared_paths(tmp_path) == site.built_def_paths(tmp_path)


def test_headers_declared_paths_detects_a_stale_headers_file_with_the_real_file_untouched(tmp_path):
    """`_headers`だけが古くなった場合(実ファイルは残っている)を検出できること。

    何があれば落ちるか: `_headers`の内容を一度も読まない検査
    (`missing_paths()`のように生成物から要求パスを再計算するだけの形)では、
    この種の劣化(`_headers`だけが古い/手で欠落させた)を原理的に見逃す。
    """
    made = site.build(GENERATED, tmp_path)
    site.write_headers(made, tmp_path)
    victim = min(site.built_def_paths(tmp_path))

    headers_path = tmp_path / "_headers"
    blocks = headers_path.read_text(encoding="utf-8").split("\n\n")
    kept = [b for b in blocks if not b.startswith(f"{victim}\n")]
    headers_path.write_text("\n\n".join(kept), encoding="utf-8")

    assert victim not in site.headers_declared_paths(tmp_path)
    assert victim in site.built_def_paths(tmp_path), "実ファイルは消していないはず"


def test_sitemap_declared_paths_detects_a_stale_sitemap_with_the_real_file_untouched(tmp_path):
    """`sitemap.txt`だけが古くなった場合を検出できること

    (このセッションで実際に起きた欠陥――law/budget追加後もsitemapが9件の
    まま追従しなかった――と同じ形を、実ファイルは残したまま再現する)。
    """
    site.build(GENERATED, tmp_path)
    victim = min(site.built_def_paths(tmp_path))
    base = get_settings().base_uri.rstrip("/")

    sitemap_path = tmp_path / "sitemap.txt"
    lines = sitemap_path.read_text(encoding="utf-8").splitlines()
    kept = [line for line in lines if line != f"{base}{victim}"]
    sitemap_path.write_text("\n".join(kept) + "\n", encoding="utf-8")

    assert victim not in site.sitemap_declared_paths(tmp_path)
    assert victim in site.built_def_paths(tmp_path), "実ファイルは消していないはず"
