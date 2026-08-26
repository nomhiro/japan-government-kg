"""成果物ビルドとmanifest。

インデックスをCIが生成する成果物として扱い、実行環境から切り離す
(設計書§6.3)。content-addressed にして破損を検出し、Jenaバージョンを
記録して実行側と照合できるようにする。
"""
import datetime
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel

from jgkg._io import atomic_write

# serve.py・pipeline.py が同じファイル名を指すための単一の出典
# (Task 10修正ラウンド: pipeline.py が carry-over の供給元検査のために
# manifest.json の存在を要求するようになった。pipeline.py が serve.py を
# importする層の逆転を避けるため、この定数はserve.pyではなくここに置く
# ——serve.pyはこちらを再importして使う)
MANIFEST_NAME = "manifest.json"


class Manifest(BaseModel):
    # 成果物ディレクトリのbasename(Ruling B31)。同一性の識別子であり、
    # 日付である必要はない(`2026-08-26-license-fix`のような名前も許される)
    release: str
    # **ビルドした日付**(観察O8の修正)。Ruling B31が`release`の意味を
    # 「最新ソース取得日」→「basename」に変えたとき、実装
    # (`created_on=release`)がこの欄も一緒にbasenameにしてしまっていた
    # ——2026-08-26、公開直前にteam-leadが実際のmanifestで発見した
    # (`"created_on": "2026-08-26-license-fix"`という、日付の欄に非日付値
    # が入った状態)。**`release`と`created_on`は別の意味を持つ欄であり、
    # 同じ値になるとは限らない。**
    created_on: str
    jena_version: str
    sha256: str
    byte_size: int
    triple_count: int
    # Task 10修正ラウンド(Ruling B26): kg.nq(N-Quads本体)の完全性照合に使う
    # sha256。**既存の`sha256`欄はtarball(tdb2.tar.gz)のハッシュであり、
    # kg.nqのハッシュではない**(このモジュールの他の欄と同様、tdb2構築前の
    # kg.nq自体を後から独立に読む消費者がいなかったため今まで無かった)。
    # pipeline.pyのcarry-over(前リリースのkg.nqから据え置き対象のグラフを
    # 抽出する処理)が、保管中に書き換えられたkg.nqを黙って受理しないための
    # 照合に使う。**旧形式(manifest_version<3)のmanifestにはこの欄が無いため
    # `None`**(「照合できない」ことを0/空文字と区別する。`read_manifest`が
    # 欄の無いJSONを読むとpydanticの既定値がそのままNoneになるので、
    # 追加のsetdefaultは要らない)
    nquads_sha256: str | None = None
    # Task 11修正ラウンド(fix-brief §3): TDB2の**展開後**サイズ(バイト数)。
    # `byte_size`(tarball圧縮後)とは別の数値 — §6.3の一時ディスク8GiB上限は
    # 展開後のTDB2が占めるサイズで判定するため、圧縮後サイズだけでは判定できない
    # (実測: 全法人13.8GiB→tar.gz 1.86GiB、支出先限定429MiB→tar.gzはさらに
    # 小さい。圧縮率がリリースごとに変わるため展開後サイズを別途記録する。
    # 支出先限定の数値は修正ラウンド2で429MiBに訂正——旧「232MiB」は別の
    # 見積り〔選択肢A、未使用〕からの混入だった。docs/measurements-phase1.md参照)。
    # `build.sh`がコンテナのネイティブ層(§6.3の警告どおりバインドマウント
    # 上には構築しない。progress.md 発見7)で`du -sb`した値をそのまま渡す。
    # **旧形式(manifest_version<4)のmanifestにはこの欄が無いため`None`**
    # (nquads_sha256と同じ「照合/判定できないことを0と区別する」作法)
    tdb2_expanded_bytes: int | None = None
    # B-2裁定: 配布物をダウンロードした人が、それを作ったコードのコミットを
    # 特定できるようにする。`gh release create`が(`--target`未指定のため)
    # publish時点のリモートデフォルトブランチHEADにタグを作るだけでは、
    # そのタグが後から動かされたりリリース自体が消されたりすると手がかりを
    # 失う——manifest自体に焼き込むのがより頑丈な記録先になる。**片方だけでは
    # 意味がない**: 作業ツリーが汚れていた(コミットに無い変更が混ざっている
    # かもしれない)状態で記録したSHAは、それ単独では「嘘」になる。そのため
    # `git_dirty`と必ずペアで追加した。**旧形式(manifest_version<6)の
    # manifestにはこの2欄が無いため`None`**(nquads_sha256/tdb2_expanded_bytes
    # と同じ「照合/判定できないことを既定値〔空文字/False〕と区別する」作法)
    git_commit: str | None = None
    # `git status --porcelain`の素の判定(追跡対象外のファイルも汚れとみなす。
    # `-uno`等で除外しない) — 追跡されていない`.py`等の変更でもビルド結果に
    # 影響しうるため、コミット済みかどうかだけでは不十分
    git_dirty: bool | None = None
    graphs: list[str]
    # 成果物に**実際に入っている**ソースと、その「いつ時点か」。
    # 隔離されたソースはここに載せない(載せると「この日付のデータを含む」という嘘になる)
    sources: dict[str, str]
    # 隔離されて入らなかったソース。**落ちたことを黙って消さない。**
    # 既定を空にしているのは、この項目が無い既存の manifest.json も読めるようにするため
    quarantined_sources: list[str] = []
    # 成果物のmanifest形式そのものの版。この欄自体を計画B Task 1で追加したため、
    # それ以前に作られた manifest.json には欄が無い。`Manifest(...)` を直接構築する
    # (=新規に作る)場合の既定は、この欄を追加した当時は2だった(現在は下記の
    # 変遷を経て5)。**旧manifestを読むときに 1 とみなす処理は
    # ここではなく read_manifest() 側に置く**(pydanticのフィールド既定だけでは
    # 「新規構築で省略した」のか「旧ファイルに欄が無い」のかを区別できないため)
    # Task 10修正ラウンド: `nquads_sha256`を追加したのでこの欄自体は再度3に上げた
    # (計画B Task 1がmanifest_version欄自体の追加で2に上げたのと同じ作法)。
    # Task 11修正ラウンド: `tdb2_expanded_bytes`を追加したので4に上げる
    # Task 11修正ラウンド2(Ruling B31): `release`/`created_on`の意味を
    # 「最新ソース取得日」から「成果物ディレクトリのbasename」に変えたため
    # (同日に作った複数リリースがmanifestだけで区別できなかった不具合の修正)、
    # manifestの読み手が旧versionと新versionで`release`の意味を区別できるように
    # 5に上げる。B-2裁定: `git_commit`/`git_dirty`欄の追加で6に上げる
    manifest_version: int = 6


