"""ベースURIの一括差し替えと整合検査。

**ベースURIは「実行時の設定」ではなく「生成時に焼き込まれるオントロジーの同一性」である。**

`schema/*.yaml` の `id:` と `prefixes:`、公理オーバーレイ、CQクエリの `PREFIX`、そして
それらから生成した `schema/generated/**` には、ベースURIが**文字列として焼き込まれる**。
`.env` の `JGKG_BASE_URI` を変えても生成物は追随しない。追随しないまま実行すると、
`emit` は新しい名前空間でデータを書き、SHACLの `sh:targetClass` は旧名前空間を指すため、
**どのシェイプもどのノードも対象にせず全グラフが `conforms=True` になる**(検証ゲートが
沈黙して素通しに変わる)。この退化を防ぐために、

1. ドメインの差し替えを1コマンドにする(`rewrite`)
2. `config.Settings.base_uri` の既定値と全対象ファイルのドメインが一致しないなら
   失敗する検査を用意する(`find_inconsistencies`)

の2つをここに置く。実行時の取り違え(`.env` で上書きしたまま古い生成物で走らせる)は
`validate.validate_dataset` の「宣言された型にシェイプが1つも無ければ例外」で捕まえる。

使い方:

    uv run python -m jgkg.base_uri --check                      # 整合検査
    uv run python -m jgkg.base_uri https://example.test/kg     # 差し替え
    ./scripts/generate-schema.sh                                # 差し替え後に必須
"""
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

# 差し替えの対象。**人が書くファイルだけ**を挙げる。生成物は再生成で追随させる
# (再生成を忘れたら `find_inconsistencies` が落ちる、という関係にしてある)
SOURCE_GLOBS: tuple[str, ...] = (
    "schema/*.yaml",
    "schema/overlay/*.ttl",
    "queries/cq/*.rq",
    "src/jgkg/*.py",
    "src/jgkg/*/*.py",
    "tests/*.py",
    "scripts/*.py",
    ".env.example",
)

# 検査の対象に生成物も含める。**ここを外すと「差し替えたが再生成していない」状態が
# 検査を通り、SHACL検証が対象0件で合格するようになる。**
GENERATED_GLOBS: tuple[str, ...] = (
    "schema/generated/*.ttl",
    "schema/generated/*.py",
)

# 自分のベースURI以外に現れてよい外部ホスト。**許可リスト方式**にしてある。
# 新しい外部語彙を参照するときはここに足す(足す判断を明示的にするため)。
# 拒否リストにすると「知らないドメインが混ざる」ことを検出できない。
ALLOWED_EXTERNAL_HOSTS: frozenset[str] = frozenset({
    # 標準語彙
    "www.w3.org",          # RDF / RDFS / OWL / SHACL / PROV / SKOS / XMLSchema
    "purl.org",            # Dublin Core
    "schema.org",
    "w3id.org",            # LinkML
    "creativecommons.org",  # ライセンス
    # 出典として記録する政府サイト(sources.py)
    "www.digital.go.jp",
    "www.houjin-bangou.nta.go.jp",
    "github.com",
    # 生成物のコメントに現れる
    "pydantic-docs.helpmanual.io",
    # テスト専用のダミー(RFC 2606 / RFC 6761 の予約名)
    "example.test",
    "uri-test.invalid",
})

# 絶対IRIの抜き出し。Turtleの `<...>`、YAMLの素の値、Pythonの文字列リテラル、
# SPARQLの `PREFIX` をまとめて拾えるように、区切りになりうる文字で止める。
# `{` `}` を除外しているのは、f-string の `f"http://{host}/x"` を1つのIRIとして
# 誤検出しないため(ホスト部を変数にした検査用コードが自分で引っかかる)
_IRI_RE = re.compile(r"""https?://[^\s<>"'`,;(){}\[\]]+""")

# 設計書§4.2のURIパターンに現れるパス片。**ホストの許可リストだけでは不十分**で、
# ベースURIのホストが出典URLと同じ(www.digital.go.jp 等)場合、そのホストは
# 許可済みなので古いベースURIが素通りしてしまう。「うちの構造を持つIRIは、
# ホストが何であれベースURIの配下でなければならない」を追加の条件にする。
# (この欠陥は test_check_detects_a_stale_domain が実際に検出した)
_OWN_PATH_RE = re.compile(r"/(def|id|graph)/")


@dataclass(frozen=True)
class Inconsistency:
    path: Path
    line: int
    iri: str
    reason: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.iri} — {self.reason}"


