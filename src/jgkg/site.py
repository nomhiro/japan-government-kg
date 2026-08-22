"""公開オントロジーを静的配信できる形に組み立てる。

**なぜ静的配信で足りるのか。** 語彙のURIはハッシュURI(`.../def/core#Agent`)である。
フラグメントはHTTPリクエストに含まれないので、サーバは `/def/core` を返せばよい。
つまり**トリプルストアを立てる前に、オントロジーだけを dereferenceable にできる。**
設計書の原則1「本体はオントロジーとKG、アプリは検証装置」に照らして、
ここが最初に公開すべきものである。

**解決すべきパスをハードコードしない。** 生成物の中で base 配下のIRIが主語として
現れるものを列挙し、それを正とする(`required_paths`)。ハードコードすると、
モジュールを増やしたときに黙って抜け落ちる — このプロジェクトで3回起きた型である。
"""
import shutil
from pathlib import Path

from rdflib import Graph, URIRef

from .config import get_settings


def _base() -> str:
    return get_settings().base_uri.rstrip("/")


def required_paths(generated_dir: Path) -> set[str]:
    """生成物が「このURLで解決されるべき」と主張しているパスを集める。

    生成OWL/SHACLの中で、ベースURI配下のIRIが**主語として**現れるものを対象にする。
    フラグメントは落とす(ハッシュURIはサーバまで届かない)。
    """
    base = _base()
    paths: set[str] = set()
    for f in sorted(generated_dir.glob("*.ttl")):
        g = Graph()
        g.parse(f, format="turtle")
        for s in set(g.subjects()):
            if isinstance(s, URIRef) and str(s).startswith(base):
                rest = str(s)[len(base) :].split("#")[0]
                if rest and rest != "/":
                    paths.add(rest)
    return paths


def build(generated_dir: Path, out_dir: Path) -> set[str]:
    """`out_dir` に配信用のファイルを作り、作ったパスの集合を返す。

    拡張子なしのエイリアス(`/def/core`)は**実ファイルとして作る。**
    プラットフォームの書き換え機能(`_redirects` の 200 rewrite 等)に依存しない方が
    移植性が高く、ここで検証もできる。数十KBの重複はその対価として妥当。
    """
    def_dir = out_dir / "def"
    if def_dir.exists():
        shutil.rmtree(def_dir)
    def_dir.mkdir(parents=True)

    made: set[str] = set()
    for f in sorted(generated_dir.glob("*.ttl")):
        shutil.copy2(f, def_dir / f.name)
        made.add(f"/def/{f.name}")

    # モジュール名だけのURI(`/def/core`)は skos:inScheme などで使われる。
    # 対応するOWLを同じ内容で置く。
    for owl in sorted(generated_dir.glob("*.owl.ttl")):
        module = owl.name.removesuffix(".owl.ttl")
        shutil.copy2(owl, def_dir / module)
        made.add(f"/def/{module}")

    # sitemap を作る。**robots.txt がこれを名指ししているので、無いと
    # 「存在しないものへの参照」になる**(このプロジェクトで繰り返した
    # 「消費者のいない記録」の裏返し)。
    base = _base()
    lines = [f"{base}/"] + [f"{base}{p}" for p in sorted(made)]
    (out_dir / "sitemap.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    made.add("/sitemap.txt")

    return made


def missing_paths(generated_dir: Path, out_dir: Path) -> set[str]:
    """生成物が要求しているのに配信物に無いパスを返す。空集合なら整合している。"""
    required = required_paths(generated_dir)
    return {p for p in required if not (out_dir / p.lstrip("/")).is_file()}
