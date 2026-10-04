# 継続収集の台帳

公開情報を分野ごとに収集するための入口・取得手順・更新方針・完全性条件を
17の収集単位として管理する。正本は `src/jgkg/collection_registry.json`。
設計は [継続収集の運用設計](superpowers/specs/2026-10-04-continuous-collection.md)。

## 利用方法

```powershell
uv run python -m jgkg.collection list
uv run python -m jgkg.collection show rs-project-details
uv run python -m jgkg.collection list --json
uv run python -m jgkg.collection validate
```

一覧は実装順で表示する。showは公式入口・発見・取得・更新・件数照合・次の作業を
表示する。validateは構造と出典参照の検査であり、ネットワーク接続や収集成功の
確認ではない。これらのコマンドは取得や定期実行を開始しない。

## 台帳の読み方

| フィールド | 意味 |
|---|---|
| evidence_level | http_sampleは標本HTTP確認、official_documentは公式説明確認、needs_confirmationは追加調査が必要 |
| researched_on / evidence_urls | 調査日と根拠。ページの形式・アクセス条件は実装時に再確認 |
| source_id / terms_status | KG出典レジストリへの参照。needs_reviewは規約確認が未完了 |
| implementation | existing_connectorは既存取得器、local_snapshotは手動取得済み、plannedは未実装 |
| implementation_scope | 取得器や手動取得で実際にできている範囲。状態名だけで全項目取得済みと判断しない |
| discover / retrieve / refresh | 対象列挙、原本取得、更新の手順 |
| check_interval_days | 確認間隔案。上流の更新周期や起動済みスケジュールではない |
| completeness / limitations | 完全性を判断する分母・条件と、未公開・未確認の範囲 |
| identity / kg_mapping | 原資料の識別子とKGへの接続方針。公開URIは既存uris.pyで構築 |
| next_action | 取得器実装に向けた次の作業 |

既存の出典規約を収集台帳に転記しない。新分野は規約を確認してからsources.pyへ
登録し、台帳のsource_idを接続する。現時点のplanned経路には実行コマンドを捏造しない。

## 追加・変更

JSONのcollectionsに契約を追加し、validateで構造を確認する。入口、実測、利用条件の
根拠を残す。分野全体の探索入口しか分かっていない場合はその限界をlimitationsに
書き、機関別の収集元を追加調査する。原本、履歴、認証情報はコミットしない。

2026-08-22の[調査カタログ](research/2026-08-22-government-data-sources.md)は歴史資料。
現在の取得方法はこの台帳と実装コードで確認する。官報の90日制約は記事種別ごとに
異なり、RSはCSVだけでなく詳細JSON APIにも取得経路がある。
