import hashlib
import json

import pytest

from jgkg import build

# B-2裁定: 既存の呼び出しに影響を与えないためのダミー値。
# この定数自体の値そのものは無意味(どのテストも実在のコミットである
# ことを要求しない)——git_commit/git_dirtyの記録/読込の振る舞いだけを
# 検証したいテストで使う
_DUMMY_GIT_COMMIT = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"


def test_build_manifest_records_checksum_and_jena_version(tmp_path):
    nq = tmp_path / "kg.nq"
    nq.write_text(
        '<http://example.test/s> <http://example.test/p> <http://example.test/o> <http://example.test/g> .\n', encoding="utf-8"
    )
    tarball = tmp_path / "kg.tar.gz"
    tarball.write_bytes(b"fake tarball content")

    m = build.build_manifest(
        nquads=nq,
        tarball=tarball,
        jena_version="5.0.0",
        release="2026-08-01",
        sources={"houjin-bangou": "2026-08-01"},
        graphs=["http://example.test/g"],
        tdb2_expanded_bytes=1234,
        git_commit=_DUMMY_GIT_COMMIT,
        git_dirty=False,
    )

    assert m.jena_version == "5.0.0"
    assert m.sha256 == hashlib.sha256(b"fake tarball content").hexdigest()
    assert m.byte_size == len(b"fake tarball content")
    assert m.triple_count == 1
    assert m.nquads_sha256 == hashlib.sha256(nq.read_bytes()).hexdigest(), (
        "kg.nq自体のsha256(tarballとは別物)がmanifestに記録されるべき"
        "(Ruling B26: carry-overの供給元照合に使う)"
    )
    assert m.tdb2_expanded_bytes == 1234, (
        "TDB2の展開後サイズがmanifestに記録されるべき"
        "(Task 11修正ラウンド: §6.3の8GiB判定に使う)"
    )
    assert m.graphs == ["http://example.test/g"]
    assert m.sources == {"houjin-bangou": "2026-08-01"}
    assert m.quarantined_sources == []
    assert m.git_commit == _DUMMY_GIT_COMMIT, (
        "ビルド元コミットのSHAがmanifestに記録されるべき(B-2裁定: 配布物を"
        "ダウンロードした人がそれを作ったコードを特定できるようにする)"
    )
    assert m.git_dirty is False


def test_manifest_records_quarantined_sources(tmp_path):
    """隔離されたソースが manifest に出ること。

    `sources` から外すだけでは「落ちたこと」が消える。設計書§8.2の
    「未解決を無かったことにしない」と同じ趣旨で、落ちた事実を残す。

    **何があれば落ちるか**: `quarantined_sources` を manifest に渡さなくなったら落ちる。
    """
    nq = tmp_path / "kg.nq"
    nq.write_text("", encoding="utf-8")
    tarball = tmp_path / "kg.tar.gz"
    tarball.write_bytes(b"x")

    m = build.build_manifest(
        nquads=nq,
        tarball=tarball,
        jena_version="6.2.0",
        release="2026-08-01",
        sources={"ministry-codes": "2026-08-22"},
        graphs=[],
        tdb2_expanded_bytes=1,
        quarantined_sources=["houjin-bangou"],
        git_commit=_DUMMY_GIT_COMMIT,
        git_dirty=False,
    )
    assert m.sources == {"ministry-codes": "2026-08-22"}
    assert m.quarantined_sources == ["houjin-bangou"]
    assert "houjin-bangou" not in m.sources, "隔離済みソースの日付を載せてはならない"


def test_build_manifest_rejects_empty_jena_version(tmp_path):
    """Jenaバージョンの記録漏れを許さない(設計書§6.3)。"""
    nq = tmp_path / "kg.nq"
    nq.write_text("", encoding="utf-8")
    tarball = tmp_path / "kg.tar.gz"
    tarball.write_bytes(b"x")

    with pytest.raises(ValueError, match="Jena"):
        build.build_manifest(nquads=nq, tarball=tarball, jena_version="",
                             release="r", sources={}, graphs=[], tdb2_expanded_bytes=1,
                             git_commit=_DUMMY_GIT_COMMIT, git_dirty=False)


