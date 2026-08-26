"""Task 10: 更新の一巡(差分検出・置換・アトミック切替・鮮度)。設計書§1.2(C)の器。

2世代の固定スナップショットで訂正・削除・据え置きの3態を検証する(§10)。
アトミック切替(serve.sh)はDocker実機で別途確認する(task-10-report.md)。
"""
import datetime
import tarfile
from pathlib import Path

import pytest
from rdflib import Dataset, URIRef
from rdflib.namespace import SKOS
from zenken_rows import zenken_row, zipped

from jgkg import build, lake, pipeline, uris
from jgkg.config import get_settings
from jgkg.connectors import houjin_bangou

DAY1 = datetime.date(2026, 7, 1)
DAY2 = datetime.date(2026, 8, 1)

NUM_A = "6000012070001"
NUM_B = "2000012020001"

# 世代1と世代2で完全に同一のバイト列(「据え置き」判定の対象)
UNCHANGED_HOUJIN_BANGOU_BYTES = zipped(zenken_row(houjin_bangou=NUM_A, name="厚生労働省"))


@pytest.fixture(autouse=True)
def tmp_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "https://jgkg.norr-tech.com")
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    monkeypatch.setenv("JGKG_ARTIFACT_DIR", str(tmp_path / "artifact"))
    monkeypatch.setenv("JGKG_QUARANTINE_DIR", str(tmp_path / "quarantine"))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _artifact_dir(release: datetime.date) -> Path:
    """build.sh と同じ規約(`data/artifact/{release}`)。previous_release は

    このディレクトリの kg.nq を指す(pipeline.run のInterfaces)。
    """
    return Path(get_settings().artifact_dir) / release.isoformat()


def _load(path: Path) -> Dataset:
    ds = Dataset(default_union=True)
    ds.parse(path, format="nquads")
    return ds


def _write_fake_manifest(out_dir: Path, release: str, source_date: str | None = None) -> None:
    """build.sh が作るのと同じ形の最小限のtarball+manifestを書く(検証済み実行の代用)。

    「前リリースの成果物が実在し、出荷された」という前提を作るために使う。
    **Task 10修正ラウンド1(Ruling B26)以降、`previous_release`を渡す
    テストは全てこれを呼ぶ必要がある** — carry-overはmanifest.jsonの存在を
    出荷済みの証拠として要求し、`nquads_sha256`で`kg.nq`(呼び出し時点の
    実際の内容)との整合も照合する(`build.build_manifest`が`out_dir/"kg.nq"`
    を読んで計算するため、この関数を呼ぶ**時点**のkg.nqの内容がそのまま
    manifestに記録される——kg.nqをこの後で書き換えるテストは、書き換えた
    **後**に呼ぶこと)。

    `source_date`: manifest.sourcesに書く`houjin-bangou`の取得日(ISO文字列)。
    省略時は`release`と同じ値を使う(既存呼び出しの後方互換——B31以前は
    releaseと取得日が同じ前提だった)。**Ruling B31修正ラウンド3(項目1)**:
    `release`(basename。同一性)と取得日(日付。鮮度)は別の軸になったため、
    非ISOの`release`(例: "2026-07-01-payees")を使うテストは`source_date`を
    明示すること(省略すると`release`自体が`fromisoformat`に渡って落ちる)。
    """
    source_date = release if source_date is None else source_date
    (out_dir / "tdb2").mkdir(parents=True, exist_ok=True)
    (out_dir / "tdb2" / "nodes.dat").write_bytes(b"fake")
    tarball = out_dir / "tdb2.tar.gz"
    with tarfile.open(tarball, "w:gz") as tf:
        tf.add(out_dir / "tdb2", arcname="tdb2")
    m = build.build_manifest(
        nquads=out_dir / "kg.nq",
        tarball=tarball,
        jena_version="6.2.0",
        release=release,
        created_on="2026-08-01",
        sources={"houjin-bangou": source_date},
        graphs=[],
        tdb2_expanded_bytes=4,
        git_commit="a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
        git_dirty=False,
    )
    build.write_manifest(m, out_dir / "manifest.json")


# =============================================================================
# Step 1: 訂正・削除が置換として反映されること(carry-overを使わない基本形)
# =============================================================================


def _two_generations_with_correction_and_deletion() -> None:
    lake.save(
        "houjin-bangou", DAY1, houjin_bangou.FILENAME,
        zipped(
            zenken_row(houjin_bangou=NUM_A, name="X")
            + zenken_row(houjin_bangou=NUM_B, name="B", seq="2")
        ),
    )
    lake.save(
        "houjin-bangou", DAY2, houjin_bangou.FILENAME,
        zipped(zenken_row(houjin_bangou=NUM_A, name="Y")),
    )