def expected_base_uri() -> str:
    """生成時に焼き込むべきベースURI。

    **実効値(`get_settings().base_uri`)ではなく既定値を正とする。** 生成物は
    `config.py` の既定値から作られるので、`.env` の上書きを正にすると
    「上書きしたら検査が永久に通る」という空振りになる。
    """
    from jgkg.config import Settings

    default = Settings.model_fields["base_uri"].default
    return str(default).rstrip("/")


def _iter_paths(root: Path, globs: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    for pattern in globs:
        for p in sorted(root.glob(pattern)):
            if p.is_file() and "__pycache__" not in p.parts:
                out.append(p)
    return out


def source_paths(root: Path) -> list[Path]:
    return _iter_paths(root, SOURCE_GLOBS)


def checked_paths(root: Path) -> list[Path]:
    return source_paths(root) + _iter_paths(root, GENERATED_GLOBS)


def _under_base(iri: str, base: str) -> bool:
    return iri == base or iri.startswith((f"{base}/", f"{base}#"))


def find_inconsistencies(root: Path, base_uri: str | None = None) -> list[Inconsistency]:
    """対象ファイルに、自分のベースURIでも許可された外部ホストでもないIRIが無いか調べる。

    ここが空でなければ、ドメインの差し替えが中途半端な状態にある(あるいは
    未登録の外部語彙が混ざっている)。
    """
    base = (base_uri or expected_base_uri()).rstrip("/")
    found: list[Inconsistency] = []

    for path in checked_paths(root):
        text = path.read_bytes().decode("utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            for iri in _IRI_RE.findall(line):
                if _under_base(iri, base):
                    continue
                parts = urlsplit(iri)
                looks_like_ours = bool(_OWN_PATH_RE.search(parts.path))
                if not looks_like_ours and parts.netloc in ALLOWED_EXTERNAL_HOSTS:
                    continue
                if looks_like_ours:
                    reason = (
                        f"設計書§4.2のURIパターン(/def/ /id/ /graph/)を持つのに"
                        f"ベースURI({base})の配下にない — 古いドメインが残っている"
                    )
                else:
                    reason = (
                        f"ベースURI({base})の配下でもなく、許可された外部ホストでもない"
                        f"(host={parts.netloc!r})"
                    )
                found.append(
                    Inconsistency(
                        path=path.relative_to(root), line=lineno, iri=iri, reason=reason
                    )
                )
    return found


def rewrite(root: Path, new_base_uri: str, old_base_uri: str | None = None) -> list[Path]:
    """人が書くファイル中のベースURIを一括で差し替える。

    改行コードを変えないようにバイト列で扱う(生成物のLF固定と同じ趣旨。
    `read_text` は改行を正規化してしまう)。
    """
    old = (old_base_uri or expected_base_uri()).rstrip("/")
    new = new_base_uri.rstrip("/")
    if not new:
        raise ValueError("新しいベースURIが空である")
    if old == new:
        return []

    old_b, new_b = old.encode("utf-8"), new.encode("utf-8")
    changed: list[Path] = []
    for path in source_paths(root):
        data = path.read_bytes()
        if old_b not in data:
            continue
        path.write_bytes(data.replace(old_b, new_b))
        changed.append(path)
    return changed


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = Path.cwd()

    if not args or args[0] in {"-h", "--help"}:
        print(__doc__)
        return 0

    if args[0] == "--check":
        problems = find_inconsistencies(root)
        if problems:
            print(
                f"ベースURI({expected_base_uri()})と一致しないIRIが"
                f"{len(problems)}件ある:",
                file=sys.stderr,
            )
            for p in problems:
                print(f"  {p}", file=sys.stderr)
            print(
                "\n差し替えるなら: uv run python -m jgkg.base_uri <新しいベースURI>"
                " && ./scripts/generate-schema.sh",
                file=sys.stderr,
            )
            return 1
        print(f"OK: ベースURI {expected_base_uri()} で整合している")
        return 0

    new_base = args[0]
    old_base = expected_base_uri()
    changed = rewrite(root, new_base)
    print(f"{old_base} → {new_base.rstrip('/')} に差し替えた({len(changed)}ファイル):")
    for p in changed:
        print(f"  {p}")
    print(
        "\n**次に ./scripts/generate-schema.sh を実行して生成物を作り直すこと。**"
        " 忘れると検証が対象0件で合格するようになる"
        "(uv run python -m jgkg.base_uri --check が検出する)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
