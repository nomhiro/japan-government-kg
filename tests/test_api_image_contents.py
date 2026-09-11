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
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_APP_PY = _REPO_ROOT / "src" / "jgkg" / "api" / "app.py"
_DOCKERFILE = _REPO_ROOT / "docker" / "api.Dockerfile"
_DOCKERIGNORE = _REPO_ROOT / ".dockerignore"

# `resolved_generated_dir = generated_dir or Path("schema/generated")`
_DEFAULT_GENERATED_DIR_RE = re.compile(
    r"generated_dir\s+or\s+Path\(\s*\"([^\"]+)\"\s*\)"
)


def _default_generated_dir() -> str:
    """`create_app`が`generated_dir`未指定のときに読む相対パスをコードから取る。"""
    source = _APP_PY.read_text(encoding="utf-8")
    match = _DEFAULT_GENERATED_DIR_RE.search(source)
    assert match, (
        "app.py から既定の generated_dir を取り出せない。"
        "`generated_dir or Path(\"...\")` の形が変わったなら、"
        "この検査の正規表現も直すこと(黙って通してはいけない)"
    )
    return match.group(1)


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


def test_the_api_image_copies_the_directory_that_get_ontology_reads() -> None:
    """**`get_ontology`が読むディレクトリがイメージに入る**こと。

    何があれば落ちるか: `docker/api.Dockerfile` から
    `COPY schema/generated ./schema/generated` を消すと落ちる
    (裁定B102で実際に欠けていたのがこれ)。
    """
    needed = _default_generated_dir()
    copied = _copied_paths()
    assert copied, "api.Dockerfile から COPY 行を1つも取れていない(検査が空回り)"
    assert needed in copied, (
        f"create_app が既定で読む '{needed}' を api.Dockerfile が COPY していない。"
        f"COPY しているのは {copied}。"
        "コンテナ内ではそのパスが存在せず、/chat の get_ontology が必ず失敗する"
    )


def test_the_dockerignore_does_not_exclude_the_generated_directory() -> None:
    """**`.dockerignore`がそれを除外していない**こと。

    COPY を書いても、`.dockerignore` が送信対象から外していれば
    ビルドは失敗する(または空になる)。`data/` は意図的に除外されており
    (13GB。api.Dockerfileのコメント参照)、同じ轍を踏まないよう
    ここで明示的に押さえる。

    何があれば落ちるか: `.dockerignore` に `schema/` を足すと落ちる。
    """
    needed = _default_generated_dir()
    patterns = [
        line.strip().rstrip("/")
        for line in _DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert patterns, ".dockerignore からパターンを1つも取れていない(検査が空回り)"
    # `schema` / `schema/generated` のような、必要なパスの祖先を除外していないこと
    parts = needed.split("/")
    ancestors = {"/".join(parts[: i + 1]) for i in range(len(parts))}
    blocked = sorted(ancestors & set(patterns))
    assert not blocked, (
        f".dockerignore が '{needed}' を(祖先 {blocked} として)除外している。"
        "COPY を書いてもイメージに入らない"
    )


def test_the_ontology_files_that_get_ontology_offers_exist_in_the_repository() -> None:
    """**道具が列挙するモジュールのファイルが実在する**こと。

    `build_tool_schemas`は`module_names()`から`module`のenumを作るので、
    列挙されたのに`.owl.ttl`が無いモジュールがあれば、LLMはそれを選べて
    しかも必ず失敗する。COPYが入っている今、実在の確認はリポジトリ側で足る。
    """
    from jgkg.site import module_names

    generated = _REPO_ROOT / _default_generated_dir()
    modules = module_names(generated)
    assert modules, "module_names() が空(検査が空回り)"
    missing = [m for m in modules if not (generated / f"{m}.owl.ttl").is_file()]
    assert not missing, f"列挙されているのに .owl.ttl が無いモジュール: {missing}"