def test_replacement_reflects_correction_and_deletion():
    """訂正(名称変更)が新値だけになり、削除(行消滅)が消えること。

    世代1: A(名称X)とB / 世代2: A(名称Y。訂正)のみ(Bは削除)。

    何があれば落ちるか: 置換でなく追記に退化したら旧値が残って落ちる。
    """
    _two_generations_with_correction_and_deletion()
    pipeline.run({"houjin-bangou": DAY1}, _artifact_dir(DAY1))
    pipeline.run({"houjin-bangou": DAY2}, _artifact_dir(DAY2))

    ds = _load(_artifact_dir(DAY2) / "kg.nq")
    uri_a = URIRef(uris.org_uri(NUM_A))
    uri_b = URIRef(uris.org_uri(NUM_B))
    labels_of_a = {str(o) for o in ds.objects(uri_a, SKOS.prefLabel)}
    assert labels_of_a == {"Y"}, "訂正の旧値が残っている(追記に退化)"
    assert (uri_b, None, None) not in ds, "削除が反映されていない"


def test_replacement_reflects_correction_and_deletion_even_with_previous_release_given():
    """`previous_release`を渡しても、houjin-bangou自体が変化していれば

    carry-overは働かず、通常どおり置換されること(据え置き判定が
    「変わっていないのに変わったと誤認する」方向の誤りを防ぐ)。
    """
    _two_generations_with_correction_and_deletion()
    out1 = _artifact_dir(DAY1)
    pipeline.run({"houjin-bangou": DAY1}, out1)
    _write_fake_manifest(out1, DAY1.isoformat())
    r2 = pipeline.run(
        {"houjin-bangou": DAY2}, _artifact_dir(DAY2), previous_release=DAY1.isoformat()
    )

    assert r2.carried_over == [], "内容が変わったソースが据え置きされてしまった"
    ds = _load(_artifact_dir(DAY2) / "kg.nq")
    uri_a = URIRef(uris.org_uri(NUM_A))
    uri_b = URIRef(uris.org_uri(NUM_B))
    assert {str(o) for o in ds.objects(uri_a, SKOS.prefLabel)} == {"Y"}
    assert (uri_b, None, None) not in ds


# =============================================================================
# Step 2: 差分検出(sha256一致)によるcarry-over
# =============================================================================


def test_unchanged_source_is_carried_over():
    """sha256が同じソースは再生成されず、carried_over に前リリースの

    グラフURIが載ること。

    何があれば落ちるか: 差分検出を外すと carried_over が空になり落ちる。
    """
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    out1 = _artifact_dir(DAY1)
    pipeline.run({"houjin-bangou": DAY1}, out1)
    _write_fake_manifest(out1, DAY1.isoformat())

    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    r2 = pipeline.run(
        {"houjin-bangou": DAY2}, _artifact_dir(DAY2), previous_release=DAY1.isoformat()
    )

    assert uris.graph_uri("houjin-bangou", DAY1) in r2.carried_over


def test_carried_over_graph_keeps_its_original_content_and_date():
    """据え置きグラフの内容が実際に引き継がれ(空のグラフURIだけを名乗る、

    という誤りにならない)、日付がDAY1のままであること(DAY2に再スタンプ
    しない)。
    """
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    out1 = _artifact_dir(DAY1)
    pipeline.run({"houjin-bangou": DAY1}, out1)
    _write_fake_manifest(out1, DAY1.isoformat())

    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    r2 = pipeline.run(
        {"houjin-bangou": DAY2}, _artifact_dir(DAY2), previous_release=DAY1.isoformat()
    )

    ds = _load(_artifact_dir(DAY2) / "kg.nq")
    carried_uri = URIRef(uris.graph_uri("houjin-bangou", DAY1))
    assert len(ds.graph(carried_uri)) > 0, "据え置きグラフの中身が空になっている"
    uri_a = URIRef(uris.org_uri(NUM_A))
    assert {str(o) for o in ds.objects(uri_a, SKOS.prefLabel)} == {"厚生労働省"}
    # DAY2の日付のhoujin-bangouグラフは作られない(据え置きは再スタンプしない)
    restamped_uri = URIRef(uris.graph_uri("houjin-bangou", DAY2))
    assert len(ds.graph(restamped_uri)) == 0, "据え置きなのにDAY2の日付で再生成されている"
    # report.sources にも旧日付(DAY1)が載る(「実際に入っているもの」原則)
    assert r2.sources["houjin-bangou"] == DAY1.isoformat()


def test_carry_over_is_not_used_when_previous_release_is_omitted():
    """`previous_release`を渡さない既定の呼び出しでは、carry-overを一切使わないこと

    (既存の全呼び出し元の振る舞いに影響しないための後方互換性)。
    """
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    pipeline.run({"houjin-bangou": DAY1}, _artifact_dir(DAY1))

    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    r2 = pipeline.run({"houjin-bangou": DAY2}, _artifact_dir(DAY2))

    assert r2.carried_over == []
    assert r2.sources["houjin-bangou"] == DAY2.isoformat()


