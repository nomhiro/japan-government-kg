"""成果物ビルドとmanifest。

インデックスをCIが生成する成果物として扱い、実行環境から切り離す
(設計書§6.3)。content-addressed にして破損を検出し、Jenaバージョンを
記録して実行側と照合できるようにする。
"""
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
    release: str
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
    graphs: list[str]
    # 成果物に**実際に入っている**ソースと、その「いつ時点か」。
    # 隔離されたソースはここに載せない(載せると「この日付のデータを含む」という嘘になる)
    sources: dict[str, str]
    # 隔離されて入らなかったソース。**落ちたことを黙って消さない。**
    # 既定を空にしているのは、この項目が無い既存の manifest.json も読めるようにするため
    quarantined_sources: list[str] = []
    # 成果物のmanifest形式そのものの版。この欄自体を計画B Task 1で追加したため、
    # それ以前に作られた manifest.json には欄が無い。`Manifest(...)` を直接構築する
    # (=新規に作る)場合の既定はこの 2。**旧manifestを読むときに 1 とみなす処理は
    # ここではなく read_manifest() 側に置く**(pydanticのフィールド既定だけでは
    # 「新規構築で省略した」のか「旧ファイルに欄が無い」のかを区別できないため)
    # Task 10修正ラウンド: `nquads_sha256`を追加したのでこの欄自体は再度3に上げる
    # (計画B Task 1がmanifest_version欄自体の追加で2に上げたのと同じ作法)
    manifest_version: int = 3


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
    sources: dict[str, str],
    graphs: list[str],
    quarantined_sources: list[str] | None = None,
) -> Manifest:
    if not jena_version:
        raise ValueError(
            "Jenaバージョンが空である。TDB2のオンディスク形式はJenaのバージョンに"
            "紐づくため、記録を省略できない(設計書§6.3)"
        )
    return Manifest(
        release=release,
        created_on=release,
        jena_version=jena_version,
        sha256=file_sha256(tarball),
        byte_size=tarball.stat().st_size,
        triple_count=_count_triples(nquads),
        nquads_sha256=file_sha256(nquads),
        graphs=sorted(graphs),
        sources=sources,
        quarantined_sources=sorted(quarantined_sources or []),
    )


def write_manifest(m: Manifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(m.model_dump(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    atomic_write(path, data)


def read_manifest(path: Path) -> Manifest:
    """manifest.json を読む。

    **`manifest_version` が無い旧 manifest は 1 とみなす。** この欄自体を
    計画B Task 1 で追加したため、それ以前の manifest には存在しない。
    `Manifest` フィールドの既定値(2、新規構築時の版)をそのまま使うと、
    旧ファイルも「欄を省略した新規構築」と区別できず誤って2とみなされる
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