def test_build_manifest_rejects_non_positive_tdb2_expanded_bytes(tmp_path):
    """TDB2展開後サイズが0や負値のまま manifest に記録されることを許さない。

    Task 11修正ラウンド(fix-brief §3): §6.3の8GiB判定はこの数値でしか行えない。
    build.sh側でdu -sbの出力を読み取れなかった場合に黙って0やNoneを書くのでは
    なく、ここで落ちる形にする(「既定は止まる側」。jena_versionの検査と同じ作法)。

    **何があれば落ちるか**: `if tdb2_expanded_bytes <= 0:` のガードを外すと落ちる
    (0を渡してもManifestが構築されてしまう)。
    """
    nq = tmp_path / "kg.nq"
    nq.write_text("", encoding="utf-8")
    tarball = tmp_path / "kg.tar.gz"
    tarball.write_bytes(b"x")

    with pytest.raises(ValueError, match="tdb2_expanded_bytes"):
        build.build_manifest(nquads=nq, tarball=tarball, jena_version="5.0.0",
                             release="r", sources={}, graphs=[], tdb2_expanded_bytes=0,
                             git_commit=_DUMMY_GIT_COMMIT, git_dirty=False)
    with pytest.raises(ValueError, match="tdb2_expanded_bytes"):
        build.build_manifest(nquads=nq, tarball=tarball, jena_version="5.0.0",
                             release="r", sources={}, graphs=[], tdb2_expanded_bytes=-1,
                             git_commit=_DUMMY_GIT_COMMIT, git_dirty=False)


def test_build_manifest_rejects_empty_git_commit(tmp_path):
    """コミットSHAの記録漏れを許さない(B-2裁定)。

    **何があれば落ちるか**: 空文字の`git_commit`をそのまま受理するように
    実装を変えると落ちる。空のSHAを記録すると「配布物とコードを結ぶ
    唯一の手がかり」(B-2裁定の趣旨)が最初から欠けたまま出荷されてしまう
    ——jena_version/tdb2_expanded_bytesの検査と同じ「既定は止まる側」。
    """
    nq = tmp_path / "kg.nq"
    nq.write_text("", encoding="utf-8")
    tarball = tmp_path / "kg.tar.gz"
    tarball.write_bytes(b"x")

    with pytest.raises(ValueError, match="git_commit"):
        build.build_manifest(nquads=nq, tarball=tarball, jena_version="5.0.0",
                             release="r", sources={}, graphs=[], tdb2_expanded_bytes=1,
                             git_commit="", git_dirty=False)


def test_build_manifest_records_dirty_flag_both_ways(tmp_path):
    """`git_dirty`がTrue/Falseどちらの値でもそのまま記録されること。

    (`False`が既定値的に見える値なので、`False`しか渡さないテストだと
    「常にFalseに固定される」欠陥を検出できない。両方を明示的に確認する。)
    """
    nq = tmp_path / "kg.nq"
    nq.write_text("", encoding="utf-8")
    tarball = tmp_path / "kg.tar.gz"
    tarball.write_bytes(b"x")

    m_clean = build.build_manifest(nquads=nq, tarball=tarball, jena_version="5.0.0",
                                    release="r", sources={}, graphs=[], tdb2_expanded_bytes=1,
                                    git_commit=_DUMMY_GIT_COMMIT, git_dirty=False)
    m_dirty = build.build_manifest(nquads=nq, tarball=tarball, jena_version="5.0.0",
                                    release="r", sources={}, graphs=[], tdb2_expanded_bytes=1,
                                    git_commit=_DUMMY_GIT_COMMIT, git_dirty=True)
    assert m_clean.git_dirty is False
    assert m_dirty.git_dirty is True