def test_carry_over_raises_when_the_previous_release_artifact_is_missing():
    """`previous_release`が指す成果物(kg.nq)が実在しなければ、黙って据え置きを

    諦めるのではなく例外にすること(呼び出し側の「前リリースが存在する」
    という主張と矛盾するため)。
    """
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    # DAY1のリリースそのものは作らない(kg.nqが存在しない状態を模す)

    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    with pytest.raises(FileNotFoundError, match="前リリース"):
        pipeline.run(
            {"houjin-bangou": DAY2}, _artifact_dir(DAY2), previous_release=DAY1.isoformat()
        )


# =============================================================================
# Ruling B31修正ラウンド3(項目1): B31の部分適用を解消する。`previous_release`
# は成果物ディレクトリの任意のbasenameを受け付け、日付形式である必要はない
# =============================================================================


def test_carry_over_works_when_the_previous_release_name_is_not_an_iso_date():
    """`previous_release`にISO日付形式ではないbasenameを渡してもcarry-over

    が機能すること。

    B31は「リリースの同一性=成果物ディレクトリのbasename」と決めたが、
    `previous_release`(参照側)が`datetime.date`型のままだと、日付形式
    ではない名前(`2026-08-26-payees`等。同日に複数リリースを作るときの
    区別に使う想定の名前)を実際に付けても、それをcarry-overの入力には
    渡せない——B31が作った同一性空間の一部にしか、参照側が追従していない
    「部分適用」になる。

    何があれば落ちるか: `previous_release`を再び`datetime.date`型の
    パラメータに戻す(または内部で`.isoformat()`/`fromisoformat`を要求する
    実装に戻す)と、非ISO形式の`non_iso_name`を渡すこの呼び出し自体が
    `AttributeError`(`str`に`.isoformat()`が無い)または`ValueError`
    (`fromisoformat`が非ISO文字列を拒否)で落ちる。
    """
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    non_iso_name = "not-an-iso-date"
    out1 = Path(get_settings().artifact_dir) / non_iso_name
    pipeline.run({"houjin-bangou": DAY1}, out1)
    # source_dateは明示する——releaseがもう日付ではないため(上記docstring参照)
    _write_fake_manifest(out1, non_iso_name, source_date=DAY1.isoformat())

    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    r2 = pipeline.run(
        {"houjin-bangou": DAY2}, _artifact_dir(DAY2), previous_release=non_iso_name
    )

    assert uris.graph_uri("houjin-bangou", DAY1) in r2.carried_over, (
        "basenameが非ISO形式の前リリースからcarry-overできていない"
        "(B31の部分適用が残っている)"
    )


def test_carry_over_rejects_a_previous_release_name_containing_a_path_separator():
    r"""`previous_release`にディレクトリの区切り文字(`/`・`\`)が含まれる場合、

    パス結合結果がどうなるかに関わらず即座に`ValueError`にすること。

    `previous_release`は成果物ディレクトリの**basename**という契約であり、
    パスの断片(例: "../2026-08-25"や"sub/dir")を許すと、成果物ディレクトリ
    の外を指せてしまう(意図しないパストラバーサル)。basenameという契約を
    型ではなく実行時チェックで守る(項目1で`str`型に緩めた分だけ、この
    チェックの必要性が増した)。

    何があれば落ちるか: `_previous_release_manifest`冒頭の`"/" in previous_release
    or "\\" in previous_release`チェックを削除すると、この呼び出しは
    `ValueError`ではなく`FileNotFoundError`(存在しないパスのmanifest.jsonを
    探しに行く)で落ちるようになり、`match="区切り文字"`のアサーションが
    合致しなくなる。
    """
    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    with pytest.raises(ValueError, match="区切り文字"):
        pipeline.run(
            {"houjin-bangou": DAY2},
            _artifact_dir(DAY2),
            previous_release="../2026-08-25",
        )


def test_carry_over_rejects_a_previous_release_name_containing_a_windows_drive_relative_colon():
    """最終レビュー観察O11。`previous_release`にコロン(`:`)が含まれる場合も

    `ValueError`にすること——`/`・`\\`だけではWindowsのドライブ相対パス
    (`"C:foo"`)を弾けない。

    `artifact_dir`の既定値`"data/artifact"`(相対パス)を使う実運用の
    構成では、`Path("data/artifact") / "C:foo"`はWindowsでは結合を無視
    して`WindowsPath('C:foo')`になり、`artifact_dir`の外を指してしまう
    (スタンドアロンで実行して確認済み)。**このテスト自身の`tmp_env`
    フィクスチャは`artifact_dir`にtmp_pathベースの絶対パスを使うため
    (テストの分離のため)、同一ドライブの絶対パス同士の結合になり実際の
    エスケープは再現しない**——ガード無効時は`artifact_dir`配下の
    存在しない`foo`サブディレクトリへの`FileNotFoundError`という
    地味な形で素通りが露見する(実運用の相対パス構成での脆弱性そのものは
    これとは別に実在する。上記コメント参照)。

    何があれば落ちるか: ガードの条件から`":" in previous_release`を外すと、
    `"C:foo"`は`/`も`\\`も含まないため素通りし、この呼び出しは
    `ValueError`(`match="区切り文字"`)ではなく
    `FileNotFoundError`(前リリースのmanifest.jsonが見つからない)で
    落ちるようになる。
    """
    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    with pytest.raises(ValueError, match="区切り文字"):
        pipeline.run(
            {"houjin-bangou": DAY2},
            _artifact_dir(DAY2),
            previous_release="C:foo",
        )


