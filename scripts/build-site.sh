#!/usr/bin/env bash
# 公開オントロジーを静的配信できる形に組み立てる。
#
# **語彙のURIはハッシュURI(.../def/core#Agent)なので、フラグメントはサーバに届かない。**
# したがって /def/core を返すだけで dereferenceable になり、**トリプルストアを立てる前に
# オントロジーだけを公開できる。** 設計書の原則1(本体はオントロジーとKG)に照らして、
# ここが最初に公開すべきものである。
#
# 出力先の site/def/ は .gitignore 対象。生成物の正はあくまで schema/generated/ である
# (同じものを2箇所にコミットしない)。
set -euo pipefail

if [ -f .env ]; then
  set -a
  . ./.env
  set +a
fi

# **配信物のドメインがずれていたら公開してはならない。** 先に整合検査を通す。
# ずれたまま公開すると、利用者が解決できないIRIを掴むことになる。
echo "== ベースURIの整合検査 =="
uv run python -m jgkg.base_uri --check

echo "== 生成物を作り直す(コミット済みと一致することを確認する) =="
./scripts/generate-schema.sh >/dev/null
if ! git diff --quiet schema/generated/; then
  echo "生成物がコミット済みのものと一致しない。先に確認すること" >&2
  git --no-pager diff --stat schema/generated/ >&2
  exit 1
fi

echo "== 配信物を組み立てる =="
uv run python -c "
import pathlib
from jgkg import site
made = site.build(pathlib.Path('schema/generated'), pathlib.Path('site'))
missing = site.missing_paths(pathlib.Path('schema/generated'), pathlib.Path('site'))
if missing:
    raise SystemExit(f'生成物が要求しているのに配信物に無い: {sorted(missing)}')
for p in sorted(made):
    print('  ', p)
"

echo
echo "完了: site/ を Cloudflare Pages に配信する"
echo "  プレビュー: npx wrangler pages dev site"
echo "  公開:       npx wrangler pages deploy site --project-name jgkg"
echo
echo "**公開は外向きの操作なので、実行者が意図して行うこと。**"