def test_verify_manifest_detects_corruption(tmp_path):
    tarball = tmp_path / "kg.tar.gz"
    tarball.write_bytes(b"original")
    nq = tmp_path / "kg.nq"
    nq.write_text("", encoding="utf-8")

    m = build.build_manifest(nquads=nq, tarball=tarball, jena_version="5.0.0",
                             release="r", sources={}, graphs=[], tdb2_expanded_bytes=1,
                             git_commit=_DUMMY_GIT_COMMIT, git_dirty=False)
    manifest_path = tmp_path / "manifest.json"
    build.write_manifest(m, manifest_path)

    build.verify_manifest(manifest_path, tarball)  # 一致するので例外なし

    tarball.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="sha256"):
        build.verify_manifest(manifest_path, tarball)


def test_verify_manifest_detects_jena_version_mismatch(tmp_path):
    """実行側のJenaバージョンが成果物と違えば例外になること。

    TDB2のオンディスク形式はJenaのバージョンに紐づく。記録しただけで
    照合しなければ、その記録は意味を持たない。
    """
    tarball = tmp_path / "kg.tar.gz"
    tarball.write_bytes(b"content")
    nq = tmp_path / "kg.nq"
    nq.write_text("", encoding="utf-8")

    m = build.build_manifest(
        nquads=nq, tarball=tarball, jena_version="6.2.0",
        release="r", sources={}, graphs=[], tdb2_expanded_bytes=1,
        git_commit=_DUMMY_GIT_COMMIT, git_dirty=False,
    )
    manifest_path = tmp_path / "manifest.json"
    build.write_manifest(m, manifest_path)

    # 一致するなら例外なし
    build.verify_manifest(manifest_path, tarball, expected_jena_version="6.2.0")
    # 省略した場合も従来通り例外なし
    build.verify_manifest(manifest_path, tarball)
    # 違えば例外
    with pytest.raises(ValueError, match="Jenaバージョン"):
        build.verify_manifest(manifest_path, tarball, expected_jena_version="6.1.0")


def test_write_manifest_is_readable_json(tmp_path):
    nq = tmp_path / "kg.nq"
    nq.write_text("", encoding="utf-8")
    tarball = tmp_path / "kg.tar.gz"
    tarball.write_bytes(b"x")
    m = build.build_manifest(nquads=nq, tarball=tarball, jena_version="5.0.0",
                             release="2026-08-01", sources={}, graphs=[], tdb2_expanded_bytes=1,
                             git_commit=_DUMMY_GIT_COMMIT, git_dirty=False)
    path = tmp_path / "manifest.json"
    build.write_manifest(m, path)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["release"] == "2026-08-01"
    assert data["jena_version"] == "5.0.0"


def test_triple_count_handles_tricky_literals(tmp_path):
    """空白・`<`・`>`・改行を含むリテラルやデータ型IRIがあっても行数を正しく数える。

    以前はここからグラフURIを推測しており、3項トリプル行のオブジェクトIRIを
    グラフURIと誤認する欠陥があった。推測をやめたので、数えるだけが正しい。
    """
    nq = tmp_path / "tricky.nq"
    nq.write_text(
        '<http://example.test/s> <http://example.test/p> "空白 と <山括弧> を含む"@ja <http://example.test/g> .\n'
        '<http://example.test/s> <http://example.test/p> "42"^^<http://www.w3.org/2001/XMLSchema#integer> <http://example.test/g> .\n'
        '<http://example.test/s> <http://example.test/p> <http://example.test/o> .\n'   # グラフ項なしの3項行
        '\n'
        '# コメント行\n',
        encoding="utf-8",
    )
    tarball = tmp_path / "kg.tar.gz"
    tarball.write_bytes(b"x")

    m = build.build_manifest(
        nquads=nq, tarball=tarball, jena_version="5.0.0",
        release="r", sources={}, graphs=["http://example.test/g"], tdb2_expanded_bytes=1,
        git_commit=_DUMMY_GIT_COMMIT, git_dirty=False,
    )
    assert m.triple_count == 3, "空行とコメント行を除いた3行を数えるべき"
    # 3項行のオブジェクトIRIがグラフとして混入していないこと
    assert m.graphs == ["http://example.test/g"]
    assert "http://example.test/o" not in m.graphs