def test_carry_over_rejects_a_previous_release_whose_manifest_sources_date_is_not_parseable():
    """前リリースの`manifest.sources`の値がISO日付として読めない場合、

    `ValueError`にすること(黙ってcarry-overを諦めるのではなく)。

    項目1の設計変更により、carry-over判定は`lake.latest_before`の探索では
    なく前リリース自身の`manifest.sources`を直接信頼するようになった
    (`_previous_release_sources`)。信頼する値が壊れていた場合
    (手動編集・別ツールでの生成・将来の形式変更など)、`datetime.date`
    としてパースできない値を握ったまま処理を進める(例: 型エラーとして
    別の場所で不明瞭に落ちる、または黙って据え置きを諦める)のではなく、
    ここで明示的に`ValueError`にする。

    何があれば落ちるか: `_previous_release_sources`の`try/except ValueError`
    ブロック(未変換の`datetime.date.fromisoformat`呼び出しの例外を再送する
    部分)を削除して素通りさせると、この呼び出しは`ValueError`
    (`match="日付として読めない"`)ではなく元の`fromisoformat`が出す
    素の`ValueError`(前リリース名の文脈が無いメッセージ)、または
    `_previous_release_sources`の呼び出し元での別の失敗になり、
    このテストの`match`アサーションが合致しなくなる。
    """
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    out1 = _artifact_dir(DAY1)
    pipeline.run({"houjin-bangou": DAY1}, out1)
    _write_fake_manifest(out1, DAY1.isoformat(), source_date="not-a-date")

    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    with pytest.raises(ValueError, match="日付として読めない"):
        pipeline.run(
            {"houjin-bangou": DAY2},
            _artifact_dir(DAY2),
            previous_release=DAY1.isoformat(),
        )


# =============================================================================
# Task 10修正ラウンド1(Ruling B26): manifest.jsonをコミット印として要求し、
# kg.nqの完全性(sha256)・内容(SHACL再検証)を照合する。
# task-10-review.md要修正1の実測[a]/[b]を正のコントロールのテストにする。
# =============================================================================


def test_carry_over_rejects_a_previous_release_that_was_never_shipped():
    """kg.nqはあるがmanifest.jsonが無い(=enforce_release_gateで落ちて出荷を

    拒否されたリリース)を、carry-overの据え置き元として黙って受理しない
    こと(task-10-review.md要修正1の実測[a])。

    `build.sh`は`run()`がkg.nqを書いた**後**に`enforce_release_gate`を呼び、
    落ちれば`set -e`でmanifest作成に進まない——「kg.nqはあるがmanifest.json
    は無い」は実運用で必ず生じる状態であり、kg.nqの存在だけを「前リリースが
    実在する」証拠にしてはならない。
    """
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    out1 = _artifact_dir(DAY1)
    pipeline.run({"houjin-bangou": DAY1}, out1)
    # manifest.jsonは書かない(ゲートで落ちた=出荷拒否されたリリースを模す)
    assert not (out1 / "manifest.json").exists()

    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    # **`match`は「出荷」で固定する(`manifest`ではない)。** manifest.jsonが
    # 存在しない場合、専用の検査を外しても`build.read_manifest`が
    # `Path.read_text()`経由で素の`FileNotFoundError`(メッセージに
    # パス文字列として"manifest.json"を含む)を投げてしまい、`match="manifest"`
    # では専用の検査の有無を区別できない(空振りの実例。壊し確認で発見)。
    # 「出荷」はこのモジュールの専用メッセージにしか出現しない語
    with pytest.raises(FileNotFoundError, match="出荷"):
        pipeline.run(
            {"houjin-bangou": DAY2}, _artifact_dir(DAY2), previous_release=DAY1.isoformat()
        )


