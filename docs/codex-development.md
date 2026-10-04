# Codexでの開発

## 開始と進め方

最新mainから専用worktreeを作り、そこでCodexの新しいチャットを開始する。
以下はリポジトリルートで実行するPowerShellの例。ブランチ名は作業ごとに変える。

```powershell
git fetch origin
git worktree add -b codex/my-change ../jgkg-my-change origin/main
Set-Location ../jgkg-my-change
codex
```

Codex desktopでは同じworktreeをプロジェクトとして開く。ルートの AGENTS.md と .agents/skills/ はリポジトリに含まれ、ユーザー共通設定のコピーは不要。
開始時に「適用するAGENTS.mdと利用可能なjgkgスキルを列挙して」と依頼して認識を確認する。
CLIの場合も認証済みのCodexを使う。Claudeのsuperpowers・MCP・通知フックは前提にしない。
ブラウザ確認にはそのセッションで利用できるブラウザツールを使い、利用できなければ未検証として残す。

$jgkg-development で対象仕様と関連裁定を読み、小さな単位で実装する。
$jgkg-review で仕様・品質・消費者までの到達性を確認し、指摘を修正する。
$jgkg-verification で変更に応じた検査を行い、根拠・未検証部分を記録する。
新しい裁定は decision-log.md、進捗変更は status.md に残す。過去の履歴は書き換えず、訂正を明示する。

## 現行統制と根拠

裁定台帳は時系列で訂正を含む。以下は現行手順の要点であり、対象変更に関する後続裁定も検索する。

| 統制 | 判断ログでの根拠 |
|---|---|
| 数字・説明を他者の報告から転記せず、一次資料・実ファイル・実行結果で確かめる。標本の層と未確認の範囲を書く | 観察O14/O15とO13の全面訂正 |
| 実データを利用者と同じHTTP入口から検証する。内部関数の成功だけでは完了にしない | B69と直後の自己訂正 |
| 実測前に接続先のmanifest、グラフ一覧・件数等から期待するデータセットかを確認する。ポートを取るだけでは確認にならない | 観察O16 |
| 再発防止テストは欠陥を検出することを確かめる。壊し確認は退避または隔離コピーで行い、未コミット変更を巻き戻さない | B102 |
| ステージ対象を限定し、push前に外向きのコミット一覧を確認する | 観察O18 |
| APIの配備済み応答と画面が読む形を照合し、ブラウザで操作・画面幅・失敗時表示も見る | B105/B106/B112/B114 |
| 配信直後の伝播待ちはキャッシュ迂回で検査し、その後通常取得を確認する | B107（B84を訂正） |

独立レビューが依頼・環境で利用できる場合は実装とレビューを分ける。同じ実装者の再点検を独立レビューと呼ばない。
並列作業はファイル所有とworktreeを分離する。生成・検証は順番に行い、実ブラウザの共有操作は直列化する。
長時間処理の停止前に対象プロセス・ログ・出力の進展を確認し、他プロジェクトのサービスを止めない。

## 環境と検証コマンド

Python 3.12以上とuvはデータ層・API・pytestに使う。LinkMLはlockfileの固定版を使う。
Node.jsとnpmはReactフロントエンドに使う。package.jsonの最低条件は22.13以上だが、現行lockfileのjsdomは22.22.2以上の22系（または24.15以上の24系、26以上）を要求する。CIと揃え、最新の22系を推奨する。
Docker DesktopはFuseki/Jena・コンテナ確認が必要な変更だけで使う。
.shはGit Bashで実行する。Windowsのsystem32のbash（WSL）と混同しない。

```powershell
$env:PYTHONUTF8 = '1'
uv sync --locked --extra dev
npm.cmd --prefix frontend ci
uv run ruff check src tests scripts
uv run pytest tests/
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run typecheck
```

Git Bashはインストール済みの実行ファイルを指定する。標準配置の例:

```powershell
$gitBash = Join-Path $env:ProgramFiles 'Git/bin/bash.exe'
& $gitBash scripts/generate-schema.sh
git status --short -- schema/generated/
& $gitBash scripts/generate-frontend-types.sh
git status --short -- frontend/openapi.json frontend/src/api/openapi-types.ts frontend/src/generated/labels.json
uv run python -m jgkg.base_uri --check
uv run python scripts/check-frontend-build.py
& $gitBash scripts/build-site.sh
uv run python scripts/check-site-build.py
```

各コマンドの終了コードを確認し、失敗したら後続に進まず原因を直す。
生成物の変更が意図したものか差分で確認する。生成器の再現性検査では再実行で追加差分が出ないことを確認する。
スキーマ生成物の正はLinux出力（B100）。Windows生成はコミット前に以下のLinux生成で置き換える。
PowerShellから実行するためMSYSのパス変換は発生しない。コンテナ用の仮想環境を分離し、ホストの.venvを上書きしない。

```powershell
docker run --rm -v "${PWD}:/w" -w /w -e PYTHONUTF8=1 -e UV_PROJECT_ENVIRONMENT=/tmp/venv python:3.12-slim bash -c 'pip install -q uv && uv sync --locked --quiet && bash scripts/generate-schema.sh'
```

Git BashからWindows Pythonを使う場合はUTF-8で実行する（PYTHONUTF8=1）。CIの全検査の正本は .github/workflows/ci.yml。
pytestは既定で実ネットワークを遮断する。実データ取得・大型ビルドは通常のテストと区別し、必要性と操作範囲を確認して行う。

## PRと配信

変更ファイルを明示してステージし、ステージ済み差分と origin/main..HEAD の履歴を確認する。
依頼で許可された範囲でブランチをpushし、main向けPRを作る。PRには問題、変更後の挙動、検証、未検証部分を書く。
CI成功とレビュー指摘の解消を確認してマージする。mainへのpushでCloudflare Pagesの本番配信が起動する。
マージ後のCIのdeploy結果を確認し、必要な本番検査を行う。配信スキップ・失敗を成功と報告しない。
本番検査コマンドは既存CIと同じものを使う:

```powershell
uv run python scripts/verify-site.py https://jgkg.norr-tech.com --wait-attempts 20 --wait-delay-seconds 15 --attempts 3 --delay-seconds 30
```

## 移行の境界

ユーザー共通のモデル・権限・通知・プラグインは移行しない。追加のMCPやプロジェクトconfig.tomlは現在の手順に必須ではない。
既存の計画・裁定・Claude worktreeは保存する。superpowersの実行指示だけをプロジェクトスキルへ置き換え、履歴に残る当時の実行方式は保持する。
