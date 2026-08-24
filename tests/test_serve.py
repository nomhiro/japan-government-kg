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
    target = tmp_path / "serve" / "current" / "tdb2"

    placed = serve.stage_release(art, target, expected_jena_version="6.2.0")

    assert placed == target
    assert (target / "nodes.dat").read_bytes() == b"index bytes"
    # 作業用ディレクトリ(展開先の一時領域)を残さない。Task 10:
    # 切替の単位は target.parent(current/)全体なので、incoming/previousは
    # target.parentの**兄弟**(tmp_path/"serve"直下)に作られる
    assert not (tmp_path / "serve" / "incoming").exists()


def test_stage_release_refuses_a_corrupted_artifact(tmp_path):
    """sha256 が合わない成果物を配置しないこと。

    **何があれば落ちるか**: `stage_release` から `verify_manifest` の呼び出しを
    外したら落ちる(壊れた成果物が配置されてしまう)。照合を展開より後ろに
    移動した場合も、target が作られてしまうので落ちる。
    """
    art = _make_artifact(tmp_path)
    (art / serve.TARBALL_NAME).write_bytes(b"tampered")
    target = tmp_path / "serve" / "current" / "tdb2"

    with pytest.raises(ValueError, match="sha256"):
        serve.stage_release(art, target, expected_jena_version="6.2.0")
    assert not target.exists(), "壊れた成果物が配置されてしまった"


def test_stage_release_refuses_a_jena_version_mismatch(tmp_path):
    """実行側のJenaバージョンが成果物と違えば配置しないこと。

    TDB2のオンディスク形式はJenaのバージョンに紐づく。`.env` の JENA_VERSION を
    上げて古い成果物を配ろうとしたら、ここで止まる。
    """
    art = _make_artifact(tmp_path, jena_version="6.2.0")
    target = tmp_path / "serve" / "current" / "tdb2"

    with pytest.raises(ValueError, match="Jenaバージョン"):
        serve.stage_release(art, target, expected_jena_version="6.3.0")
    assert not target.exists(), "バージョンの合わない成果物が配置されてしまった"


def test_stage_release_keeps_the_previous_generation(tmp_path):
    """差し替え時に前世代を残すこと(最低限の切り戻し)。

    Task 10: 前世代は`target.parent`(`current/`)の**兄弟ディレクトリ**
    `previous/`の下に、`tdb2/`という同じ構造で残る(`current/tdb2` →
    `previous/tdb2`。ディレクトリごと退避するため内部構造はそのまま)。
    """
    target = tmp_path / "serve" / "current" / "tdb2"
    target.mkdir(parents=True)
    (target / "nodes.dat").write_bytes(b"old index")

    art = _make_artifact(tmp_path, payload=b"new index")
    serve.stage_release(art, target, expected_jena_version="6.2.0")

    assert (target / "nodes.dat").read_bytes() == b"new index"
    previous_tdb2 = tmp_path / "serve" / "previous" / "tdb2"
    assert (previous_tdb2 / "nodes.dat").read_bytes() == b"old index"


def test_stage_release_swaps_the_whole_current_directory_not_just_tdb2(tmp_path):
    """`current/`直下にtdb2以外のファイルがあっても、ディレクトリごと

    `previous/`へ退避されること(task-10-brief.md「`data/artifact/current`を
    ディレクトリごと入れ替える」)。**何があれば落ちるか**: tdb2サブディレクトリ
    だけを個別に入れ替える実装(旧`tdb2.previous`方式)に戻すと、この
    マーカーファイルは`current/`に残ったまま(=退避されない)になる。
    """
    current_dir = tmp_path / "serve" / "current"
    target = current_dir / "tdb2"
    target.mkdir(parents=True)
    (target / "nodes.dat").write_bytes(b"old index")
    marker = current_dir / "generation.marker"
    marker.write_text("gen-1", encoding="utf-8")

    art = _make_artifact(tmp_path, payload=b"new index")
    serve.stage_release(art, target, expected_jena_version="6.2.0")

    assert not marker.exists(), "current/直下の他ファイルが退避されずに残っている"
    previous_marker = tmp_path / "serve" / "previous" / "generation.marker"
    assert previous_marker.read_text(encoding="utf-8") == "gen-1"


def test_stage_release_reports_a_missing_artifact(tmp_path):
    with pytest.raises(FileNotFoundError, match="成果物が見つからない"):
        serve.stage_release(
            tmp_path / "nope", tmp_path / "serve" / "current" / "tdb2", expected_jena_version="6.2.0"
        )


def test_cli_refuses_when_the_jena_version_is_unknown(tmp_path, monkeypatch):
    """Jenaバージョンが分からないまま配置しないこと。

    以前は `--jena-version` を省略すると**何も言わずに照合を飛ばして配置**していた。
    I3 で作った照合経路が既定で無効になっているのと同じで、Ruling 35 の
    「記録の演技」に戻る。C2 と同じ方針(既定は止まる側)に揃える。

    **何があれば落ちるか**: `expected_jena_version` に既定値 `None` を戻したら、
    あるいはCLIが未解決のまま `stage_release` を呼ぶようになったら落ちる。
    """
    art = _make_artifact(tmp_path)
    monkeypatch.delenv("JENA_VERSION", raising=False)
    target = tmp_path / "serve" / "current" / "tdb2"

    with pytest.raises(SystemExit) as e:
        serve.main([str(art), "--target", str(target)])
    assert e.value.code == 2
    assert not target.exists(), "照合できないまま配置してしまった"


def test_cli_takes_the_jena_version_from_the_environment(tmp_path, monkeypatch):
    """環境変数 JENA_VERSION を既定として使うこと(compose と同じ値)。"""
    art = _make_artifact(tmp_path, jena_version="6.2.0")
    target = tmp_path / "serve" / "current" / "tdb2"

    monkeypatch.setenv("JENA_VERSION", "6.2.0")
    assert serve.main([str(art), "--target", str(target)]) == 0
    assert (target / "nodes.dat").exists()

    # 環境変数がずれていれば止まる
    monkeypatch.setenv("JENA_VERSION", "6.3.0")
    with pytest.raises(ValueError, match="Jenaバージョン"):
        serve.main([str(art), "--target", str(target)])


def test_cli_requires_an_explicit_flag_to_skip_the_check(tmp_path, monkeypatch):
    """照合を飛ばすには明示的なフラグが必要であること。"""
    art = _make_artifact(tmp_path, jena_version="6.2.0")
    monkeypatch.delenv("JENA_VERSION", raising=False)
    target = tmp_path / "serve" / "current" / "tdb2"

    assert serve.main([str(art), "--target", str(target), "--skip-jena-check"]) == 0
    assert (target / "nodes.dat").exists()

    # 併用は誤りとして弾く(どちらの意図か曖昧になる)
    with pytest.raises(SystemExit):
        serve.main(
            [str(art), "--target", str(target), "--skip-jena-check", "--jena-version", "6.2.0"]
        )
