"""成果物の配置経路のテスト。

レビューI3: `verify_manifest` を呼ぶのは今までテストだけで、実行時の照合経路が
存在しなかった。ここは「配置する前に照合する」ことを固定する。
"""
import tarfile

import pytest

from jgkg import build, serve


def _make_artifact(tmp_path, jena_version="6.2.0", payload=b"index bytes"):
    """build.sh が作るのと同じ形の成果物を1つ作る。"""
    art = tmp_path / "artifact" / "2026-08-01"
    (art / "tdb2").mkdir(parents=True)
    (art / "tdb2" / "nodes.dat").write_bytes(payload)
    nq = art / "kg.nq"
    nq.write_text("", encoding="utf-8")

    tarball = art / serve.TARBALL_NAME
    with tarfile.open(tarball, "w:gz") as tf:
        tf.add(art / "tdb2", arcname="tdb2")

    m = build.build_manifest(
        nquads=nq,
        tarball=tarball,
        jena_version=jena_version,
        release="2026-08-01",
        sources={"houjin-bangou": "2026-08-01"},
        graphs=[],
    )
    build.write_manifest(m, art / serve.MANIFEST_NAME)
    return art


def test_stage_release_places_the_database(tmp_path):
    art = _make_artifact(tmp_path)
    target = tmp_path / "serve" / "tdb2"

    placed = serve.stage_release(art, target, expected_jena_version="6.2.0")

    assert placed == target
    assert (target / "nodes.dat").read_bytes() == b"index bytes"
    # 作業用ディレクトリを残さない
    assert not target.with_name("tdb2.incoming").exists()


def test_stage_release_refuses_a_corrupted_artifact(tmp_path):
    """sha256 が合わない成果物を配置しないこと。

    **何があれば落ちるか**: `stage_release` から `verify_manifest` の呼び出しを
    外したら落ちる(壊れた成果物が配置されてしまう)。照合を展開より後ろに
    移動した場合も、target が作られてしまうので落ちる。
    """
    art = _make_artifact(tmp_path)
    (art / serve.TARBALL_NAME).write_bytes(b"tampered")
    target = tmp_path / "serve" / "tdb2"

    with pytest.raises(ValueError, match="sha256"):
        serve.stage_release(art, target, expected_jena_version="6.2.0")
    assert not target.exists(), "壊れた成果物が配置されてしまった"


def test_stage_release_refuses_a_jena_version_mismatch(tmp_path):
    """実行側のJenaバージョンが成果物と違えば配置しないこと。

    TDB2のオンディスク形式はJenaのバージョンに紐づく。`.env` の JENA_VERSION を
    上げて古い成果物を配ろうとしたら、ここで止まる。
    """
    art = _make_artifact(tmp_path, jena_version="6.2.0")
    target = tmp_path / "serve" / "tdb2"

    with pytest.raises(ValueError, match="Jenaバージョン"):
        serve.stage_release(art, target, expected_jena_version="6.3.0")
    assert not target.exists(), "バージョンの合わない成果物が配置されてしまった"


def test_stage_release_keeps_the_previous_generation(tmp_path):
    """差し替え時に前世代を残すこと(最低限の切り戻し)。"""
    target = tmp_path / "serve" / "tdb2"
    target.mkdir(parents=True)
    (target / "nodes.dat").write_bytes(b"old index")

    art = _make_artifact(tmp_path, payload=b"new index")
    serve.stage_release(art, target, expected_jena_version="6.2.0")

    assert (target / "nodes.dat").read_bytes() == b"new index"
    assert (target.with_name("tdb2.previous") / "nodes.dat").read_bytes() == b"old index"


def test_stage_release_reports_a_missing_artifact(tmp_path):
    with pytest.raises(FileNotFoundError, match="成果物が見つからない"):
        serve.stage_release(tmp_path / "nope", tmp_path / "serve" / "tdb2")
