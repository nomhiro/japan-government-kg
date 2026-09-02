"""オントロジーの日本語表示名(`dcterms:title`。裁定B78)を

`frontend/src/generated/labels.json`へ書き出す(D-5)。

    uv run python scripts/export-frontend-labels.py

比較ロジックの本体は`jgkg.frontend_labels`にある(このファイルはCLIの
薄い皮でしかない——理由はそのモジュールのdocstring参照)。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import json

from jgkg.frontend_labels import extract_labels

REPO_ROOT = Path(__file__).resolve().parent.parent
ALL_OWL = REPO_ROOT / "schema" / "generated" / "all.owl.ttl"
OUT = REPO_ROOT / "frontend" / "src" / "generated" / "labels.json"


def main() -> int:
    if not ALL_OWL.is_file():
        print(f"{ALL_OWL} が無い。先に ./scripts/generate-schema.sh を実行すること", file=sys.stderr)
        return 1

    labels = extract_labels(ALL_OWL)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(labels, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} (types={len(labels['types'])}, predicates={len(labels['predicates'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
