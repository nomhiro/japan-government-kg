#!/usr/bin/env python
"""ベースURIの一括差し替え / 整合検査のCLI。実体は jgkg.base_uri にある。

    uv run python scripts/set-base-uri.py --check
    uv run python scripts/set-base-uri.py https://example.test/kg
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jgkg.base_uri import main

if __name__ == "__main__":
    raise SystemExit(main())
