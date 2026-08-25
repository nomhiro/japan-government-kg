"""B-1: KGを配布可能にする(公開の仕組み)。

`scripts/publish-release.sh` / `python -m jgkg.publish` の実体をテストする。
GitHub Actions のワークフローを作らない理由は `scripts/publish-release.sh` の
コメントに書く(このテストの対象外)。
"""
import gzip
import hashlib
import json
import subprocess

import pytest

from jgkg import build, publish, sources


def _make_release_dir(tmp_path, name="2026-08-01", nquads_text=None, sources_map=None, graphs=None):
    """kg.nq・tdb2.tar.gz・manifest.json を持つ、本物と同じ形の release_dir を作る。

    `tests/test_build.py` の既存の作り方(`build.build_manifest`→
    `build.write_manifest`)をそのまま使う——manifestの構築ロジック自体を
    ここで再実装しない。
    """
    release_dir = tmp_path / name
    release_dir.mkdir()
    if nquads_text is None:
        nquads_text = (
            "<https://jgkg.norr-tech.com/id/law/1> "
            "<https://jgkg.norr-tech.com/def/law#jurisdiction> "
            "<https://jgkg.norr-tech.com/id/org/1> "
            "<https://jgkg.norr-tech.com/graph/egov-law/2026-08-01> .\n"
        )
    (release_dir / "kg.nq").write_text(nquads_text, encoding="utf-8")
    tarball_path = release_dir / publish.TARBALL_NAME
    tarball_path.write_bytes(b"fake tdb2 tarball content")

    m = build.build_manifest(
        nquads=release_dir / "kg.nq",
        tarball=tarball_path,
        jena_version="6.2.0",
        release=name,
        sources=sources_map or {"egov-law": "2026-08-01", "houjin-bangou": "2026-08-01"},
        graphs=graphs if graphs is not None else [f"https://jgkg.norr-tech.com/graph/egov-law/{name}"],
        tdb2_expanded_bytes=1234,
        git_commit="a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
        git_dirty=False,
    )
    build.write_manifest(m, release_dir / build.MANIFEST_NAME)
    return release_dir, m


# =============================================================================
# verify_release_assets: 公開前検査(本体)
# =============================================================================


def test_verify_release_assets_passes_for_a_genuine_release(tmp_path):
    """壊れていない release_dir は例外なく通ること(壊し確認の陽性対照)。"""
    release_dir, m = _make_release_dir(tmp_path)
    result = publish.verify_release_assets(release_dir)
    assert result.release == m.release


def test_verify_release_assets_rejects_tarball_sha256_mismatch(tmp_path):
    """manifestのsha256(tarball)と実物が食い違うと拒否されること。

    何があれば落ちるか: `--out-dir`にコミット後もtarballが転送・保管中に
    壊れる(B26と同じ懸念)。manifestを信じて配布すると、壊れたtarballを
    正しいものとして配ってしまう。
    """
    release_dir, _m = _make_release_dir(tmp_path)
    manifest_path = release_dir / build.MANIFEST_NAME
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["sha256"] = "0" * 64  # 実物と食い違う値に書き換える
    manifest_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="sha256"):
        publish.verify_release_assets(release_dir)


def test_verify_release_assets_rejects_nquads_sha256_mismatch(tmp_path):
    """manifestのnquads_sha256(kg.nq)と実物が食い違うと拒否されること。"""
    release_dir, _m = _make_release_dir(tmp_path)
    # kg.nq をmanifest構築後に書き換える(保管中の破損を模す)
    (release_dir / "kg.nq").write_text("破損した内容\n", encoding="utf-8")

    with pytest.raises(ValueError, match="nquads_sha256|kg\\.nq"):
        publish.verify_release_assets(release_dir)


def test_verify_release_assets_rejects_a_manifest_without_nquads_sha256(tmp_path):
    """旧形式(nquads_sha256欄が無い)manifestは、kg.nqの完全性を照合できないので拒否すること。

    `nquads_sha256 is None` を「照合をスキップして通す」にはしない——
    「既定は止まる側」(このプロジェクトの繰り返しの作法)。
    """
    release_dir, _m = _make_release_dir(tmp_path)
    manifest_path = release_dir / build.MANIFEST_NAME
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    del data["nquads_sha256"]
    data["manifest_version"] = 2
    manifest_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="nquads_sha256"):
        publish.verify_release_assets(release_dir)


