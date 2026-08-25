"""ベースURIの整合検査そのものをテストする。

設計書§4.2は「ドメイン確定時の差し替えは設定1箇所のみで完結させ、それ以外の場所に
ドメイン文字列を書かない(CIで検出する)」と書いているが、**事実として成立していない**
(YAML/オーバーレイ/CQクエリ/生成物にドメインが焼き込まれる)。成立していない要件を
検査するふりをするより、「焼き込まれることを認めて、ずれたら落ちる」形に変えた。

このファイル自身が検査対象なので、別ドメインのIRIを**文字列リテラルとして書かない**
(書くと `test_base_uri_is_consistent_across_every_target_file` が自分自身を検出して
落ちる)。ベース部分だけを定数にして f-string で組み立てる。
"""
from pathlib import Path

import pytest

from jgkg import base_uri

# **`Path.cwd()` にしてはならない。** リポジトリ直下以外から pytest を起動すると
# glob が何も見つけず、`find_inconsistencies` が空を返して
# `test_base_uri_is_consistent_across_every_target_file` が**1ファイルも見ずに合格する**
# (このプロジェクトが最も警戒している「対象0件で合格」そのものになる)。
# テストファイルの位置から解決すれば、どこから起動しても同じ範囲を見る。
# `base_uri.find_inconsistencies` / `main()` 側の `Path.cwd()` はCLIとして正しい。
ROOT = Path(__file__).resolve().parents[1]

# 検査用のダミー。ホストは RFC 6761 の予約名で、単体では §4.2 のパス構造を持たない
OLD = "http://example.test/old-kg"
UNREGISTERED_HOST = "vocab.invalid"
NEW = "https://example.test/new-kg"


def test_base_uri_is_consistent_across_every_target_file():
    """全対象ファイルのドメインが `config.Settings.base_uri` の既定値と一致すること。

    **何があれば落ちるか**: `schema/*.yaml` / `schema/overlay/*.ttl` /
    `queries/cq/*.rq` / `src/**.py` / `tests/*.py` / `scripts/*.py` /
    `.env.example` / **`schema/generated/**`** のどれかに、既定のベースURIの配下でも
    許可された外部ホストでもないIRIが1つでもあれば落ちる。
    つまり「差し替えたが再生成していない」「一部のファイルだけ直した」
    「未登録の外部語彙が混ざった」のいずれもここで止まる。
    """
    # **先に検査対象が空でないことを主張する。** 空リストに対する
    # 「不整合が無い」は無意味であり、それが「対象0件で合格」の正体である
    targets = base_uri.checked_paths(ROOT)
    assert len(targets) >= 10, f"検査対象が少なすぎる({len(targets)}件): {ROOT}"

    problems = base_uri.find_inconsistencies(ROOT)
    assert not problems, "ベースURIが一致しない箇所がある:\n" + "\n".join(
        f"  {p}" for p in problems
    )


def test_generated_files_are_actually_scanned():
    """検査対象に生成物が含まれていること。

    C1 の原因は「検査範囲が `src/**.py` だけだった」ことなので、範囲そのものを
    固定する。**何があれば落ちるか**: `GENERATED_GLOBS` から生成物を外したら落ちる。
    """
    scanned = {p.name for p in base_uri.checked_paths(ROOT)}
    for name in ("all.shacl.ttl", "all.owl.ttl", "core.yaml", "all.yaml"):
        assert name in scanned, f"{name} が検査対象に入っていない"
    assert any(n.endswith(".rq") for n in scanned), "CQクエリが検査対象に入っていない"


def test_site_static_files_are_scanned():
    """最終レビュー要修正6(裁定)。`site/robots.txt`が検査対象に入っていること。

    `site/robots.txt:8`がドメインを直書きしていたが、`SOURCE_GLOBS`が
    `site/**`を含んでいなかったため、`--check`は緑のまま配信物が旧ドメインの
    sitemapを指し続ける穴があった(ドメイン移行の場面で発覚する)。

    何があれば落ちるか: `SOURCE_GLOBS`から`"site/*"`を外すと、
    `checked_paths(ROOT)`に`robots.txt`が現れなくなり落ちる。
    """
    scanned = {p.name for p in base_uri.checked_paths(ROOT)}
    assert "robots.txt" in scanned, "site/robots.txt が検査対象に入っていない"


def test_check_detects_a_stale_domain_even_on_an_allowed_host(tmp_path):
    """許可済みホスト上に古いベースURIが残っていても検出できること。

    ホストの許可リストだけでは、ベースURIのホストが出典URLと同じ場合に
    古いドメインが素通りする。§4.2 のパス構造(/def/ /id/ /graph/)を持つIRIは
    ホストに関係なくベースURIの配下でなければならない、という条件で捕まえる。
    """
    (tmp_path / "queries" / "cq").mkdir(parents=True)
    (tmp_path / "schema").mkdir()
    (tmp_path / "schema" / "core.yaml").write_text(
        f"id: {NEW}/def/core\n", encoding="utf-8"
    )
    (tmp_path / "queries" / "cq" / "p0-99.rq").write_text(
        f"PREFIX core: <{OLD}/def/core#>\n", encoding="utf-8"
    )

    problems = base_uri.find_inconsistencies(tmp_path, base_uri=NEW)
    assert len(problems) == 1, [str(p) for p in problems]
    assert problems[0].path == Path("queries/cq/p0-99.rq")
    assert "old-kg" in problems[0].iri