def test_carry_over_rejects_a_previous_release_whose_kg_nq_no_longer_matches_the_manifest():
    """manifestに記録されたkg.nqのsha256と実際のkg.nqが一致しない

    (保管中に書き換えられた)場合、carry-overの供給元として拒否すること
    (task-10-review.md要修正1の実測[b]の一部)。
    """
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    out1 = _artifact_dir(DAY1)
    pipeline.run({"houjin-bangou": DAY1}, out1)
    _write_fake_manifest(out1, DAY1.isoformat())  # 正しい内容に対するmanifest

    # 保管中の書き換えを模す(manifestは更新しない)
    with (out1 / "kg.nq").open("a", encoding="utf-8") as f:
        f.write("# tampered\n")

    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    with pytest.raises(ValueError, match="sha256"):
        pipeline.run(
            {"houjin-bangou": DAY2}, _artifact_dir(DAY2), previous_release=DAY1.isoformat()
        )


_FULLWIDTH_DIGITS = str.maketrans("0123456789", "０１２３４５６７８９")


def test_carry_over_declines_when_the_carried_graph_fails_shacl_revalidation():
    """manifestのsha256はkg.nqと一致するが、内容がSHACL不適合(全角13桁の

    法人番号。裁定B22/F-3が禁じた形)なグラフは、carry-overの合流前に
    再検証で弾かれ、通常どおり再生成すること(task-10-review.md要修正1の
    実測[b]の中心。Ruling B26(b): 「carry-overは再生成の省略であって検証の
    省略ではない」)。

    manifestのsha256照合(tier 1)だけでは、**破損した内容に対してmanifestが
    正しく再計算された場合**(このテストが模す状況。スキーマ進化などで
    ハッシュだけでは検出できない劣化の代理)を検出できない——SHACL再検証
    (tier 3)が独立の防御であることを直接確認する。

    何があれば落ちるか: `run()`から`_validate_carried_graphs`の呼び出しを
    外す(単純な`_extract_graphs_from_kg_nq`呼び出しに戻す)と、壊れた
    houjinBangouの値がそのまま出荷される。
    """
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    out1 = _artifact_dir(DAY1)
    pipeline.run({"houjin-bangou": DAY1}, out1)

    # 前リリースのkg.nqを破損させる(B22/F-3が禁じた全角13桁の法人番号)
    kg_path = out1 / "kg.nq"
    original = kg_path.read_text(encoding="utf-8")
    corrupted = original.replace(f'"{NUM_A}"', f'"{NUM_A.translate(_FULLWIDTH_DIGITS)}"')
    assert corrupted != original, "置換対象(houjinBangouの値)が見つからなかった"
    kg_path.write_text(corrupted, encoding="utf-8")
    # manifestは破損**後**の内容に対して書く(sha256照合だけでは検出できない
    # 劣化を模す——tier 3の独立性を確認するため)
    _write_fake_manifest(out1, DAY1.isoformat())

    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    r2 = pipeline.run(
        {"houjin-bangou": DAY2}, _artifact_dir(DAY2), previous_release=DAY1.isoformat()
    )

    assert r2.carried_over == [], "SHACL不適合のグラフがcarry-overされてしまった"
    assert r2.sources["houjin-bangou"] == DAY2.isoformat()
    ds = _load(_artifact_dir(DAY2) / "kg.nq")
    uri_a = URIRef(uris.org_uri(NUM_A))
    assert {str(o) for o in ds.objects(uri_a, SKOS.prefLabel)} == {"厚生労働省"}, (
        "再生成されたはずのグラフに内容が無い(破損した据え置きが混入した疑い)"
    )


def test_carried_over_graph_is_counted_in_graphs_validated():
    """据え置きグラフもSHACL再検証を受けるため、graphs_validatedに数えられる

    こと(task-10-review.md観察4)。据え置きグラフはgraphsには載るが
    validate_datasetを通らないためgraphs_validatedに数えられない、という
    ズレをRuling B26(b)のSHACL再検証で解消する。
    """
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    out1 = _artifact_dir(DAY1)
    r1 = pipeline.run({"houjin-bangou": DAY1}, out1)
    _write_fake_manifest(out1, DAY1.isoformat())

    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    r2 = pipeline.run(
        {"houjin-bangou": DAY2}, _artifact_dir(DAY2), previous_release=DAY1.isoformat()
    )

    assert uris.graph_uri("houjin-bangou", DAY1) in r2.carried_over
    # r1: houjin-bangou・ministry-codes・provenanceの3グラフを検証。
    # r2: houjin-bangouは検証をスキップして据え置くが、ministry-codes・
    # provenanceは常に再計算するので同じ2件+据え置き分の再検証1件=3件
    # (「据え置きグラフの検証が数から漏れる」というズレが無ければ、世代間で
    # 一致するはず)
    assert r2.graphs_validated == r1.graphs_validated, (
        "据え置きグラフの検証件数が世代1の検証件数と一致しない"
        f"(r1={r1.graphs_validated}, r2={r2.graphs_validated})"
    )


# =============================================================================
# Task 10修正ラウンド1(観察3): 同一日付ディレクトリに複数ファイルがあっても、
# carry-overの差分検出がファイル名で正しく絞り込むこと
# =============================================================================


