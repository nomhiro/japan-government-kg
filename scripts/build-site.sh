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

# 最終レビュー⚠️E(実測): Windowsのコンソールコードページ(cp932)で
# stdoutが開かれると、下のuv run python -c "..."が出す日本語(「パス分の
# ブロック」等)が文字化けする。serve.sh・generate-schema.shで既に2回
# 直した欠陥の3回目(実測: 修正前は`パス分のブロック`が
# `�p�X���̃u���b�N`のように化けた)。
export PYTHONUTF8=1

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

# 最終レビュー要修正1(裁定B40): _headers も生成物(made)から作る。
# 手書きのワイルドカード /def/* を置いたままにすると、モジュールが増えても
# 減っても _headers 側が追従せず、欠落したパスに text/turtle を被せて
# しまう(要修正2と同じ欠陥の型)。
headers_path = site.write_headers(made, pathlib.Path('site'))
print(f'  {headers_path} ({len(made) - 1} パス分のブロック + 共通ブロック)')
"

echo
echo "完了: site/ を Cloudflare Pages に配信する"
echo "  プレビュー: npx wrangler pages dev site"
echo "  公開:       npx wrangler pages deploy site --project-name jgkg --branch main"
echo "              **--branch main は必須。** 省略すると wrangler が現在のgitブランチ名を"
echo "              使い、本番ではなくそのブランチのプレビュー配信になる(独自ドメインは"
echo "              更新されない)。2026-08-25に実際に踏んだ: worktreeのブランチ名で"
echo "              デプロイが成功したのに jgkg.norr-tech.com は古いままだった。"
echo
echo "**公開は外向きの操作なので、実行者が意図して行うこと。**"