def test_check_detects_an_unregistered_external_host(tmp_path):
    """未登録の外部ホストが混ざったら検出すること(許可リスト方式)。"""
    (tmp_path / "schema").mkdir()
    (tmp_path / "schema" / "core.yaml").write_text(
        f"prefixes:\n  weird: http://{UNREGISTERED_HOST}/ns#\n", encoding="utf-8"
    )
    problems = base_uri.find_inconsistencies(tmp_path, base_uri=NEW)
    assert len(problems) == 1, [str(p) for p in problems]
    assert UNREGISTERED_HOST in problems[0].iri


def test_iri_extraction_stops_before_a_fullwidth_closing_paren(tmp_path):
    """全角の閉じ括弧`）`がURLの一部として誤って取り込まれないこと。

    B-1で実際に踏んだ欠陥: `sources.py`の出典記載(`citation`)に、政府サイト
    自身の出典記載例と同じ書式「（URL）」を採ったところ、`_IRI_RE`が半角の
    閉じ括弧`)`しか除外しておらず、全角`）`がホスト名の一部として誤って
    取り込まれた。結果、既に許可済みのホスト(github.com)が
    「未登録の外部ホスト(host='github.com）')」として誤検出された。
    """
    (tmp_path / "schema").mkdir()
    # パスを持たない**裸のホスト**であることが再現の条件(実際のsources.pyの
    # 欠陥も裸ホスト`https://rssystem.go.jp）`だった)。パスがあると
    # `urlparse`がその全角括弧をpath側に落とすため、netloc自体は汚染されず
    # 再現しない
    (tmp_path / "schema" / "core.yaml").write_text(
        "note: 出典：GitHub（https://github.com）\n",
        encoding="utf-8",
    )
    problems = base_uri.find_inconsistencies(tmp_path, base_uri=NEW)
    assert problems == [], [str(p) for p in problems]


def test_rewrite_replaces_every_occurrence(tmp_path):
    """差し替えが1コマンドで完結すること(取りこぼしが無いこと)。"""
    (tmp_path / "schema" / "overlay").mkdir(parents=True)
    (tmp_path / "queries" / "cq").mkdir(parents=True)
    (tmp_path / "schema" / "core.yaml").write_text(
        f"id: {OLD}/def/core\nprefixes:\n  jgkgcore: {OLD}/def/core#\n", encoding="utf-8"
    )
    (tmp_path / "schema" / "overlay" / "axioms.ttl").write_text(
        f"@prefix core: <{OLD}/def/core#> .\n", encoding="utf-8"
    )
    (tmp_path / "queries" / "cq" / "p0-99.rq").write_text(
        f"PREFIX core: <{OLD}/def/core#>\n", encoding="utf-8"
    )
    (tmp_path / ".env.example").write_text(f"JGKG_BASE_URI={OLD}\n", encoding="utf-8")

    changed = base_uri.rewrite(tmp_path, NEW, old_base_uri=OLD)
    assert len(changed) == 4, [str(p) for p in changed]
    assert not base_uri.find_inconsistencies(tmp_path, base_uri=NEW)


def test_rewrite_replaces_the_domain_in_site_robots_txt(tmp_path):
    """最終レビュー要修正6。ドメイン移行の`rewrite()`が`site/robots.txt`も

    書き換えること(裁定)。

    何があれば落ちるか: `SOURCE_GLOBS`から`"site/*"`を外すと、
    `rewrite()`が`site/robots.txt`を対象にせず、`changed`にこのファイルが
    含まれなくなる。ファイルの中身も古いドメインのまま残り、
    `find_inconsistencies`が(`site/*`が検査対象からも外れているため)
    それを検出できないまま`--check`が緑になる——`site/robots.txt`が
    もう保有していないドメインのsitemapを指し続けるのに気づけない。
    """
    (tmp_path / "site").mkdir()
    robots = tmp_path / "site" / "robots.txt"
    robots.write_text(
        f"User-agent: *\nAllow: /\nSitemap: {OLD}/sitemap.txt\n", encoding="utf-8"
    )

    changed = base_uri.rewrite(tmp_path, NEW, old_base_uri=OLD)

    assert robots in changed, [str(p) for p in changed]
    assert OLD not in robots.read_text(encoding="utf-8")
    assert f"{NEW}/sitemap.txt" in robots.read_text(encoding="utf-8")


def test_rewrite_preserves_crlf(tmp_path):
    """改行コードを書き換えないこと。

    生成物の再現性はGitの改行設定に依存させない(.gitattributes と同じ趣旨)。
    `read_text`/`write_text` を使うと CRLF が LF に潰れる。
    """
    (tmp_path / "schema").mkdir()
    target = tmp_path / "schema" / "core.yaml"
    target.write_bytes(f"id: {OLD}/def/core\r\nname: x\r\n".encode())

    base_uri.rewrite(tmp_path, NEW, old_base_uri=OLD)
    assert target.read_bytes() == f"id: {NEW}/def/core\r\nname: x\r\n".encode()


def test_rewrite_rejects_empty_base_uri(tmp_path):
    with pytest.raises(ValueError, match="空"):
        base_uri.rewrite(tmp_path, "", old_base_uri=OLD)
