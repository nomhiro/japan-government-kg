"""FastAPIのOpenAPIスキーマを`frontend/openapi.json`へ書き出す(D-5)。

    uv run python scripts/export-openapi.py

**ネットワークは使わない。** `create_production_app()`は`RemoteKGClient`を
構築するだけで、実際にFusekiへ接続するのは各ルートハンドラが呼ばれたとき
(または起動時のlifespan/`warm_up`)だけである。`app.openapi()`はルート定義
から静的にスキーマ辞書を組み立てるだけで、どちらも起動しない——したがって
Fusekiが動いていなくても実行できる(`tests/conftest.py`のソケット遮断にも
一度も触れない)。

**手書きしない理由(D-5ブリーフ設計2)**: API応答の形はこのセッション中に
3回変わった(`id_path`の追加・出典の正規化・`Provenance.available`の追加)。
フロントエンドの型を手書きすると必ず遅れる——`src/jgkg/api/models.py`と
`app.py`から機械的に導出し、`frontend/src/api/openapi-types.ts`
(`openapi-typescript`が読む)の入力にする。

**生成物はコミットする**(`schema/generated/`と同じ方針)。CIは
`scripts/generate-frontend-types.sh`を再実行して差分が無いことを確認する
(schema/generated/の regen-diff チェックと同じ形)。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

# `src/`をpathに通す(このリポジトリの他のscripts/*.pyと同じ理由:
# pytestはpyproject.tomlのpythonpathで解決するが、素の`python scripts/x.py`
# 実行はそれを持たない)。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from jgkg.api.app import create_production_app

OUT = Path(__file__).resolve().parent.parent / "frontend" / "openapi.json"


def main() -> int:
    app = create_production_app()
    schema = app.openapi()
    # 生成物のdiff検査(git diff)が意味を持つよう、鍵の順序・インデントを固定する。
    text = json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