def test_carry_over_date_lookup_is_not_confused_by_a_same_date_sidecar_file():
    """据え置き判定(`_previous_date_if_unchanged`)が、同じ日付ディレクトリに

    別ファイルが増えても、正しいファイル名(`houjin_bangou.FILENAME`)のsha256
    だけを比較すること(task-10-review.md観察3)。

    何があれば落ちるか: ファイル名で絞らずソート順(辞書順で最後)のsha256を
    拾う実装に戻すと、「zenken.zipより辞書順で後に来るサイドカー」の存在で
    サイドカーの方を前リリース側の比較対象に選んでしまい、本来は不変
    (=据え置き対象)であるはずのzenken.zip自身の比較が無関係なサイドカーの
    差分に汚染されて、据え置きが誤って諦められる。

    **Ruling B31修正ラウンド3の注記**: この判定は以前`lake.latest_before`で
    「前リリース日付以前の直近スナップショット」を探索してから、その日付で
    ファイル名を再絞り込みしていた(`max(key=path.name)`のソート順に依存する
    経路)。修正後は前リリースのmanifest.sourcesが記録する日付を直接使うため
    探索そのものが無くなったが、**ファイル名で絞り込む**という本テストが
    固定する性質自体は変わらず必要(サイドカーが同じ日付ディレクトリに
    あれば、ファイル名を見ない限りどちらの実装でも誤って拾いうる)。
    """
    # "zzz..."はzenken.zipより辞書順で後に来る(list_snapshotsはmeta.jsonの
    # globをsortedで返す——pipeline.py:640-649の既存コメントと同じ罠を、
    # houjin-bangouのcarry-over判定側で再現する)
    lake.save("houjin-bangou", DAY1, "zzz-unrelated-sidecar.zip", b"sidecar content DAY1")
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    out1 = _artifact_dir(DAY1)
    pipeline.run({"houjin-bangou": DAY1}, out1)
    _write_fake_manifest(out1, DAY1.isoformat())

    # DAY2: zenken.zip本体は不変(sha256一致)。サイドカーは内容が違う
    # (異なるsha256)——無関係な変化がzenken.zip自身の据え置き判定に
    # 影響してはならない
    lake.save("houjin-bangou", DAY2, "zzz-unrelated-sidecar.zip", b"sidecar content DAY2 different")
    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    r2 = pipeline.run(
        {"houjin-bangou": DAY2}, _artifact_dir(DAY2), previous_release=DAY1.isoformat()
    )

    assert uris.graph_uri("houjin-bangou", DAY1) in r2.carried_over, (
        "本体(zenken.zip)は不変なのに、無関係なサイドカーの差分で"
        "据え置きが誤って諦められた"
    )


def test_carry_over_falls_back_to_regeneration_when_the_previous_graph_is_absent():
    """前リリースの成果物(kg.nq)は実在するが、該当グラフが無い

    (例: 隔離されていた)場合は、据え置きを諦めて通常どおり再生成すること
    (黙って空にしない。このタスクで踏みやすい欠陥の型2)。
    """
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    # DAY1のリリースは作るが、houjin-bangouのグラフを含まない空のkg.nqにする
    # (「前リリースは存在するが該当グラフが無い」を直接作る)
    out1 = _artifact_dir(DAY1)
    out1.mkdir(parents=True)
    (out1 / "kg.nq").write_text("", encoding="utf-8")
    _write_fake_manifest(out1, DAY1.isoformat())

    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    r2 = pipeline.run(
        {"houjin-bangou": DAY2}, _artifact_dir(DAY2), previous_release=DAY1.isoformat()
    )

    assert r2.carried_over == [], "前リリースに該当グラフが無いのに据え置きした"
    assert r2.sources["houjin-bangou"] == DAY2.isoformat()
    ds = _load(_artifact_dir(DAY2) / "kg.nq")
    uri_a = URIRef(uris.org_uri(NUM_A))
    assert {str(o) for o in ds.objects(uri_a, SKOS.prefLabel)} == {"厚生労働省"}, (
        "再生成されたはずのグラフに内容が無い"
    )