def test_verify_release_assets_rejects_when_release_name_does_not_match_directory(tmp_path):
    """manifest.releaseとディレクトリのbasenameが食い違うと拒否されること(Ruling B31)。"""
    release_dir, _m = _make_release_dir(tmp_path, name="2026-08-01")
    manifest_path = release_dir / build.MANIFEST_NAME
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["release"] = "2026-08-02"  # ディレクトリ名と食い違わせる
    manifest_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="release"):
        publish.verify_release_assets(release_dir)


@pytest.mark.parametrize("missing_name", ["manifest.json", "tdb2.tar.gz", "kg.nq"])
def test_verify_release_assets_rejects_a_missing_asset(tmp_path, missing_name):
    """3資産(manifest.json / tdb2.tar.gz / kg.nq)のどれが欠けても拒否されること。

    パラメータ化した3件すべてを実際に検査する(空虚な検査にしない —
    「そもそもファイルが1つも無いディレクトリ」だけを試して終わりにしない)。
    """
    release_dir, _m = _make_release_dir(tmp_path)
    (release_dir / missing_name).unlink()

    with pytest.raises(FileNotFoundError):
        publish.verify_release_assets(release_dir)


# =============================================================================
# make_kg_nq_gz: kg.nq.gz の作成(元のkg.nqは消さない)
# =============================================================================


def test_make_kg_nq_gz_creates_a_valid_gzip_without_deleting_the_original(tmp_path):
    release_dir, m = _make_release_dir(tmp_path)
    original_bytes = (release_dir / "kg.nq").read_bytes()

    gz_path, gz_sha256, gz_size = publish.make_kg_nq_gz(release_dir, m)

    assert gz_path.exists()
    assert (release_dir / "kg.nq").exists(), "元のkg.nqを消してはならない"
    assert (release_dir / "kg.nq").read_bytes() == original_bytes, "元のkg.nqの内容も変えてはならない"
    with gzip.open(gz_path, "rb") as f:
        assert f.read() == original_bytes, "kg.nq.gzを展開するとkg.nqと同じ内容に戻ること"
    assert gz_sha256 == hashlib.sha256(gz_path.read_bytes()).hexdigest()
    assert gz_size == gz_path.stat().st_size


def test_make_kg_nq_gz_is_idempotent_when_rerun_against_unchanged_kg_nq(tmp_path):
    """2回目の呼び出しは既存のkg.nq.gzを壊さずに再利用すること(B31と同じ「既定は止まる側」)。"""
    release_dir, m = _make_release_dir(tmp_path)
    first_path, first_sha256, _size = publish.make_kg_nq_gz(release_dir, m)
    first_mtime = first_path.stat().st_mtime_ns

    second_path, second_sha256, _size2 = publish.make_kg_nq_gz(release_dir, m)

    assert second_path == first_path
    assert second_sha256 == first_sha256
    assert second_path.stat().st_mtime_ns == first_mtime, "再利用ではなく再生成すると更新時刻が変わるはず"


def test_make_kg_nq_gz_rejects_a_stale_gz_that_no_longer_matches_kg_nq(tmp_path):
    """既存のkg.nq.gzが今のkg.nqと食い違う(古い)場合は、黒く上書きせず拒否すること。

    何があれば落ちるか: 古いkg.nq.gzを「あるので再利用してよい」と黙って
    使い続けると、更新されたkg.nqと食い違う古いgzを配ってしまう。
    """
    release_dir, m = _make_release_dir(tmp_path)
    publish.make_kg_nq_gz(release_dir, m)  # 最初の(正しい)kg.nq.gzを作る

    # kg.nq.gz だけを、今のkg.nqとは無関係な内容で上書きする(古いgzの模擬)
    with gzip.open(release_dir / publish.KG_NQ_GZ_NAME, "wb") as f:
        f.write(b"stale content unrelated to kg.nq")

    with pytest.raises(ValueError, match="kg\\.nq\\.gz"):
        publish.make_kg_nq_gz(release_dir, m)


# =============================================================================
# render_release_notes: 手書き禁止(sources.py・manifestからの導出)
# =============================================================================


