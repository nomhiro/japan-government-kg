"""B-1: リリースをGitHub Releasesへ公開する仕組み。

**GitHub Actionsのワークフローにしていない理由はこのモジュールではなく
`scripts/publish-release.sh`のコメントに書く**(利用者がまず読むのはあちら)。

公開前の検査が本体である: manifest.jsonが記録しているsha256と、実物の
`tdb2.tar.gz`・`kg.nq`のsha256が一致することを確かめ、一致しなければ
公開しない(`verify_release_assets`)。既定はdry-runで、`--publish`を
明示しない限り`gh`を一切呼ばない。

出典表示とライセンスは`sources.py`から導出する(手書きしない)。
このプロジェクトで6件目になる「導出すべき値を手書きする」型への対処
(先行5件: 公開物検査のモジュール一覧 / 乗数 / 除外リスト / エラー文言中の
パス / CQ8の日付 / `ministry-codes`の日付検査)。
"""
import argparse
import gzip
import hashlib
import shutil
import subprocess
from pathlib import Path

from jgkg import build, sources
from jgkg.serve import TARBALL_NAME

KG_NQ_NAME = "kg.nq"
KG_NQ_GZ_NAME = "kg.nq.gz"
NOTES_NAME = "RELEASE_NOTES.md"


def verify_release_assets(release_dir: Path) -> build.Manifest:
    """3資産の存在と、manifestが記録するsha256・releaseとの一致を確かめる。

    **一致しない/欠けている場合は公開してはならない**(B-1ブリーフの本題)。
    ここで検査した`Manifest`をそのまま返す(呼び出し側が同じファイルを
    もう一度読み直さないため——読み直すと、検査と使用の間でファイルが
    書き換わる余地〔TOCTOU〕がわずかに生まれる)。
    """
    manifest_path = release_dir / build.MANIFEST_NAME
    tarball_path = release_dir / TARBALL_NAME
    nquads_path = release_dir / KG_NQ_NAME
    for label, path in (
        ("manifest.json", manifest_path),
        ("tdb2.tar.gz", tarball_path),
        ("kg.nq", nquads_path),
    ):
        if not path.exists():
            raise FileNotFoundError(
                f"公開に必要な資産が無い: {path}({label})。"
                " build.sh で作ったリリースディレクトリを渡しているか確認する"
            )

    manifest = build.read_manifest(manifest_path)

    # Ruling B31: リリースの識別子はディレクトリのbasename。manifest.release
    # と食い違うのは「どのディレクトリの内容を公開しようとしているか」が
    # 自己矛盾している状態であり、公開してはならない。
    if manifest.release != release_dir.name:
        raise ValueError(
            f"manifestのrelease({manifest.release!r})とディレクトリ名"
            f"({release_dir.name!r})が一致しない(Ruling B31)。"
            " どちらが正しいか確認してから公開する"
        )

    actual_tarball_sha256 = build.file_sha256(tarball_path)
    if actual_tarball_sha256 != manifest.sha256:
        raise ValueError(
            f"tdb2.tar.gzのsha256がmanifestと一致しない: "
            f"manifest={manifest.sha256} actual={actual_tarball_sha256}。"
            " 転送・保管中に壊れた疑いがある。壊れた資産を公開してはならない"
        )

    # **旧形式(manifest_version<3)のmanifestはnquads_sha256を持たない。**
    # 「照合できない」を「合格」とみなさない——「既定は止まる側」。
    if manifest.nquads_sha256 is None:
        raise ValueError(
            "manifestにnquads_sha256が無い(旧形式のmanifest。"
            " manifest_version<3)。kg.nqの完全性を照合できないため公開できない"
        )
    actual_nquads_sha256 = build.file_sha256(nquads_path)
    if actual_nquads_sha256 != manifest.nquads_sha256:
        raise ValueError(
            f"kg.nqのsha256(nquads_sha256)がmanifestと一致しない: "
            f"manifest={manifest.nquads_sha256} actual={actual_nquads_sha256}。"
            " 転送・保管中に壊れた疑いがある。壊れた資産を公開してはならない"
        )
    return manifest