def test_carry_over_ignores_unrelated_graphs_present_in_the_previous_kg_nq():
    """前リリースのkg.nqに、carry-over対象ではない別グラフ(全法人グラフ相当)

    が混在していても、(a) 本来の据え置き対象(houjin-bangou)は正しく機能し、
    (b) その無関係なグラフの内容は新リリースに復活しないこと。

    advisorレビュー指摘: 前リリースのkg.nqを丸ごとrdflibの`Dataset`にロード
    する実装だと、RS入りの前リリースに実際に含まれるhoujin-bangou-all
    (約3,500万行。`run()`の`include_all_corporations`処理がkg.nqの末尾に
    そのまま連結する)を読み込んでメモリが破綻する(R19/R21)。修正後は
    対象グラフだけを1パスの行フィルタで拾うため規模に強いが、**この規模を
    テストで再現するのは重すぎる**。代わりに、対象外のグラフが混在した
    小さいkg.nqで、carry-overの結線そのもの(a)と、無関係な内容が新
    リリースに残らないこと(b)を直接固定する。

    **何があれば落ちるか(壊し確認済み)**: (a)は、`run()`内の抽出呼び出し
    (`_extract_graphs_from_kg_nq`の呼び出し)を外すと落ちる(carry-overの
    結線が本当に効いているかを確認する)。(b)は現在の実装では`run()`側が
    グラフURIを指定した個別取得(`carried_graphs.get(exact_uri)`)しか
    しないため、`_extract_graphs_from_kg_nq`単体のフィルタを壊しても
    (a)(b)いずれも失敗しない(=多重の防御になっている。実際に3パターン
    壊して確認した)。それでも(b)は、将来`run()`側が`carried_graphs`を
    キー指定せず丸ごと使う書き方に変わった場合の回帰を検知する——導入前は
    どのテストも保証していなかった性質という点に変わりはない。
    """
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    out1 = _artifact_dir(DAY1)
    pipeline.run({"houjin-bangou": DAY1}, out1)

    # 前リリースのkg.nqに、carry-over対象外の別グラフ(全法人グラフ相当)を
    # 手動で追記する。run()が実際に行っている追記(houjin-bangou-all.nqを
    # kg.nqの末尾にそのまま連結する)を模す
    unrelated_graph = uris.graph_uri("houjin-bangou-all", DAY1)
    unrelated_org = uris.org_uri("9000000000001")
    with (out1 / "kg.nq").open("a", encoding="utf-8", newline="\n") as f:
        f.write(f'<{unrelated_org}> <{SKOS.prefLabel}> "無関係法人" <{unrelated_graph}> .\n')
    # manifestは無関係グラフを追記した**後**の内容に対して書く——実際の
    # include_all_corporations=Trueの前リリースも、houjin-bangou-allを
    # 含めたkg.nq全体に対してmanifestを作る(scripts/build.sh参照)ので、
    # この順序がその実運用を正しく模す
    _write_fake_manifest(out1, DAY1.isoformat())

    lake.save("houjin-bangou", DAY2, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    r2 = pipeline.run(
        {"houjin-bangou": DAY2}, _artifact_dir(DAY2), previous_release=DAY1.isoformat()
    )

    # (a) 本来の据え置き対象は無関係グラフの混在に関わらず正しく機能する
    assert uris.graph_uri("houjin-bangou", DAY1) in r2.carried_over
    ds = _load(_artifact_dir(DAY2) / "kg.nq")
    uri_a = URIRef(uris.org_uri(NUM_A))
    assert {str(o) for o in ds.objects(uri_a, SKOS.prefLabel)} == {"厚生労働省"}

    # (b) 無関係グラフの内容は新リリースに復活しない(carry-over対象の
    # 範囲を超えて何でも引き継ぐ実装になっていないことの確認)。
    # **グラフを指定せず主語で見る**(`ds.graph(URIRef(unrelated_graph))`
    # だけだと、無関係な内容が誤って別のグラフURI——例えばhoujin-bangou自身
    # の据え置きグラフ——に取り込まれて残るような壊れ方を見逃す)
    assert (URIRef(unrelated_org), None, None) not in ds, (
        "carry-over対象外のグラフの内容が(どのグラフかを問わず)新リリースに残っている"
    )
    assert len(ds.graph(URIRef(unrelated_graph))) == 0, (
        "carry-over対象外のグラフが新リリースに復活している"
    )


# =============================================================================
# 依存関係つきcarry-over(advisorレビュー指摘: 自ソースのsha256だけでは
# 不健全。他ソースへの依存を経由して変化が伝播することを固定する)
# =============================================================================


def test_carry_over_declines_for_egov_law_when_houjin_bangou_changed():
    """egov-lawグラフ自身のバイト列は不変でも、依存元(houjin-bangou)が

    変化していれば据え置きしないこと。egov-lawのjurisdiction解決は
    houjin-bangou由来のministriesに依存するため、houjin-bangouの変化が
    jurisdiction解決結果を変える可能性がある(自ソースのsha256だけを見る
    判定は不健全というadvisorレビュー指摘の再現)。
    """
    from jgkg.connectors import egov_law

    law_bytes = _egov_laws_jsonl()
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    lake.save("egov-law", DAY1, egov_law.FILENAME, law_bytes)
    # C-3: egov-lawを含むリリースはegov-law-dataも必須(pipeline.pyのガード)。
    # このテストの主眼は依存判定(houjin-bangouの変化)であり、対応表の
    # 内容自体は問わないので空(0データ行)で足りる
    _save_minimal_egov_law_data_snapshot(DAY1)
    out1 = _artifact_dir(DAY1)
    pipeline.run({"houjin-bangou": DAY1, "egov-law": DAY1, "egov-law-data": DAY1}, out1)
    _write_fake_manifest(out1, DAY1.isoformat())

    # houjin-bangouは変化させる。egov-lawは同一バイト列のまま
    lake.save(
        "houjin-bangou", DAY2, houjin_bangou.FILENAME,
        zipped(zenken_row(houjin_bangou=NUM_A, name="変更後の名称")),
    )
    lake.save("egov-law", DAY2, egov_law.FILENAME, law_bytes)
    _save_minimal_egov_law_data_snapshot(DAY2)
    r2 = pipeline.run(
        {"houjin-bangou": DAY2, "egov-law": DAY2, "egov-law-data": DAY2},
        _artifact_dir(DAY2),
        previous_release=DAY1.isoformat(),
    )

    assert uris.graph_uri("egov-law", DAY1) not in r2.carried_over, (
        "依存元(houjin-bangou)が変化したのにegov-lawが据え置きされた"
    )
    assert r2.sources["egov-law"] == DAY2.isoformat()


def _egov_laws_jsonl() -> bytes:
    import json

    law = {
        "law_info": {
            "law_id": "323M60000100010",
            "law_num": "昭和二十三年厚生省令第十号",
            "law_num_type": "MinisterialOrdinance",
            "law_type": "MinisterialOrdinance",
            "promulgation_date": "1948-01-01",
        },
        "revision_info": None,
        "current_revision_info": {
            "law_title": "テスト用の省令", "abbrev": None, "repeal_status": "None",
        },
    }
    return (json.dumps(law, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")


def _save_minimal_egov_law_data_snapshot(date: datetime.date) -> None:
    """C-3: 空の対応表(0データ行)のegov-law-dataスナップショット。

    このファイルのテストはcarry-over/依存判定そのものを見ており、
    AbolishedGovernmentOrganの解決内容は問わない(このテストの法令
    「昭和二十三年厚生省令第十号」は旧省庁名を使っているが、対応表が
    空なので従来通りOLD_MINISTRYのまま——resolved_abolishedへの分類は
    test_transform_law.py/test_pipeline.pyの専用テストが検査する)。
    """
    import json

    from jgkg.connectors import egov_law
    from jgkg.transform.ministry_succession import SUCCESSION_LAW_ID

    law_data = {
        "law_info": {"law_id": SUCCESSION_LAW_ID},
        "revision_info": {"amendment_enforcement_date": "2001-01-06", "amendment_law_id": None},
        "law_full_text": {"tag": "Law", "attr": {}, "children": [
            {"tag": "LawBody", "attr": {}, "children": [
                {"tag": "TableStruct", "attr": {}, "children": [
                    {"tag": "Table", "attr": {}, "children": [
                        {"tag": "TableRow", "attr": {}, "children": [
                            {"tag": "TableColumn", "attr": {}, "children": ["従前の府省"]},
                            {"tag": "TableColumn", "attr": {}, "children": ["新府省"]},
                        ]},
                    ]},
                ]},
            ]},
        ]},
    }
    lake.save(
        egov_law.LAW_DATA_SOURCE_ID, date, egov_law.law_data_filename(SUCCESSION_LAW_ID),
        json.dumps(law_data, ensure_ascii=False).encode("utf-8"),
    )


# =============================================================================
# Step 3(検証ゲート): 検証に失敗したら成果物が作られず、前リリースが残ること(§6.4)
# =============================================================================


def run_and_gate(fetched_on, out_dir, **kwargs):
    """build.sh の要点(run→enforce_release_gate)だけを再現する薄いヘルパー。"""
    report = pipeline.run(fetched_on, out_dir, **kwargs)
    pipeline.enforce_release_gate(report)
    return report


def test_failed_validation_keeps_previous_release():
    """世代2が検証に落ちたら成果物が作られず、世代1が残ること(§6.4)。

    何があれば落ちるか: 隔離ゲートを exit 0 に緩めると落ちる(C2の再発検知)。
    """
    lake.save("houjin-bangou", DAY1, houjin_bangou.FILENAME, UNCHANGED_HOUJIN_BANGOU_BYTES)
    out1 = _artifact_dir(DAY1)
    pipeline.run({"houjin-bangou": DAY1}, out1)
    _write_fake_manifest(out1, DAY1.isoformat())

    lake.save(
        "houjin-bangou", DAY2, houjin_bangou.FILENAME,
        zipped(zenken_row(name="重複1") + zenken_row(name="重複2", seq="2")),
    )
    with pytest.raises(pipeline.QuarantineNotEmptyError):
        run_and_gate({"houjin-bangou": DAY2}, _artifact_dir(DAY2))

    assert (out1 / "manifest.json").exists(), "前リリースの成果物が失われている"
