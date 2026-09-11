"""APIイメージが、実行時に読むファイルを実際に持っていることを検査する。

**なぜ必要か(裁定B102で本番で踏んだ)。**
`/chat`の`get_ontology`は`schema/generated/{module}.owl.ttl`を**相対パスで**
読む。E-2でこの道具を足したとき`docker/api.Dockerfile`のCOPYを足さなかった
ため、**本番のコンテナでは常に失敗していた**(チャットは「オントロジーを
取得できなかった」と正直に答え続けた)。

**既存のテストは全部緑だった。** `tests/test_api_chat.py`は`generated_dir`に
リポジトリのパスを渡すので、そのファイルは必ず存在する ——
**コンテナという別の環境を一度も見ていなかった**(再発欠陥9:
実データ/実環境に一度も当てていない層は緑でも未検証)。

この検査は、コンテナを起動せずに静的に成立させる:
`create_app`が既定で読む相対パスを**コードから取り出し**、
`api.Dockerfile`がそれをCOPYしていること・`.dockerignore`がそれを
除外していないことを見る。**パスを手書きしない** ——
手書きすると、コードが読む場所を変えたときに追随しない(再発欠陥1)。

**F-2(裁定B103)での拡張。** `/overview`が起動時に読む`queries_dir`
(既定`queries/cq`)も同じ穴を踏みうる——`generated_dir`だけを固定して
見る形のままだと、次に足された実行時ディレクトリでCOPYを忘れても
このテストは気づかない。そのため`create_app`の**シグネチャが持つ既定値を
全部**(`generated_dir`・`queries_dir`)コードから取り出す形に広げた。
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_APP_PY = _REPO_ROOT / "src" / "jgkg" / "api" / "app.py"
_DOCKERFILE = _REPO_ROOT / "docker" / "api.Dockerfile"
_DOCKERIGNORE = _REPO_ROOT / ".dockerignore"

# `resolved_generated_dir = generated_dir or Path("schema/generated")`
# `resolved_queries_dir = queries_dir or Path("queries/cq")`
# ——`create_app`が引数省略時に読む、実行時ディレクトリの既定値**全部**を
# この1つの正規表現で拾う(パラメータ名を手書きで列挙しない)。
_DEFAULT_RUNTIME_DIR_RE = re.compile(
    r"(\w+)\s+or\s+Path\(\s*\"([^\"]+)\"\s*\)"
)


def _default_runtime_dirs() -> dict[str, str]:
    """`create_app`が引数省略時に読む相対パスを**全部**コードから取り出す。

    **なぜ1個だけでなく全部見るか(裁定B102の再発防止)。** 次に新しい
    実行時ディレクトリのパラメータが増えても(この変更自体が`queries_dir`
    でその実例)、このテストがそれを自動的に検査対象へ加える——1つの
    パラメータ名を検査に手書きすると、増えた方が検査から漏れる。
    """
    source = _APP_PY.read_text(encoding="utf-8")
    found = dict(_DEFAULT_RUNTIME_DIR_RE.findall(source))
    assert found, (
        "app.py から既定の実行時ディレクトリを1つも取り出せない。"
        "`<param> or Path(\"...\")` の形が変わったなら、"
        "この検査の正規表現も直すこと(黙って通してはいけない)"
    )
    return found


def _copied_paths() -> list[str]:
    """`api.Dockerfile`の`COPY`が送り元として並べるパス。"""
    copied: list[str] = []
    for line in _DOCKERFILE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.upper().startswith("COPY "):
            continue
        # `COPY <src>... <dest>` —— 最後の1つが宛先
        parts = stripped.split()[1:]
        if len(parts) >= 2:
            copied.extend(parts[:-1])
    return copied


def _is_copied(needed_path: str, copied: list[str]) -> bool:
    """`needed_path`が`copied`のどれかと完全一致するか、その配下にあるか。

    **配下も認める理由**: `COPY queries ./queries`は`queries`ディレクトリ
    全体を送るので、`create_app`が既定で読む`queries/cq`(その配下)は
    これで満たされる——`schema/generated`のような完全一致だけを認めると、
    ディレクトリ丸ごとCOPYする形(`api.Dockerfile`が両方の書き方を混在させて
    いる)を誤って「無い」と判定してしまう。
    """
    return any(
        needed_path == c or needed_path.startswith(c.rstrip("/") + "/") for c in copied
    )


def test_the_api_image_copies_every_directory_create_app_reads_by_default() -> None:
    """**`create_app`が既定で読むディレクトリが、全部イメージに入る**こと。

    何があれば落ちるか: `docker/api.Dockerfile`から`COPY schema/generated
    ./schema/generated`(裁定B102で実際に欠けていた)、あるいは
    `COPY queries ./queries`(裁定B103。`/overview`が読む)のどちらかを
    消すと落ちる。
    """
    needed = _default_runtime_dirs()
    copied = _copied_paths()
    assert copied, "api.Dockerfile から COPY 行を1つも取れていない(検査が空回り)"
    missing = {name: path for name, path in needed.items() if not _is_copied(path, copied)}
    assert not missing, (
        f"create_app が既定で読むディレクトリのうち、api.Dockerfile が COPY していないものがある: "
        f"{missing}。COPY しているのは {copied}。"
        "コンテナ内ではそのパスが存在せず、対応するエンドポイントが必ず失敗する"
    )


def test_the_dockerignore_does_not_exclude_any_of_them() -> None:
    """**`.dockerignore`がそれらを除外していない**こと。

    COPY を書いても、`.dockerignore` が送信対象から外していれば
    ビルドは失敗する(または空になる)。`data/` は意図的に除外されており
    (13GB。api.Dockerfileのコメント参照)、同じ轍を踏まないよう
    ここで明示的に押さえる。

    何があれば落ちるか: `.dockerignore` に `schema/` や `queries/` を
    足すと落ちる。
    """
    needed = _default_runtime_dirs()
    patterns = [
        line.strip().rstrip("/")
        for line in _DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert patterns, ".dockerignore からパターンを1つも取れていない(検査が空回り)"
    for name, path in needed.items():
        # `schema` / `schema/generated` のような、必要なパスの祖先を
        # 除外していないこと
        parts = path.split("/")
        ancestors = {"/".join(parts[: i + 1]) for i in range(len(parts))}
        blocked = sorted(ancestors & set(patterns))
        assert not blocked, (
            f".dockerignore が '{name}' の既定値 '{path}' を"
            f"(祖先 {blocked} として)除外している。COPY を書いてもイメージに入らない"
        )


def test_the_ontology_files_that_get_ontology_offers_exist_in_the_repository() -> None:
    """**道具が列挙するモジュールのファイルが実在する**こと。

    `build_tool_schemas`は`module_names()`から`module`のenumを作るので、
    列挙されたのに`.owl.ttl`が無いモジュールがあれば、LLMはそれを選べて
    しかも必ず失敗する。COPYが入っている今、実在の確認はリポジトリ側で足る。
    """
    from jgkg.site import module_names

    generated = _REPO_ROOT / _default_runtime_dirs()["generated_dir"]
    modules = module_names(generated)
    assert modules, "module_names() が空(検査が空回り)"
    missing = [m for m in modules if not (generated / f"{m}.owl.ttl").is_file()]
    assert not missing, f"列挙されているのに .owl.ttl が無いモジュール: {missing}"