def file_sha256(path: Path) -> str:
    """ファイルの内容全体のsha256(全体をメモリに載せず1MiBずつ読む)。

    tarball・kg.nq のどちらも数百MB〜規模になり得るため、`read_bytes()`では
    なくストリームで読む。pipeline.py(carry-overの供給元照合。Ruling B26)が
    このモジュール外から呼ぶため公開名にした(以前は`_sha256`という
    モジュール内部限定の名前だったが、tarball以外(kg.nq)の照合という
    2つ目の消費者ができたことで、モジュール境界を越える公開APIになった)。
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_triples(path: Path) -> int:
    """N-Quadsの行数を数える。

    全体をメモリに載せない(実データでは数千万行になる)。
    **グラフURIはここで推測しない。** リテラルには空白も `>` も含まれうるため、
    テキストからグラフ項を判別するには本物の字句解析が必要で、素朴な文字列操作では
    3項トリプル行のオブジェクトIRIをグラフURIと誤認する。グラフ一覧は Dataset を
    持つ呼び出し側から受け取る。
    """
    count = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            count += 1
    return count


def build_manifest(
    nquads: Path,
    tarball: Path,
    jena_version: str,
    release: str,
    created_on: str,
    sources: dict[str, str],
    graphs: list[str],
    tdb2_expanded_bytes: int,
    git_commit: str,
    git_dirty: bool,
    quarantined_sources: list[str] | None = None,
) -> Manifest:
    # 観察O8の修正: `created_on`は日付でなければならない。**空文字チェック
    # だけでは不十分**——実際に検出された欠陥の値(`"2026-08-26-license-fix"`)
    # は空文字ではないため、空文字チェックだけでは素通りしてしまう。
    # `date.fromisoformat`は末尾の余分な文字も拒否する(`"2026-08-26-license-
    # fix"`は`"2026-08-26"`を含むが、これも例外になる)
    try:
        datetime.date.fromisoformat(created_on)
    except ValueError as exc:
        raise ValueError(
            f"created_on が日付(YYYY-MM-DD)ではない: {created_on!r}。"
            "releaseディレクトリのbasename(識別子)をそのまま渡していないか"
            "確認する(観察O8: この2つの欄は意味が異なる。releaseは同一性、"
            "created_onはビルドした日付)"
        ) from exc
    if not jena_version:
        raise ValueError(
            "Jenaバージョンが空である。TDB2のオンディスク形式はJenaのバージョンに"
            "紐づくため、記録を省略できない(設計書§6.3)"
        )
    # Task 11修正ラウンド(fix-brief §3): **必須パラメータにして既定値を
    # 持たせない。** §6.3の8GiB判定はこの数値でしか行えないため、
    # 呼び出し側(build.sh)がdu -sbの出力を読み取れなかった場合に
    # manifestへ黙って`None`を書くのではなく、ここで呼び出しそのものが
    # 落ちる形にする(「既定は止まる側」。jena_versionの検査と同じ作法)
    if tdb2_expanded_bytes <= 0:
        raise ValueError(
            f"tdb2_expanded_bytes が正の値ではない: {tdb2_expanded_bytes!r}。"
            " TDB2の展開後サイズを du -sb 等から読み取れていない疑いがある"
            "(§6.3の一時ディスク8GiB判定にこの数値を使うため、0や負値のまま"
            "manifestに記録してはならない)"
        )
    # B-2裁定: jena_versionと同じ「既定は止まる側」。呼び出し側(build.sh)が
    # `git rev-parse HEAD`を読み取れなかった場合に空文字を静かに記録すると、
    # この欄を追加した目的(配布物とコードを結ぶ手がかり)そのものが最初から
    # 欠けたまま出荷されてしまう。**gitコマンド自体の実行はここでは行わない**
    # (build.pyはチェックサム計算等と同様、渡された値を記録するだけの層に
    # 留める。jena_version/tdb2_expanded_bytesと同じ「計算は呼び出し側、
    # 検証と記録はここ」という分担)
    if not git_commit:
        raise ValueError(
            "git_commit が空である。配布物をダウンロードした人がそれを作った"
            "コードのコミットを特定できるようにするため、記録を省略できない"
            "(B-2裁定)。git rev-parse HEAD を読み取れていない疑いがある"
        )
    return Manifest(
        release=release,
        created_on=created_on,
        jena_version=jena_version,
        sha256=file_sha256(tarball),
        byte_size=tarball.stat().st_size,
        triple_count=_count_triples(nquads),
        nquads_sha256=file_sha256(nquads),
        tdb2_expanded_bytes=tdb2_expanded_bytes,
        graphs=sorted(graphs),
        sources=sources,
        quarantined_sources=sorted(quarantined_sources or []),
        git_commit=git_commit,
        git_dirty=git_dirty,
    )


def write_manifest(m: Manifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(m.model_dump(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    atomic_write(path, data)


def read_manifest(path: Path) -> Manifest:
    """manifest.json を読む。

    **`manifest_version` が無い旧 manifest は 1 とみなす。** この欄自体を
    計画B Task 1 で追加したため、それ以前の manifest には存在しない。
    `Manifest` フィールドの既定値(5、新規構築時の版)をそのまま使うと、
    旧ファイルも「欄を省略した新規構築」と区別できず誤って5とみなされる
    ため、読み込み時だけここで明示的に補う。
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("manifest_version", 1)
    return Manifest(**data)


def verify_manifest(
    manifest_path: Path,
    tarball: Path,
    expected_jena_version: str | None = None,
) -> None:
    """成果物のsha256と、任意でJenaバージョンが一致することを確かめる。

    実行側が起動時にこれを呼ぶことで、Neptuneのsegment自動修復に相当する
    「壊れたデータを検出する」能力をチェックサムで安価に得る。

    `expected_jena_version` を渡すと、実行側のJenaバージョンが成果物を作った
    ものと一致するかも確かめる。**TDB2のオンディスク形式はJenaのバージョンに
    紐づく**ため、記録しただけで照合しなければ意味がない。
    """
    m = read_manifest(manifest_path)
    actual = file_sha256(tarball)
    if actual != m.sha256:
        raise ValueError(
            f"成果物のsha256が一致しない。manifest={m.sha256} actual={actual}"
        )
    if expected_jena_version is not None and expected_jena_version != m.jena_version:
        raise ValueError(
            "Jenaバージョンが一致しない。TDB2のオンディスク形式はバージョンに紐づくため"
            f"読めない可能性がある。manifest={m.jena_version} runtime={expected_jena_version}"
        )
