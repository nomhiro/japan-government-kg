# フロント再設計 — 製品デザイン仕様(2026-09-12)

設計書 `2026-08-22-japan-government-kg-design.md` §9.2 が約束した「検索起点・型別レイアウト・全表示に出典」を、
**利用者シナリオから組み直した製品デザイン**として詳細化する。原則1(本体はオントロジーとKG、
アプリは検証装置)は維持する。何を変えたかは裁定B104・B105(`docs/decision-log.md`)に記録した。

モック(骨格3案+トーン3種。レビュー済み): `docs/mockups/2026-09-12-redesign/`
(設計キャンバス: https://claude.ai/code/artifact/d914de65-1dcd-4fae-99ae-06dda16b2a3f)

## 0. なぜ作り直すか

現行フロント(`frontend/`。素のTS + Vite + Sigma.js、手書き約3,500行)は「表示が偽を主張しない」
「全表示に出典」の規律は徹底している。一方で**利用者が何をしに来てどう帰るかの動線・情報設計・
視覚言語は未設計**である:

- グローバルナビが無く、`#/path` は事業ページのボタンからしか到達できない
- 検索結果が `<li>` + click で、キーボードで選べない
- 属性1行ごとに出典表記が本文より長く繰り返される
- §9.2 の「型別レイアウト」が未実装で、全型が同じ属性表
- 近傍グラフは同心円配置で毛玉化し、ズーム・フィルタ・レイアウト切替が無い
- チャットは同期で数十秒沈黙し、履歴がURLに残らない
- メディアクエリ2本のみでモバイル未対応。フォーカス表示・ランドマーク・グラフの代替表現が無い

利用者の要求: 「国の施策の関係性、お金の関係性を**俯瞰**でき、かつ関係性を**追って調査**できる」。
対象は全類型(市民 / 報道・研究者 / 法務・政策担当 / 開発者)。

## 1. 利用シナリオと成功条件

| 類型 | 代表タスク | 成功条件 |
|---|---|---|
| A 市民 | 国のお金はどこへ | トップ→府省→上位事業→支払先→一次資料を**4クリック以内**。専門用語なし。各数字に出典・取得日・「下限」等の限界が同じ画面に見える |
| B 報道・研究者 | この法人/事業を追う | 法人名で検索→年度別・事業別の受取額→所管府省・根拠法令へ遡る。**URLで状態を共有**でき、表を書き出せる |
| C 法務・政策 | 法令の所管と関連事業 | 法令→所管府省(旧省庁の継承含む)→根拠とする事業→改正履歴。改正が近傍に出ない現状の制約は画面で正直に示す(データ層修正後は辺として出す) |
| D 開発者 | KGそのものを使う | 「データとAPI」から語彙 `/def/`・ダウンロード・API・CQ一覧・鮮度・ライセンスに1クリック |

## 2. 製品の骨格: 把握 → 追跡 → 探索(+聞く)

### 2.1 情報構造とルート

ハッシュルーティングを維持する(理由は `frontend/src/router.ts:1-20`。`/def/*` の恒久LOD識別子を壊さない)。

共通シェル: 告知バー(静的HTMLのまま) / ヘッダ(ワードマーク、**常設オムニボックス**、
ナビ「全体を見る・つながりを辿る・経路・聞く・データとAPI」、テーマ切替) / 「聞く」は全画面共通の**サイドドロワー**。

| ルート | 層 | 内容 |
|---|---|---|
| `#/` | 把握 | トップ(2.2-1) |
| `#/search?q=` | — | オムニボックスの全結果(型フィルタ・もっと見る) |
| `#/entity/{id_path}` | 追跡 | **型別ダッシュボード**(府省/事業/法人/法令/その他)。タブ: 概要・つながり(グラフ)・すべての関係・出典と鮮度 |
| `#/explore?center=&depth=&lens=&axes=&layout=` | 探索 | 全画面ワークベンチ(モック DirectionB) |
| `#/path?from=&to=` | 探索 | 経路探索(ワークベンチの1モードとしても開ける) |
| `#/chat` | 聞く | ドロワーと同じ部品の全画面版(共有用) |
| `#/data` | — | データとAPI: 鮮度(CQ10)・ライセンス・ダウンロード・語彙・API・CQ一覧 |

不明なハッシュは404画面(現状は無言で検索へ戻る)。

### 2.2 画面仕様

1. **トップ「全体を見る」**(モック Main): ヒーロー1文+鮮度チップ / 俯瞰カード3枚(当初予算・
   国が自ら支払った額「下限」・支払先の特定度の内訳帯) / 府省の構成比帯(対数にしない)+上位N行+
   「厚労省を除いて見る」 / 「たとえば、こう辿れます」(児童手当の 国→1,741市町村→受給者、三菱重工業) /
   「問いから入る」CQカード / 要求と査定の5年表+執行率 / フッタ(データとAPI・出典と利用条件)。
   **数字はすべて `/overview`(CQ12〜20)の答え**(裁定B103)。
2. **府省ページ**: 当初予算と5年推移(CQ15束縛)、所管事業の予算額順(新CQ21。ページング)、
   所管事業の予算と執行の推移(新CQ22)、所管法令(既存 `/entity` の incoming `jurisdiction`)、旧省庁の継承。
3. **事業ページ**(モック AEntity): 予算の推移 2021→2025(新CQ23。当初/補正/現額/執行/翌年度要求)、
   資金の流れ(支出先ブロックの図。新CQ24。**合計を作らず入口の額+「下限」**。通過段は「同じお金」と明記。裁定B96→B97)、
   国自らの間接経費(新CQ25)、支払先の金額順+照合区分+属する段(新CQ26)、根拠法令(未解決参照は
   「特定できず・理由」で正直に)、所管府省。
4. **法人ページ**: 年度別受取額(新CQ27)、事業別(新CQ28)、遡上した府省(新CQ29。**CQ4をそのまま束縛しない**。
   実測8.75秒)、所在地、法人番号。
5. **法令ページ**: 所管府省と継承チェーン(新CQ30)、根拠とする事業の予算額順(新CQ31)、
   改正履歴(新CQ32。`law:lawId` の等値結合で**今のKGでも出せる**)、公布日・法令番号。
6. **その他の型**(支出・ブロック・年度予算・未解決参照など): 汎用レイアウト(属性表+関係)。
   支出は「金額+支払先」を並べて描く(表示側で解決。合成ではない)。
7. **探索ワークベンチ**(モック DirectionB): 左レール=レンズ(つながり/予算で見る/法令で見る/資金の流れで見る)・
   軸チップ(一致しないものは薄く)・深さ・レイアウト(ForceAtlas2/同心円)・辺ラベル(選択時/常時)・
   凡例(いま画面にある型だけ) / 中央=Sigma キャンバス+ズーム/フィット/「全ての関係を表で」+状態行
   (ノード数・辺数・分岐上限ノード) / 右=インスペクタ(型・6軸・属性・出典・**述語を選んで展開**・
   中心にする・経路の始点・詳細ページ)。状態はすべてURLに載せる。
8. **経路**: 始点/終点はオムニボックスで選ぶ。結果は横一列のチェーン+辺ごとの出典。
   `found=false` を「存在しない」と描くのは `exhaustive=true` のときだけ(`describePathResult` を維持)。
9. **聞く(ドロワー)**: どの画面からも「この画面について聞く」で開き、現在の `id_path` を文脈として渡す。
   **道具の開始/終了を逐次表示**(SSE)、答え→表→「調べたエンティティ」チップ→出典→道具履歴の順(裁定B94)。
   履歴は sessionStorage。上限(毎分5回・日次予算)到達はそのまま表示。
10. **データとAPI**: 鮮度表(CQ10)、PDL1.0 と編集・加工主体の表記、GitHub Releases、`/def/`、
    API使い方、CQ一覧(問いと `.rq` へのリンク)。

### 2.3 横断パターン(React化しても守る規律)

- 画面に出す数字は `queries/cq/*.rq` の答え(裁定B103)。型別ページは「一般形CQ + `# @bind` 注入」で同じ規律に乗せる(§5-B)
- 表示名の出所はオントロジー側だけ(`labels.json` / `skos:prefLabel`。裁定B78・B88)。フロントで合成しない
- 全表示要素に出典(ソース名・取得日・ライセンス)。`available:false` は空リンクを描かず「出典が取れていない」(裁定B86)
- 打ち切り・上限・「下限」を隠さない: `truncated` / `nodes_truncated` / `fanout_truncated_nodes` / `exhaustive` を
  `<Truncation>` / `<Caveat>` 部品に固定し vitest で縛る(裁定B82)
- 状態はURLに(共有・復元)。ローディングはスケルトン
- 「描画された」≠「動く」: 押せるものを押すテストを書く(裁定B93)

## 3. デザイン言語

デジタル庁デザインシステム(DADS)を**参考**にし、見やすさ・操作しやすさを優先する。
ただし政府ロゴ・公式ブランド色・公式サイトを示す要素は使わず、「日本国政府とは無関係」の告知は維持する(裁定B105)。

- **書体**: Noto Sans JP(Google Fonts。フォールバック Hiragino Sans / Yu Gothic UI)。本文16px・行間1.7、
  見出し 20/24/32/40。数字は `tabular-nums`
- **色**: ライト/ダーク両対応(トグル+システム追従)。主色は明快な青1色(DADSの公式色そのものは使わない)、
  注意色は現行 `--signal` 系の落ち着いた赤、6軸の型色は `frontend/src/graph-colors.ts` の導出を維持。
  Sigma は CSS を読まないので `graph-theme.ts` 経由(裁定B95)
- **形**: 8pxグリッド、角丸8px、影は使わないか1段のみ、罫線で区切る。タップ領域44px以上。
  フォーカスリングは太く高コントラスト
- **禁止**: グラデーション背景、絵文字、左ボーダー付きカード、ガラス風、Inter/Roboto、意味の無い数字やアイコンの羅列
- **アクセシビリティ**: ランドマーク(`header/nav/main/footer`)、スキップリンク、検索結果と候補は
  `<button>` / `role="option"` でキーボード操作、グラフには「全ての関係を表で」の代替、`prefers-reduced-motion`、
  色だけに依存させない(凡例に型名、照合区分に文言)
- **レスポンシブ**: 400px幅で成立。グリッドは1列に、表はカード化、グラフ高さはビューポート基準、
  ワークベンチはレール/インスペクタをシートに畳む

## 4. 技術方針(React移行)

- **スタック**: React 19 + `@vitejs/plugin-react@^5.1`(Vite 6 のまま。6.x は Vite 8 必須と実測) /
  自前ハッシュルータ維持(`router.ts` の純粋部分を `app/routes.ts` へ、`useRoute` は `useSyncExternalStore`) /
  データ取得は自前 `useApiQuery`(AbortController+最新のみ描く。TanStack Query は必要になった時点で) /
  グローバルCSS+CSS変数トークン(CSS Modules はハッシュがビルド環境に依存しないか未確認なので当面入れない) /
  Sigma は `features/graph/GraphCanvas.tsx` **1ファイルだけ**が import し `useEffect` でラップ /
  `graphology-layout-forceatlas2` は同期版・固定反復・同心円を初期位置に(決定的) /
  テストは vitest + jsdom(コンポーネントテストだけ `// @vitest-environment jsdom`)+ Testing Library、
  E2E は `@playwright/test`(Chromium、`page.route` でフィクスチャ、別ワークフローから開始)
- **守る制約**: `frontend/index.html` の告知は静的に残す(`src/jgkg/site_verify.py` が本文検査) /
  `base` は `/` のまま / `frontend/public/` を作らない(`site.py` の `sync_app` が `index.html`・`assets/` 以外を捨てる) /
  単一 `tsconfig` + `noEmit` / ビルドID・時刻を埋め込むプラグイン禁止(`scripts/check-frontend-build.py`) /
  `client.ts` の `VITE_API_BASE` 判定は不変 / `generated/labels.json`・`api/openapi-types.ts`・`openapi.json`
  のパスは動かさない / `tests/test_decision_log_references.py` の対象拡張子に `.tsx` を追加
- **移行方式**: Strangler。`App.tsx` が route ごとに React 版か `LegacyView`(旧 innerHTML ビューを
  マウントする橋)を選び、画面単位で `main` に入れて毎回本番検証を通す。
  順序: 土台 → chat → entity+graph → search+overview → path → 旧ビュー削除 → E2E → FA2
- **既存テスト**: 純関数テストは移動のみ。HTML文字列を返す関数のテストは「判断だけ返す純関数」+
  「コンポーネントで `queryByRole("link")` が null」に置き換え、同一PR内で入れ替える

## 5. API・CQ・データ層の追加

| Phase | 内容 |
|---|---|
| **A 出典拡充+鮮度** | `Provenance` に `source_name`(dcterms:source)・`license_url`(dcterms:license)・`generated_by`・`recorded_on`・`source_sha256[]` を**任意フィールドで追加**(既存5項の名前・意味は不変)。`_build_provenance_query` に OPTIONAL、`get_entity_detail` は `_hydrate_graphs` 1回に統一。CQ7 も同列を返す。鮮度は **`/overview` に `freshness`(CQ10)を追加**(新ルート不要。裁定B103の機構に乗る) |
| **B 型別集約+展開制御** | 新ルート `GET /summary/{kind}/{id_path}`(kind=ministry/project/organization/law。判別共用体。各セクションに `limit/offset/truncated` と `sources`)。方式は**一般形CQ + WHERE内 `# @bind ?var kind` 行に `VALUES` を1行注入、`# @pageable` で `LIMIT/OFFSET` 付加/置換**。spy テストで「注入を除去すると `.rq` 本文と完全一致」を検査。新CQ21〜32 は `queries/cq/` の同じ台帳に番号を振る。`/neighborhood` に `predicates=`・`direction=`(裁定B74の対処。述語IRIは `all.owl.ttl` から起動時導出)、新 `GET /neighborhood/{id}/summary`(述語×方向の件数)。**前提作業**: `fuseki/kg.ttl` に `arq:queryTimeout`(値は実測で決め、起動時 `/overview` を通す)、`RemoteKGClient.query` に `timeout` 引数 |
| **C チャットSSE** | `handle_chat` を `iter_chat` ジェネレータ化し、同期 `/chat` と新 `POST /chat/stream`(`text/event-stream`: `tool_call_start/end`・`final`・`error`・keep-alive)を同じ経路に。レート制限・日次予算はレスポンス開始前に判定。同時ストリーム数の上限を設定に追加。トークン `delta` は api-version `2024-10-21` で `stream_options.include_usage` が返るか**実測してから** |
| **D 検索改善** | `types=`・`offset=`・`mode=prefix|contains`・複数語AND。Lucene は入れない(索引をイメージ層に焼く方式・rdflib バックエンドとの二重化と相性が悪い) |
| **E データ層(KG再作成)** | (a) `AnnualBudget` に `skos:prefLabel`(APIが読むのは prefLabel。`dcterms:title` ではない) (b) `Expenditure` の表示名は KG を変えず表示側で「金額+支払先」を推奨 (c) `UnresolvedReference` に `unresolved_text` を prefLabel として付与(検索対象には入れない) (d) `LawRevision → Law` に `law:revisionOf` を追加(`lawId` リテラルは残す)。4件を**次のデータ更新リリースに束ねる** |

横断: API↔フロントの版ずれ(裁定B103追記7)を避けるため変更は**加算のみ**。APIを先に配備しフロントを後に配備し、
配備後に実ブラウザで `undefined` が無いことを見る。

## 6. フェーズ

| Phase | 届けるもの | 依存 |
|---|---|---|
| 0 土台 | React + plugin-react + jsdom/Testing Library、`main.tsx`/`App.tsx`/`useRoute`/`LegacyView`、トークンとシェル(告知・ヘッダ・オムニボックス・ナビ・テーマ切替・フッタ)。**既存4画面は旧ビューのまま動く**。sha256 2回一致を React 入りで実証しバンドル増分を記録 | なし |
| 1 把握 | 新トップ(React)、`#/search`、`#/data`、404画面。API Phase A | 0 |
| 2 追跡 | 型別ダッシュボード4種+汎用、`/entity` の `limit` と「もっと見る」。API Phase B | 1 |
| 3 探索 | ワークベンチ(レンズ・軸チップ・FA2・インスペクタ・述語指定展開・URL状態)、経路の統合、旧 `views/*.ts` と `LegacyView` の削除 | 2 |
| 4 聞く | ドロワー化、文脈渡し、SSE(API Phase C) | 0 |
| 5 仕上げ | 検索改善(Phase D)、Playwright 最小スペック、モバイル・a11y の総点検 | 3, 4 |
| 6 データ層 | Phase E を次のデータ更新に同乗 | 独立 |

## 7. 検証

- 毎PR: `npm test` / `uv run python scripts/check-frontend-build.py` / `bash scripts/build-site.sh` /
  `check-site-build.py` / `uv run pytest` / 配信後 `verify-site.py https://jgkg.norr-tech.com`(`VITE_API_BASE` を揃える。裁定B101)
- 実ブラウザは**押せるものを押す**(裁定B93の表を再利用): ノードクリック・辺クリック・展開・状態行・凡例・
  ダーク切替(ピクセル確認)・検索結果のキーボード選択・400px幅。読み込まれた `script[src]` のハッシュが今のビルドか毎回確かめる
- API: 新CQの束縛版を実索引で測り `docs/measurements-phase1.md` に記録。**1秒超なら設計見直し**。
  フィクスチャの緑だけで完了にしない
- SSE: 配備後に `curl -N` で逐次到着を確認、`X-Forwarded-For` の実値をログで確認
- 数字の整合: 画面の値と `run_cq.py` の答えを突き合わせる

## 8. 未決(実装中に裁定する)

1. `AnnualBudget` の表示名: `src/jgkg/rdf/emit.py` とテストは原則7を根拠に**付けない**ことを固定、
   `docs/status.md` は付けると決めており矛盾。推奨は「同一ソースの2列からの導出なので付ける」
2. `Expenditure` の表示名: 表示側で「金額+支払先」を並べる(推奨)か、`payeeLabel` を全行に書いて prefLabel を合成に変えるか
3. Fuseki `arq:queryTimeout` と API 側リクエスト経路タイムアウトの値(仮置き→実測で確定)