def _sha256_of_gzip_content(gz_path: Path) -> str:
    """gzipファイルを展開した**内容**のsha256(圧縮バイト列自体ではない)。"""
    h = hashlib.sha256()
    with gzip.open(gz_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def make_kg_nq_gz(release_dir: Path, manifest: build.Manifest) -> tuple[Path, str, int]:
    """`kg.nq`をgzip圧縮した`kg.nq.gz`を同じディレクトリに作る(**元のkg.nqは消さない**)。

    gzipは非決定的なことがある(同じ内容でも実装・オプションでバイト列が
    変わりうる)ため、`kg.nq.gz`自身のsha256はmanifestに書き戻さず、
    呼び出し側(リリースノート)に渡すだけにする(B-1ブリーフの指示)。

    **2回目以降の呼び出しは既存の`kg.nq.gz`を再利用する**(B31の「既定は
    止まる側」と同じ精神。dry-runを何度実行しても壊れたビルドの残骸のように
    無条件に上書きし続けない)。ただし**再利用する前に、その`kg.nq.gz`を
    展開した内容が今の`kg.nq`(manifest.nquads_sha256で照合)と一致することを
    確かめる**——古い`kg.nq.gz`が残っているのに気付かず、更新された`kg.nq`と
    食い違うものを配ってしまう事故を防ぐ。食い違っていたら例外にする
    (黙って上書きもしない。手動で削除してから再実行させる)。
    """
    nquads_path = release_dir / KG_NQ_NAME
    gz_path = release_dir / KG_NQ_GZ_NAME

    if gz_path.exists():
        existing_content_sha256 = _sha256_of_gzip_content(gz_path)
        if existing_content_sha256 != manifest.nquads_sha256:
            raise ValueError(
                f"既存の{gz_path}は今のkg.nqと食い違う(展開後sha256="
                f"{existing_content_sha256}、manifest.nquads_sha256="
                f"{manifest.nquads_sha256})。古い kg.nq.gz の可能性がある。"
                " 手動で削除してから再実行する(自動上書きはしない)"
            )
    else:
        with nquads_path.open("rb") as src, gzip.open(gz_path, "wb") as dst:
            shutil.copyfileobj(src, dst)

    gz_sha256 = build.file_sha256(gz_path)
    gz_size = gz_path.stat().st_size
    return gz_path, gz_sha256, gz_size


def render_release_notes(
    release_dir: Path,
    manifest: build.Manifest,
    gz_path: Path,
    gz_sha256: str,
    gz_size: int,
) -> str:
    """リリースノート本文を組み立てる。**すべてmanifestとsources.pyから導出する**
    (手書きしない。モジュールdocstring参照)。

    このリリースディレクトリを何度公開準備しても内容は同じ入力からの
    純粋な変換になる(kg.nq.gzと違って再利用/拒否の判断は無い)ので、
    毎回無条件に再生成してよい。
    """
    tarball_path = release_dir / TARBALL_NAME
    lines: list[str] = []
    lines.append(f"# Japan Government Knowledge Graph — {manifest.release}")
    lines.append("")
    lines.append(
        "**このプロジェクトは日本国政府とは無関係です。** 日本国政府が公開する"
        "データを第三者が構造化したものであり、政府による公式なデータセットでは"
        "ありません。"
    )
    lines.append("")
    lines.append("## 含まれるデータ")
    lines.append(f"- トリプル数: {manifest.triple_count:,}")
    lines.append(f"- グラフ({len(manifest.graphs)}件):")
    for g in sorted(manifest.graphs):
        lines.append(f"  - `{g}`")
    if manifest.quarantined_sources:
        lines.append(f"- 検証に失敗し隔離されたソース: {sorted(manifest.quarantined_sources)}")
    lines.append("")

    lines.append("## 出典・ライセンス")
    lines.append("| ソース | 日付 | 出典 | ライセンス |")
    lines.append("|---|---|---|---|")
    for source_id, date in sorted(manifest.sources.items()):
        src = sources.get_source(source_id)
        # 構造的な条件(local_pathを持つか)で「取得日」/「記録日」を分ける。
        # "ministry-codes"という文字列比較にしない
        # (CQ10・fetch.py・pipeline.pyの`_parse_source`と同じ判定条件)。
        date_kind = "記録日" if src.local_path is not None else "取得日"
        lines.append(
            f"| {src.name} | {date}({date_kind}) | [{src.url}]({src.url}) |"
            f" [{src.license}]({src.license_url}) |"
        )
    lines.append("")

    lines.append("### 出典の記載例(各出典元が規約ページで指定する書式による)")
    for source_id in sorted(manifest.sources):
        src = sources.get_source(source_id)
        lines.append(f"- {src.citation}")
    lines.append("")

    lines.append("### 編集・加工について")
    lines.append(
        "本リリースの各資産(`kg.nq.gz`・`tdb2.tar.gz`)は、上記の出典データを"
        "解析・正規化し、RDF/OWLオントロジーの形式へ変換したものです。"
        "**編集・加工を行ったこと、及びその主体はJapan Government Knowledge "
        "Graph(JGKG)プロジェクトであることを、ここに明記します**"
        "(https://github.com/nomhiro/japan-government-kg 。このプロジェクトは"
        "日本国政府とは無関係です)。編集・加工した情報を、あたかも国"
        "(又は府省等)が作成したかのような態様で公表・利用しないでください。"
    )
    lines.append("")

    lines.append("### 第三者の権利について")
    lines.append(
        "公共データ利用規約(第1.0版)は「本コンテンツの中には、第三者(国以外の"
        "者)が著作権その他の権利を有している場合があります」と述べています。"
        "行政事業レビュー見える化サイト(RS)自身も、**法人番号列・根拠法令名列に"
        "ついては提供元(国税庁法人番号公表サイト/e-Gov法令検索)の利用条件に"
        "従うこと**を明記しています——本KGでも同様に、これらの列の出典・利用"
        "条件は各提供元のものが適用されると考えてください。"
    )
    lines.append("")

    lines.append("### この成果物のライセンス")
    lines.append(
        "この成果物(データの構造化・RDF化・オントロジー設計そのもの)は "
        "**CC BY 4.0** で提供します。**ただし元データ(各府省庁・機関が公開した"
        "内容そのもの)を私たちが再ライセンスすることはできません**——元データは"
        "各出典元の公共データ利用規約(第1.0版)に基づくものであり、出典表示・"
        "編集加工の記載義務はそちらの規約に従います。PDL1.0はCC BY 4.0と"
        "互換性があります(PDL1.0原文に明記)。"
    )
    lines.append("")

    lines.append("## 資産とsha256")
    lines.append("| ファイル | サイズ | sha256 |")
    lines.append("|---|---|---|")
    lines.append(f"| `{build.MANIFEST_NAME}` | {manifest_path_size(release_dir):,} bytes | (manifest.json自身は照合対象ではない) |")
    lines.append(f"| `{TARBALL_NAME}` | {tarball_path.stat().st_size:,} bytes | `{manifest.sha256}` |")
    lines.append(f"| `{KG_NQ_GZ_NAME}` | {gz_size:,} bytes | `{gz_sha256}` |")
    lines.append("")
    lines.append(
        "`tdb2.tar.gz`のsha256とkg.nq自体のsha256(`nquads_sha256`="
        f"`{manifest.nquads_sha256}`)は`manifest.json`にも記録されている。"
        "ダウンロード後は`sha256sum`等で照合できる。"
    )
    lines.append("")

    lines.append("## 読み込み手順")
    lines.append("")
    lines.append("### N-Quadsから(どのRDFストアでも読める。長く使えるのはこちら)")
    lines.append("```sh")
    lines.append(f"gunzip {KG_NQ_GZ_NAME}")
    lines.append("# 例: 任意のトリプルストアにN-Quadsとしてロードする")
    lines.append("```")
    lines.append("")
    lines.append(
        "### TDB2から(即起動できるが**Jena 6.2.0に固定される**"
        "——TDB2のオンディスク形式はJenaのバージョンに紐づくため、"
        "別のバージョンのJenaでは読めない可能性がある)"
    )
    lines.append("```sh")
    lines.append(f"tar xzf {TARBALL_NAME}")
    lines.append(
        "# Jena 6.2.0 の Fuseki にこのtdb2/ディレクトリを指させて起動する"
        "(scripts/serve.sh参照)"
    )
    lines.append("```")
    lines.append("")
    lines.append(
        "両方とも読み込んだ後は同じSPARQLエンドポイントとして使える"
        "(`queries/cq/`のコンピテンシー質問を参照)。"
    )
    return "\n".join(lines) + "\n"


def manifest_path_size(release_dir: Path) -> int:
    """`manifest.json`自身のファイルサイズ(リリースノートの資産表に載せる用)。"""
    return (release_dir / build.MANIFEST_NAME).stat().st_size


# --- gh CLI呼び出し。テストが monkeypatch できるよう、薄い関数として分離する ---
# (fetch.py の DISPATCH スタブ差し替えと同じ作法: 外部I/Oをこの1点に集め、
# main() 自体は「呼ぶかどうか」の判断だけを持つ)


def _gh_auth_status() -> subprocess.CompletedProcess:
    return subprocess.run(
        ["gh", "auth", "status"], capture_output=True, text=True, check=False
    )


def _gh_release_create(
    release: str, notes_path: Path, assets: list[Path]
) -> subprocess.CompletedProcess:
    cmd = [
        "gh", "release", "create", release,
        "--title", f"JGKG {release}",
        "--notes-file", str(notes_path),
        *(str(a) for a in assets),
    ]
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def _git_remote_origin_url() -> str | None:
    """公開先の見当をつけるための表示専用の読み取り(`gh`を呼ばずに済ませる)。

    取得できなくてもdry-runの表示が欠けるだけで、機能上は困らないので
    `None`を返すだけにする(例外にしない)。
    """
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, check=False,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="リリースディレクトリの資産を検査し、GitHub Releasesへ公開する準備をする"
    )
    parser.add_argument(
        "release_dir", type=Path, help="例: data/artifact/2026-08-25-corrected"
    )
    parser.add_argument(
        "--publish", action="store_true",
        help="実際に `gh release create` を実行する。**既定はdry-run**"
        "(検査結果と公開予定の内容を表示するだけで、何もアップロードしない)",
    )
    args = parser.parse_args(argv)

    # 公開前検査は dry-run でも常に行う。「見せて終わる」dry-runが、
    # 実際には公開できない壊れたリリースを正常な計画として見せるのは
    # dry-runの意味に反する。
    manifest = verify_release_assets(args.release_dir)
    gz_path, gz_sha256, gz_size = make_kg_nq_gz(args.release_dir, manifest)
    notes = render_release_notes(args.release_dir, manifest, gz_path, gz_sha256, gz_size)
    notes_path = args.release_dir / NOTES_NAME
    notes_path.write_text(notes, encoding="utf-8")

    tarball_path = args.release_dir / TARBALL_NAME
    manifest_path = args.release_dir / build.MANIFEST_NAME
    assets = [gz_path, tarball_path, manifest_path]

    print("=" * 78)
    print(f"公開計画: リリース {manifest.release!r} を GitHub Releases へ公開する")
    print("=" * 78)
    remote = _git_remote_origin_url()
    print(f"公開先(git remote origin): {remote or '(不明。gitリポジトリの外で実行した可能性がある)'}")
    print(f"リリースノート: {notes_path}")
    print("資産:")
    for p in assets:
        print(f"  - {p.name}: {p.stat().st_size:,} bytes")
    print()

    if not args.publish:
        print("dry-run(既定)。実際にアップロードするには --publish を明示する")
        return 0

    print("== gh の認証状態を確認 ==")
    try:
        auth = _gh_auth_status()
    except FileNotFoundError as exc:
        raise RuntimeError(
            "gh コマンドが見つからない。https://cli.github.com/ からインストールする"
        ) from exc
    if auth.returncode != 0:
        # **「未認証」と決めつけない**——`gh auth status`はネットワーク不通や
        # ホスト未設定でも非0を返す。実際のstderrをそのまま見せる
        raise RuntimeError(
            "`gh auth status` が失敗した(認証未了、またはネットワーク/設定の"
            f"問題の可能性がある)。実際の出力:\n{auth.stderr or auth.stdout}\n"
            "認証するには `gh auth login` を実行する"
        )
    print(auth.stdout or auth.stderr)

    print("== gh release create を実行 ==")
    result = _gh_release_create(manifest.release, notes_path, assets)
    print(result.stdout)
    if result.returncode != 0:
        raise RuntimeError(f"`gh release create` が失敗した:\n{result.stderr}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