def test_build_manifest_produces_version_6(tmp_path):
    """新規に構築した manifest は manifest_version=6 を持つこと。

    計画B Task 1がmanifest_version欄自体の追加で2に上げ、Task 10修正ラウンド1が
    `nquads_sha256`欄の追加で3に上げ、Task 11修正ラウンドが`tdb2_expanded_bytes`
    欄の追加で4に上げ、Task 11修正ラウンド2(Ruling B31)が`release`/`created_on`
    の意味変更(最新ソース取得日→成果物ディレクトリのbasename)で5に上げた
    (欄追加ではないが、既存欄の意味が変わるのも読み手には破壊的変更なので
    同じ「版を上げる」作法に従う)。B-2裁定が`git_commit`/`git_dirty`欄の
    追加で6に上げた(配布物をダウンロードした人がそれを作ったコードの
    コミットを特定できるようにする)。
    """
    nq = tmp_path / "kg.nq"
    nq.write_text("", encoding="utf-8")
    tarball = tmp_path / "kg.tar.gz"
    tarball.write_bytes(b"x")

    m = build.build_manifest(nquads=nq, tarball=tarball, jena_version="5.0.0",
                             release="r", sources={}, graphs=[], tdb2_expanded_bytes=1,
                             git_commit=_DUMMY_GIT_COMMIT, git_dirty=False)
    assert m.manifest_version == 6


def test_read_manifest_treats_a_missing_version_field_as_1(tmp_path):
    """`manifest_version` 欄が無い旧 manifest.json を読むと 1 とみなすこと。

    この欄自体を計画B Task 1 で追加したため、それ以前に作られた manifest には
    存在しない。**何があれば落ちるか**: `Manifest` フィールドの既定値(6)を
    そのまま使う実装に戻すと、旧ファイルも6と誤判定されて落ちる。
    """
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({
            "release": "2026-08-01",
            "created_on": "2026-08-01",
            "jena_version": "5.0.0",
            "sha256": "0" * 64,
            "byte_size": 1,
            "triple_count": 1,
            "graphs": [],
            "sources": {},
        }),
        encoding="utf-8",
    )

    m = build.read_manifest(manifest_path)
    assert m.manifest_version == 1


def test_manifest_version_roundtrips_through_write_and_read(tmp_path):
    """新規 manifest を書いて読み直しても版(6)・git_commit・git_dirtyが保たれること。"""
    nq = tmp_path / "kg.nq"
    nq.write_text("", encoding="utf-8")
    tarball = tmp_path / "kg.tar.gz"
    tarball.write_bytes(b"x")

    m = build.build_manifest(nquads=nq, tarball=tarball, jena_version="5.0.0",
                             release="r", sources={}, graphs=[], tdb2_expanded_bytes=1,
                             git_commit=_DUMMY_GIT_COMMIT, git_dirty=True)
    manifest_path = tmp_path / "manifest.json"
    build.write_manifest(m, manifest_path)

    reloaded = build.read_manifest(manifest_path)
    assert reloaded.manifest_version == 6
    assert reloaded.nquads_sha256 == m.nquads_sha256
    assert reloaded.tdb2_expanded_bytes == m.tdb2_expanded_bytes
    assert reloaded.git_commit == _DUMMY_GIT_COMMIT
    assert reloaded.git_dirty is True


def test_read_manifest_treats_a_missing_nquads_sha256_as_none(tmp_path):
    """`nquads_sha256`欄が無い旧manifest(manifest_version<3)を読むとNoneになること。

    **何があれば落ちるか**: `Manifest`のフィールド既定を空文字などに変えると、
    pipeline.pyのcarry-over供給元照合(Ruling B26)が「照合できない」ことを
    正しく検出できなくなる。
    """
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({
            "release": "2026-08-01",
            "created_on": "2026-08-01",
            "jena_version": "5.0.0",
            "sha256": "0" * 64,
            "byte_size": 1,
            "triple_count": 1,
            "graphs": [],
            "sources": {},
            "manifest_version": 2,
        }),
        encoding="utf-8",
    )

    m = build.read_manifest(manifest_path)
    assert m.nquads_sha256 is None


