import hashlib
import json

import pytest

from jgkg import build


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
    )

    assert m.jena_version == "5.0.0"
    assert m.sha256 == hashlib.sha256(b"fake tarball content").hexdigest()
    assert m.byte_size == len(b"fake tarball content")
    assert m.triple_count == 1
    assert m.graphs == ["http://example.test/g"]
    assert m.sources == {"houjin-bangou": "2026-08-01"}


def test_build_manifest_rejects_empty_jena_version(tmp_path):
    """Jenaバージョンの記録漏れを許さない(設計書§6.3)。"""
    nq = tmp_path / "kg.nq"
    nq.write_text("", encoding="utf-8")
    tarball = tmp_path / "kg.tar.gz"
    tarball.write_bytes(b"x")

    with pytest.raises(ValueError, match="Jena"):
        build.build_manifest(nquads=nq, tarball=tarball, jena_version="",
                             release="r", sources={}, graphs=[])


def test_verify_manifest_detects_corruption(tmp_path):
    tarball = tmp_path / "kg.tar.gz"
    tarball.write_bytes(b"original")
    nq = tmp_path / "kg.nq"
    nq.write_text("", encoding="utf-8")

    m = build.build_manifest(nquads=nq, tarball=tarball, jena_version="5.0.0",
                             release="r", sources={}, graphs=[])
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
        release="r", sources={}, graphs=[],
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
                             release="2026-08-01", sources={}, graphs=[])
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
        release="r", sources={}, graphs=["http://example.test/g"],
    )
    assert m.triple_count == 3, "空行とコメント行を除いた3行を数えるべき"
    # 3項行のオブジェクトIRIがグラフとして混入していないこと
    assert m.graphs == ["http://example.test/g"]
    assert "http://example.test/o" not in m.graphs
