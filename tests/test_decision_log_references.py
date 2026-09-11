"""裁定(Ruling/裁定 Bnn)への参照が、決定ログに実在することを機械的に確かめる。

**なぜ必要か(裁定B100で実際に踏んだ)。**
`scripts/generate-schema.sh` に「裁定B100」を引くコメントを書いたが、
`docs/decision-log.md` に B100 の記載を書くのを忘れたまま押した。
コードとドキュメントが**存在しない裁定を根拠として引いている**状態で、
読んだ人は理由を辿れない。人間のレビューでは見つからなかった
(参照と記載は別のファイルにあり、同時に開かれない)。

この検査は、リポジトリ全体の `裁定Bnn` / `Ruling Bnn` という参照を集め、
そのすべてが決定ログで**定義されている**ことを要求する。
定義とは、決定ログの行が次のどちらかで始まることを指す:

- 見出し: `## 裁定 B57: …` / `### 裁定 B33: …` / `## Ruling B31: …`
- 太字の段落: `**Ruling B20(指摘8): …` / `**裁定 B4(B3を上書き): …`

(B1〜B32 は太字の段落、B33 以降は見出しで書かれている。**どちらの形も
実在するので、両方を定義として認める** —— 片方だけを認める実装にすると、
古い裁定が全部「未定義」になってこの検査が無意味になる。)
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DECISION_LOG = _REPO_ROOT / "docs" / "decision-log.md"

# 本文を持つテキストファイルだけを見る(バイナリと生成物の.ttlは除く)。
_TEXT_SUFFIXES = {".md", ".py", ".sh", ".yaml", ".yml", ".ts", ".rq", ".json", ".html"}

# 「裁定B97」「裁定 B97」「Ruling B31」。全角スペースは実際には現れないので見ない。
_REFERENCE_RE = re.compile(r"(?:裁定|Ruling)\s?(B\d+)")

# 決定ログ側で「ここがその裁定の記載である」と見なす行の形。
_DEFINITION_RE = re.compile(r"^(?:#+\s|\*\*)(?:裁定|Ruling)\s?(B\d+)\b")

# **この検査が空回りしないための下限。** 正規表現が壊れて0件になると、
# 「未定義は0件」という主張は自動的に真になってしまう(欠陥型2: 空虚なテスト)。
# 2026-09-11 の実測は参照98件・定義98件。
_MIN_REFERENCES = 90
_MIN_DEFINITIONS = 90


def _tracked_text_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    return [
        _REPO_ROOT / name
        for name in out
        if name and Path(name).suffix in _TEXT_SUFFIXES
    ]


def _referenced_rulings() -> dict[str, set[str]]:
    """参照されている裁定 → 参照しているファイル(リポジトリ相対)の集合。"""
    found: dict[str, set[str]] = {}
    for path in _tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for match in _REFERENCE_RE.finditer(text):
            found.setdefault(match.group(1), set()).add(rel)
    return found


def _defined_rulings(log_text: str) -> set[str]:
    return {
        match.group(1)
        for line in log_text.splitlines()
        if (match := _DEFINITION_RE.match(line))
    }


def test_every_referenced_ruling_is_recorded_in_the_decision_log() -> None:
    """**存在しない裁定を根拠として引いているコード・文書が無い**こと。

    何があれば落ちるか: `docs/decision-log.md` に記載を書かずに、
    決定ログに無い番号(たとえば B101)を裁定として引くコメントをどこかに
    足すと、そのファイル名つきで落ちる(裁定B100で実際に起きたのがこれ)。

    **この説明文に「裁定」+その番号という並びを書いてはいけない。**
    検査は`git ls-files`の全テキストを走査する —— つまり**この
    テストファイル自身も走査対象**であり、例として書いた番号がそのまま
    「決定ログに無い裁定への参照」として自分で検出される
    (最初に書いたときそれで落ちた)。
    """
    referenced = _referenced_rulings()
    defined = _defined_rulings(_DECISION_LOG.read_text(encoding="utf-8"))

    assert len(referenced) >= _MIN_REFERENCES, (
        f"参照が{len(referenced)}件しか取れていない(実測98件)。"
        "_REFERENCE_RE が壊れて検査が空回りしている疑い"
    )
    assert len(defined) >= _MIN_DEFINITIONS, (
        f"決定ログ側の定義が{len(defined)}件しか取れていない(実測98件)。"
        "_DEFINITION_RE が壊れて検査が空回りしている疑い"
    )

    dangling = sorted(
        (name for name in referenced if name not in defined),
        key=lambda name: int(name[1:]),
    )
    assert not dangling, "決定ログに記載の無い裁定が参照されている:\n" + "\n".join(
        f"  {name}: {', '.join(sorted(referenced[name]))}" for name in dangling
    )


def test_both_heading_and_bold_paragraph_forms_count_as_a_definition() -> None:
    """**両方の書き方を定義として認めている**ことを固定する。

    決定ログは B1〜B32 を太字の段落、B33 以降を見出しで書いている。
    片方だけを定義と見なす実装に戻すと、古い裁定が全部「未定義」になり、
    上のテストが大量の偽陽性で落ちる —— そのとき下限を下げて黙らせる、
    という誤った直し方を防ぐために、ここで両形式を明示的に押さえる。
    """
    # 末尾2行は**定義に数えない**形: 本文中の言及と、「裁定」を含まない見出し。
    # (ここに並べる番号は、すべて決定ログに実在するものにしてある ——
    #  このファイル自身も走査対象なので、架空の番号は書けない。)
    sample = """**Ruling B20(指摘8): 段(役割)は verbatim の任意スロット
## Ruling B31: リリースの同一性を切り離す
### 裁定 B33: §5の中核証拠をスクリプト化する
## 裁定 B100: 生成物はLinuxで作る
本文中の裁定B97への言及は定義ではない
### B37: 逆向きの作り直しも起きていない"""
    assert _defined_rulings(sample) == {"B20", "B31", "B33", "B100"}


def test_the_decision_log_defines_b100() -> None:
    """この検査を入れる動機になった B100 が、実際に記載されていること。"""
    assert "B100" in _defined_rulings(_DECISION_LOG.read_text(encoding="utf-8"))
