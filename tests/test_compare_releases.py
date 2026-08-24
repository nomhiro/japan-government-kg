"""Task 11修正ラウンド3 項目4: `scripts/compare_releases.py`(裁定B33)の回帰テスト。

裁定B33の目的は「§5の核心証拠(グラフ別ソート済みsha256突合)を証拠として
恒久化する」ことだった。実行結果の書き起こしと壊し確認の記録だけでは、
**スクリプト自身が将来書き換わって腐っても気づかない**(コミットされたテストが
無いと、腐敗を検出する仕組みがドキュメントの目視確認にしか無くなる)。

`scripts/`はpytestの`pythonpath`(pyproject.toml)に含まれないため、
`importlib`でファイルパスから直接読み込む(`tests/test_schema_consistency.py`
の`spec_from_file_location`と同じ手法)。
"""
import importlib.util
import tarfile
from pathlib import Path
from types import ModuleType

from jgkg import build

# base_uri.pyの整合検査(tests/*.pyも対象)に引っかからないよう、このプロジェクト
# 自身のベースURI配下のダミーURIを使う(外部ホストの許可リストに追加する話では
# ない——このテストが本物のグラフ・語彙を指すわけではないため)
BASE = "https://jgkg.norr-tech.com"
G1 = f"{BASE}/graph/test-compare-releases-g1"
STRAY_GRAPH = f"{BASE}/graph/test-compare-releases-g-stray"

LINE_1 = f'<{BASE}/id/test/s1> <{BASE}/def/test/p> "v1" <{G1}> .'
LINE_2 = f'<{BASE}/id/test/s2> <{BASE}/def/test/p> "v2" <{G1}> .'
LINE_3 = f'<{BASE}/id/test/s3> <{BASE}/def/test/p> "v3" <{G1}> .'
STRAY_LINE = f'<{BASE}/id/test/s4> <{BASE}/def/test/p> "stray" <{STRAY_GRAPH}> .'


def _load_compare_releases() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "compare_releases.py"
    spec = importlib.util.spec_from_file_location("compare_releases", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


COMPARE_RELEASES = _load_compare_releases()


def _write_release(out_dir: Path, lines: list[str]) -> None:
    """最小限のkg.nq + manifest.jsonを持つ「リリース」を1つ作る。

    `build.build_manifest`が実際に`nquads`引数のファイルを読んでsha256/行数を
    計算するため、書いたkg.nqの内容がそのままmanifestに反映される。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    kg_nq = out_dir / "kg.nq"
    kg_nq.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tarball = out_dir / "kg.tar.gz"
    with tarfile.open(tarball, "w:gz") as tf:
        tf.add(kg_nq, arcname="kg.nq")
    m = build.build_manifest(
        nquads=kg_nq, tarball=tarball, jena_version="6.2.0",
        release=out_dir.name, sources={}, graphs=[G1], tdb2_expanded_bytes=1,
    )
    build.write_manifest(m, out_dir / "manifest.json")


def test_same_content_in_a_different_line_order_is_judged_same(tmp_path):
    """行の並び順が違うだけの2リリースはSAME判定(exit 0)になること。

    carry-over経路と新規生成経路でrdflib Datasetへの挿入順序が異なるため、
    kg.nqのバイト列は変わるがトリプルの集合は変わらない——これが裁定B33の
    核心の主張(§5)。グラフ別にソートしてから比較することでこれを確認する。
    """
    release_a = tmp_path / "release-a"
    release_b = tmp_path / "release-b"
    _write_release(release_a, [LINE_1, LINE_2, LINE_3])
    _write_release(release_b, [LINE_3, LINE_1, LINE_2])  # 並び順だけ違う

    assert COMPARE_RELEASES.main([str(release_a), str(release_b)]) == 0


def test_a_residual_line_outside_any_declared_graph_fails_nonzero(tmp_path):
    """manifestが列挙するどのグラフにも属さない行が1件でもあれば、非0終了すること。

    グラフ数の一致だけでは、あるグラフの行が別の名前(または抽出できない形)で
    紛れ込むような取りこぼしを見逃す——残余行の検査がその防御を担う。

    何があれば落ちるか(壊し確認): `scripts/compare_releases.py`の`main()`内の
    残余行チェック(`if residual_count_a or residual_count_b or mismatches:`)
    を`if False:`に書き換えると、この行の存在を無視してSAME/exit 0を返す
    ようになり、このテストの`== 1`アサーションが落ちる(実際に書き換えて
    確認した記録はtask-11-fix-round-3-report.md参照)。
    """
    release_a = tmp_path / "release-a"
    release_b = tmp_path / "release-b"
    _write_release(release_a, [LINE_1, LINE_2, LINE_3])
    _write_release(release_b, [LINE_1, LINE_2, LINE_3, STRAY_LINE])

    assert COMPARE_RELEASES.main([str(release_a), str(release_b)]) == 1