def test_release_notes_are_derived_from_the_manifest_not_hardcoded(tmp_path):
    """トリプル数・グラフ一覧・ソース日付がmanifestの値そのものであること。

    空虚にしない: 別の(違う)manifestに対して呼び、出力される数値が
    追従して変わることまで確認する——固定テンプレートに偶然一致しただけの
    検査にしない。
    """
    release_dir, m = _make_release_dir(
        tmp_path, name="2026-08-01",
        sources_map={"egov-law": "2026-08-01"},
    )
    gz_path, gz_sha256, gz_size = publish.make_kg_nq_gz(release_dir, m)
    notes = publish.render_release_notes(release_dir, m, gz_path, gz_sha256, gz_size)

    assert str(m.triple_count) in notes
    assert "https://jgkg.norr-tech.com/graph/egov-law/2026-08-01" in notes
    assert "2026-08-01" in notes
    assert gz_sha256 in notes
    assert m.sha256 in notes, "tdb2.tar.gzのsha256(manifest記録値)も載ること"

    # 別のmanifest(トリプル数・グラフが違う)に対しては出力も追従して変わる
    release_dir_2, m2 = _make_release_dir(
        tmp_path, name="2026-08-02",
        nquads_text=(
            "<https://jgkg.norr-tech.com/id/law/1> "
            "<https://jgkg.norr-tech.com/def/law#jurisdiction> "
            "<https://jgkg.norr-tech.com/id/org/1> "
            "<https://jgkg.norr-tech.com/graph/egov-law/2026-08-02> .\n"
            "<https://jgkg.norr-tech.com/id/law/2> "
            "<https://jgkg.norr-tech.com/def/law#jurisdiction> "
            "<https://jgkg.norr-tech.com/id/org/2> "
            "<https://jgkg.norr-tech.com/graph/egov-law/2026-08-02> .\n"
        ),
        sources_map={"egov-law": "2026-08-02"},
    )
    gz_path_2, gz_sha256_2, gz_size_2 = publish.make_kg_nq_gz(release_dir_2, m2)
    notes_2 = publish.render_release_notes(release_dir_2, m2, gz_path_2, gz_sha256_2, gz_size_2)

    assert str(m2.triple_count) in notes_2
    assert str(m.triple_count) != str(m2.triple_count), "この検査自体が別の値を比較できているか(前提)"
    assert "2026-08-02" in notes_2
    assert "2026-08-01" not in notes_2, "前のリリースの取得日を引き続き主張してはならない"


def test_release_notes_license_text_is_derived_from_sources_py(tmp_path, monkeypatch):
    """出典表示・ライセンスが `sources.py` から導出されていること(直書き禁止)。

    このプロジェクトで6件目になる「導出すべき値を手書きする」型への対処。
    `sources.SOURCES` を偽の値で置き換え、(a) 偽の値が出力に現れること、
    (b) 元の(本物の)ライセンス文字列が出力から消えていること、の両方向を
    確認する——片方向だけでは「たまたま両方の文字列を含むテンプレート」を
    見逃す(空虚な検査にしない)。
    """
    release_dir, m = _make_release_dir(
        tmp_path, sources_map={"egov-law": "2026-08-01"},
    )
    gz_path, gz_sha256, gz_size = publish.make_kg_nq_gz(release_dir, m)

    real_license = sources.get_source("egov-law").license
    fake_source = sources.Source(
        id="egov-law",
        name="架空のテスト用ソース名PLACEHOLDER",
        url="https://example.test/fake-source",
        license="架空のテスト用ライセンスXYZ123",
        license_url="https://example.test/fake-license",
        frequency="monthly",
        access="api",
    )
    monkeypatch.setitem(sources.SOURCES, "egov-law", fake_source)

    notes = publish.render_release_notes(release_dir, m, gz_path, gz_sha256, gz_size)

    assert "架空のテスト用ライセンスXYZ123" in notes, "sources.SOURCESを書き換えた値が出力に反映されるべき"
    assert "架空のテスト用ソース名PLACEHOLDER" in notes
    assert real_license not in notes, "元のライセンス文字列がテンプレートに直書きされていれば残ってしまう"


def test_release_notes_citation_is_derived_from_sources_py(tmp_path, monkeypatch):
    """出典の記載例(`citation`)も`sources.py`から導出されていること(直書き禁止)。

    ライセンス文字列の検査(上のテスト)と同じ「両方向」確認:
    偽の`citation`が出力に現れ、元の(本物の)`citation`が消えていること。
    """
    release_dir, m = _make_release_dir(
        tmp_path, sources_map={"egov-law": "2026-08-01"},
    )
    gz_path, gz_sha256, gz_size = publish.make_kg_nq_gz(release_dir, m)

    real_citation = sources.get_source("egov-law").citation
    fake_source = sources.Source(
        id="egov-law",
        name="架空のテスト用ソース名",
        url="https://example.test/fake-source",
        license="架空のテスト用ライセンス",
        license_url="https://example.test/fake-license",
        frequency="monthly",
        access="api",
        citation="架空のテスト用出典記載例QWERTY789",
    )
    monkeypatch.setitem(sources.SOURCES, "egov-law", fake_source)

    notes = publish.render_release_notes(release_dir, m, gz_path, gz_sha256, gz_size)

    assert "架空のテスト用出典記載例QWERTY789" in notes
    assert real_citation not in notes, "元の出典記載例がテンプレートに直書きされていれば残ってしまう"


