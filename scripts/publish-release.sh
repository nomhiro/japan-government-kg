#!/usr/bin/env bash
# リリースディレクトリの資産を検査し、GitHub Releasesへ公開する。
#
# 使い方:
#   scripts/publish-release.sh data/artifact/2026-08-25-corrected            # dry-run(既定)
#   scripts/publish-release.sh data/artifact/2026-08-25-corrected --publish  # 実際に公開する
#
# **なぜ GitHub Actions のワークフロー(workflow_dispatch等)にしていないか。**
# 「CIでやればいいのに」と将来思う人が同じ結論に至れるように、理由を書く:
#
#   1. 配布物(kg.nq.gz / tdb2.tar.gz / manifest.json)は `data/artifact/<name>/`
#      にあるが、`data/` は `.gitignore` 対象である。CIのチェックアウトは
#      これらのファイルを最初から持っていない。
#   2. CIの中で作り直すこともできない。成果物を再構築するには**レイク
#      (政府データそのもの)**が必要で、レイクも同じ理由でリポジトリに入らない
#      (`data/lake/` も `.gitignore` 対象)。CIが持っているのはソースコードと
#      スキーマの生成物だけであり、実データは無い。
#   3. つまり **公開は本質的にローカルの操作である。** 成果物を実際に
#      手元に持っている人だけが公開できる——ワークフローを作ってボタンを
#      押せる形にしても、そのボタンの裏でCIが読める実データは存在しない。
#
# 偶然だが、これは設計書が繰り返す原則
# 「**外向きの操作は意図の表明を要求する**」とも一致する。手元でこの
# スクリプトを明示的に実行することそのものが、その意図の表明になる。
#
# 実体は `python -m jgkg.publish`(検査・kg.nq.gz作成・リリースノート組み立て・
# `gh` 呼び出しはすべてそちら側でコードとしてテストできる場所に置く。
# このスクリプト自体は薄いラッパーに留める——`build.sh`が引数解釈を
# `pipeline.py`に置いているのと同じ作法)。
set -euo pipefail

# PYTHONUTF8=1: これを付けずにWindows上で直接実行すると、標準出力の日本語が
# プラットフォームの既定コードページ(UTF-8でない)で解釈されて文字化けする
# (serve.sh・build.shと同じ既知の癖)。
PYTHONUTF8=1 uv run python -m jgkg.publish "$@"