def test_read_manifest_treats_a_missing_tdb2_expanded_bytes_as_none(tmp_path):
    """`tdb2_expanded_bytes`欄が無い旧manifest(manifest_version<4)を読むとNoneになること。

    Task 11修正ラウンド。**何があれば落ちるか**: `Manifest`のフィールド既定を
    0などに変えると、「§6.3の8GiB判定ができない(未記録)」と「判定した結果
    0バイトだった」が区別できなくなる(nquads_sha256と同じ「None≠既定値」の作法)。
    """
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({
            "release": "2026-08-01",
            "created_on": "2026-08-01",
            "jena_version": "5.0.0",
            "sha256": "0" * 64,
            "byte_size": 1,
            "triple_count": 1,
            "nquads_sha256": "1" * 64,
            "graphs": [],
            "sources": {},
            "manifest_version": 3,
        }),
        encoding="utf-8",
    )

    m = build.read_manifest(manifest_path)
    assert m.tdb2_expanded_bytes is None


def test_read_manifest_treats_missing_git_fields_as_none(tmp_path):
    """`git_commit`/`git_dirty`欄が無い旧manifest(manifest_version<6)を読むと
    両方Noneになること。

    B-2裁定: 「片方だけ記録されていても意味がない(SHAが汚れていたかどうか
    分からなければ、そのSHAを信頼できない)」という趣旨に基づき、この2欄は
    常にペアで追加された。旧manifestにはどちらも存在しないため、
    nquads_sha256/tdb2_expanded_bytesと同じ「None≠既定値」の作法で
    両方Noneとして読む。

    **何があれば落ちるか**: `Manifest`のフィールド既定を空文字/Falseに
    変えると、「記録されていない」ことと「クリーンな空コミットだった」が
    区別できなくなる。
    """
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps({
            "release": "2026-08-01",
            "created_on": "2026-08-01",
            "jena_version": "5.0.0",
            "sha256": "0" * 64,
            "byte_size": 1,
            "triple_count": 1,
            "nquads_sha256": "1" * 64,
            "tdb2_expanded_bytes": 1,
            "graphs": [],
            "sources": {},
            "manifest_version": 5,
        }),
        encoding="utf-8",
    )

    m = build.read_manifest(manifest_path)
    assert m.git_commit is None
    assert m.git_dirty is None


def test_build_manifest_nquads_sha256_changes_when_kg_nq_content_changes(tmp_path):
    """kg.nqの内容が変われば`nquads_sha256`も変わること(完全性照合の基本要件)。"""
    tarball = tmp_path / "kg.tar.gz"
    tarball.write_bytes(b"x")

    nq_a = tmp_path / "a.nq"
    nq_a.write_text(
        '<http://example.test/s> <http://example.test/p> <http://example.test/o1> <http://example.test/g> .\n',
        encoding="utf-8",
    )
    nq_b = tmp_path / "b.nq"
    nq_b.write_text(
        '<http://example.test/s> <http://example.test/p> <http://example.test/o2> <http://example.test/g> .\n',
        encoding="utf-8",
    )

    m_a = build.build_manifest(nquads=nq_a, tarball=tarball, jena_version="5.0.0",
                                release="r", sources={}, graphs=[], tdb2_expanded_bytes=1,
                                git_commit=_DUMMY_GIT_COMMIT, git_dirty=False)
    m_b = build.build_manifest(nquads=nq_b, tarball=tarball, jena_version="5.0.0",
                                release="r", sources={}, graphs=[], tdb2_expanded_bytes=1,
                                git_commit=_DUMMY_GIT_COMMIT, git_dirty=False)
    assert m_a.nquads_sha256 != m_b.nquads_sha256