def test_release_notes_include_editing_disclosure_and_processor_identity(tmp_path):
    """PDL1.0が要求する「編集・加工を行ったこと及びその主体」の記載があること。

    出典表示だけでは足りない(PDL1.0原文: 「編集・加工等して利用する場合は、
    上記出典とは別に、編集・加工等を行ったことを記載してください」)。
    このKGは解析・正規化・RDF化という編集・加工そのものなので、この開示が
    必須になる。
    """
    release_dir, m = _make_release_dir(tmp_path)
    gz_path, gz_sha256, gz_size = publish.make_kg_nq_gz(release_dir, m)
    notes = publish.render_release_notes(release_dir, m, gz_path, gz_sha256, gz_size)

    assert "編集" in notes and "加工" in notes
    assert "japan-government-kg" in notes.lower(), "加工の主体(このプロジェクト自身)を名指しすること"


def test_release_notes_include_third_party_rights_caveat(tmp_path):
    """PDL1.0の第三者権利の注意と、RS自身の「法人番号列・根拠法令名列は提供元の条件に従う」旨があること。

    **空虚にしない注意**: 冒頭の定型文(「日本国政府が公開するデータを
    第三者が構造化したものであり」)にも偶然「第三者」という文字列が
    含まれるため、`"第三者" in notes` だけでは常に真になり空虚な検査になる
    (実際に確認して気づいた)。PDL1.0原文の第三者条項に特有の言い回し
    (「著作権その他の権利」)で検査する。
    """
    release_dir, m = _make_release_dir(tmp_path)
    gz_path, gz_sha256, gz_size = publish.make_kg_nq_gz(release_dir, m)
    notes = publish.render_release_notes(release_dir, m, gz_path, gz_sha256, gz_size)

    assert "著作権その他の権利" in notes
    assert "法人番号" in notes and "根拠法令" in notes, "RS自身の列単位の注意も載ること"


def test_release_notes_do_not_claim_to_relicense_the_underlying_government_data(tmp_path):
    """成果物全体を無条件にCC BY 4.0と主張しないこと(元データの再ライセンスは出来ない)。

    何が問題になりうるか: 「この成果物はCC BY 4.0です」だけを書くと、政府が
    公開した元データ自体を私たちがCC BY 4.0へ再ライセンスしたかのように
    読める。元データは各出典元のPDL1.0に基づき、それを私たちが変える権限は
    無い。
    """
    release_dir, m = _make_release_dir(tmp_path)
    gz_path, gz_sha256, gz_size = publish.make_kg_nq_gz(release_dir, m)
    notes = publish.render_release_notes(release_dir, m, gz_path, gz_sha256, gz_size)

    assert "CC BY 4.0" in notes
    assert "再ライセンス" in notes, "元データの再ライセンスはできないことを明記すること"
    assert "公共データ利用規約" in notes or "PDL1.0" in notes


def test_release_notes_labels_ministry_codes_as_recorded_on_not_fetched_on(tmp_path):
    """`local_path`を持つソース(ministry-codes)は「記録日」、それ以外は「取得日」と表示すること。

    `schema/competency-questions.md`のCQ10の答え(houjin-bangou/egov-law/
    rs-system=取得日、ministry-codes=記録日)と同じ区別を、文字列比較
    ("ministry-codes"という名前の一致)ではなく`local_path is not None`という
    構造的な条件で行う(`fetch.py`・A-4で修正した`pipeline.py`と同じ判定条件)。
    """
    release_dir, m = _make_release_dir(
        tmp_path,
        sources_map={"egov-law": "2026-08-01", "ministry-codes": "2026-08-01"},
    )
    gz_path, gz_sha256, gz_size = publish.make_kg_nq_gz(release_dir, m)
    notes = publish.render_release_notes(release_dir, m, gz_path, gz_sha256, gz_size)

    assert "記録日" in notes
    assert "取得日" in notes


# =============================================================================
# CLI(main): dry-run既定・--publish・ghの認証状態
# =============================================================================


