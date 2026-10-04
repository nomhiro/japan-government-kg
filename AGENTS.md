# JGKG 開発エージェントの作業規約

応答・作業記録は日本語で書く。このリポジトリは日本政府の公式サービスではなく、公開一次資料を出典付きKGに統合する第三者の公共財プロジェクト。

## 開始時に確認するもの
- README.md と docs/status.md で構成・進捗を確認する。記載日と実コードの差も確認し、古い進捗を現在の状態と断定しない。
- 設計の正本は docs/superpowers/specs/ の対象仕様書。データ層の起点は 2026-08-22-japan-government-kg-design.md。
- 実装判断は docs/decision-log.md の関連裁定を読む。後の訂正を検索し、撤回された初稿を規則として使わない。実測の一次記録は docs/measurements-phase1.md。
- 作業計画は docs/superpowers/plans/。歴史的なサブエージェント名・モデル名・superpowersプラグインへの指示は必須依存ではない。現行手順は docs/codex-development.md。

## 構成と不変条件
- src/jgkg/: コネクタ・正規化・RDF・検証・API。schema/: LinkMLとOWL/SHACL。queries/cq/: コンピテンシー質問。frontend/: React/TypeScript。scripts/: 生成・ビルド・検査。deploy/・docker/・fuseki/: 配備。
- 公開URIを不用意に改名しない。URI構築は src/jgkg/uris.py に集約する。
- 事実には一次資料・取得日・出典を残す。名前付きグラフの更新は置換。推測で名称・関係・数字を補わない。
- schema/generated/ とフロントエンドのAPI型・ラベルは生成元を変更して再生成する。生成物だけを手編集しない。
- 生データ、data/artifact/、.env、認証情報をコミットしない。既存worktree・ローカルデータを保存する。
- テスト成功、実データ確認、本番確認を区別して報告する。確認していない層は未検証と書く。

## 開発ハーネス
- 実装は $jgkg-development、レビューは $jgkg-review、検証は $jgkg-verification を使う。各スキルは .agents/skills/ にある。
- 最新mainを基点に codex/ 接頭辞のブランチと専用worktreeを使う。変更はPR経由で統合する。
- 生成とテストを同じworktreeで並行実行しない。ブラウザを共有して並行操作しない。他者の稼働中に共有ファイルの編集・rebase・プロセス停止をしない。
- タスク依頼はpush・マージ・公開の包括許可ではない。外部操作は依頼の範囲に従う。mainへのマージは本番配信を起動する。