def test_cli_dry_run_never_calls_gh(tmp_path, monkeypatch, capsys):
    """`--publish`を渡さない既定の呼び出しでは、gh関連の関数が一切呼ばれないこと。

    壊し確認3件の1つ。gh呼び出し関数をスタブにして「呼ばれたら失敗する」形にし、
    それでもdry-runが正常終了することを確認する。
    """
    release_dir, _m = _make_release_dir(tmp_path)

    def _must_not_be_called(*args, **kwargs):
        pytest.fail("dry-run(--publish無し)でgh関連の関数が呼ばれた")

    monkeypatch.setattr(publish, "_gh_auth_status", _must_not_be_called)
    monkeypatch.setattr(publish, "_gh_release_create", _must_not_be_called)

    assert publish.main([str(release_dir)]) == 0
    out = capsys.readouterr().out
    assert "dry-run" in out
    assert (release_dir / publish.KG_NQ_GZ_NAME).exists(), "dry-runでも配布物の用意(kg.nq.gz作成)は行うこと"


def test_cli_publish_flag_does_call_gh(tmp_path, monkeypatch):
    """`--publish`を渡すと、実際にgh関連の関数が(スタブ経由で)呼ばれること。

    上のdry-runテストが「そもそもどんな入力でも呼ばれない」という空虚な
    検査になっていないことの陽性対照——このテストが無いと、
    `_gh_release_create`を呼ぶコードパス自体が存在しなくても上のテストは通る。
    """
    release_dir, m = _make_release_dir(tmp_path)
    calls = []

    def _fake_auth_status():
        return subprocess.CompletedProcess(args=["gh", "auth", "status"], returncode=0, stdout="Logged in", stderr="")

    def _fake_release_create(release, notes_path, assets):
        calls.append((release, notes_path, tuple(assets)))
        return subprocess.CompletedProcess(args=["gh", "release", "create"], returncode=0, stdout="https://github.com/x/y/releases/tag/z", stderr="")

    monkeypatch.setattr(publish, "_gh_auth_status", _fake_auth_status)
    monkeypatch.setattr(publish, "_gh_release_create", _fake_release_create)

    assert publish.main([str(release_dir), "--publish"]) == 0
    assert len(calls) == 1, "gh release create相当の関数がちょうど1回呼ばれるべき"
    called_release, called_notes_path, called_assets = calls[0]
    assert called_release == m.release
    assert called_notes_path.exists()
    called_names = {p.name for p in called_assets}
    assert called_names == {publish.KG_NQ_GZ_NAME, publish.TARBALL_NAME, build.MANIFEST_NAME}, (
        "公開する資産は3つ(kg.nq.gz / tdb2.tar.gz / manifest.json)であるべき"
        "(リリースノート自体は本文であって資産ではない)"
    )


def test_cli_publish_is_rejected_without_gh_authentication(tmp_path, monkeypatch):
    """`gh auth status`が失敗を返したら、`gh release create`を試みずに拒否すること。

    `gh`の実際のstderrを検査の材料にする(「未認証」と決めつけない——
    ネットワーク不通・ホスト未設定でも`gh auth status`は非0を返すため)。
    """
    release_dir, _m = _make_release_dir(tmp_path)
    create_calls = []

    def _fake_auth_status_unauthenticated():
        return subprocess.CompletedProcess(
            args=["gh", "auth", "status"], returncode=1, stdout="",
            stderr="You are not logged into any GitHub hosts. Run gh auth login to authenticate.",
        )

    def _fake_release_create(release, notes_path, assets):
        create_calls.append((release, notes_path, assets))
        raise AssertionError("認証未了なのに gh release create が呼ばれた")

    monkeypatch.setattr(publish, "_gh_auth_status", _fake_auth_status_unauthenticated)
    monkeypatch.setattr(publish, "_gh_release_create", _fake_release_create)

    with pytest.raises(RuntimeError, match="gh auth login"):
        publish.main([str(release_dir), "--publish"])
    assert create_calls == [], "認証確認より前にgh release createが呼ばれてはならない"


def test_cli_publish_is_rejected_before_touching_gh_when_assets_are_broken(tmp_path, monkeypatch):
    """資産が壊れている場合、`--publish`付きでもgh関連の関数に一切到達しないこと。

    壊し確認3件のもう1つ(sha256不一致)。検査の順序(資産検査が最初)を固定する。
    """
    release_dir, _m = _make_release_dir(tmp_path)
    manifest_path = release_dir / build.MANIFEST_NAME
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(data), encoding="utf-8")

    def _must_not_be_called(*args, **kwargs):
        pytest.fail("資産が壊れているのにgh関連の関数に到達した")

    monkeypatch.setattr(publish, "_gh_auth_status", _must_not_be_called)
    monkeypatch.setattr(publish, "_gh_release_create", _must_not_be_called)

    with pytest.raises(ValueError, match="sha256"):
        publish.main([str(release_dir), "--publish"])
