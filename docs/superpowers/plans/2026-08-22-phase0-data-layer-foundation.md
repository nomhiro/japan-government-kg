# Phase 0: データレイヤー基盤 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 政府データKGの基盤を作り、「**国の機関と府省**が出典付きでSPARQL検索できる、再現可能に再構築できるKG成果物」を完成させる。

> **範囲についての注記(2026-08-22 に縮小)**: 当初は「全法人(約500万件)」を対象にしていたが、実データでの検算により、全件を1つのグラフに取り込む設計では pydantic オブジェクトと rdflib のトリプルがそれぞれ数GB規模になり破綻することが判明した。設計書§6.2.3が「規模の問題はエンドポイント/成果物の分割で対処し、1つを大きくするな」と明示している(Wikidataが恒久化した解)ため、**Phase 0 は基盤の確立に集中し、全法人の取り込みは Phase 1(plan B)のストリーミング設計に送る**。任意の法人が実際に必要になるのは Phase 1 の縦スライス(支出先法人)である。

**Architecture:** LinkMLをスキーマの単一ソースとし、CIでOWL/SHACL/Pydanticを生成する。コネクタは取得だけを行い、取得時点のスナップショットを不変で保持する。変換は決定的パーサのみ(LLMは使わない)。RDFは名前付きグラフ単位で出力し、各グラフにPROV-Oで出典を付ける。SHACL検証を通ったグラフだけをTDB2インデックスに投入し、tar.gzの成果物として配布する。実行側は成果物を展開して読み取り専用で提供する。

**Tech Stack:** Python 3.12 / uv / LinkML 1.11.1 / rdflib / pySHACL / Apache Jena (TDB2, Fuseki) / docker-compose / pytest

**Spec:** `docs/superpowers/specs/2026-08-22-japan-government-kg-design.md`

**この計画の範囲外(後続計画):**
- 計画B: 法令・予算ドメイン、エンティティ解決の名寄せ本体、縦の接続スライス、更新の一巡、CQ1〜CQ10
- 計画C: FastAPI層、React + Sigma.js の可視化アプリ

## Global Constraints

以下は設計書のプロジェクト全体要件であり、**全タスクの要件に暗黙に含まれる**。

- **ベースURIは設定値 `JGKG_BASE_URI` の1箇所に集約する。** これ以外の場所にドメイン文字列を書かない(CIで検出する。設計書§4.2)
- **URIパターンは以下で固定し、以後変更しない**(設計書§4.2):
  - `{base}/id/org/{法人番号}` — 組織(府省・法人)
  - `{base}/id/law/{法令ID}` — 法令(時点非依存)
  - `{base}/id/law/{法令ID}/{YYYYMMDD}` — 法令の時点版
  - `{base}/id/project/{事業ID}` — 予算事業
  - `{base}/id/budgetitem/{年度}/{科目コード}` — 予算科目
  - `{base}/id/expenditure/{事業ID}/{年度}/{連番}` — 支出(Event)
  - `{base}/id/event/{種別}/{キー}` — その他のEvent
  - `{base}/graph/{ソースID}/{取得日}` — 名前付きグラフ
  - `{base}/def/{モジュール}#{用語}` — オントロジー用語
- **ベースURIのドメインが確定するまで、KGを外部に公開しない**(設計書§4.2、唯一の未決事項)
- **LinkMLのバージョンは `linkml==1.11.1` にピン留めする**(1.11.0がyankされた前例。設計書§5.7)
- **LinkMLの生成物は `.gitignore` に入れず、必ずGitにコミットする。** これがLinkML採用を可逆にする唯一の措置(設計書§5.1)
- **`gen-owl` には `--no-use-native-uris` を明示する。** 既定のTrueだとOWLとSHACL/データが別のIRIを語る(設計書§10)
- **定義文には日本語の言語タグ `@ja` を付ける**(設計書§5.7)。ただし**`--default-language` オプションは `linkml==1.11.1` に存在しない**(公式ドキュメントには記載があるが未リリース機能。実機で確認済み)。生成後に `jgkg.schema_lang` でrdflibを使って付ける。対象は定義文(`skos:definition` / `sh:description`)のみで、要素名である `rdfs:label` には付けない
- **生成スクリプトで `PYTHONUTF8=1` を設定する。** Windowsではstdoutがコンソールのコードページ(cp932)で開かれ、リダイレクト先のTurtleが不正なUTF-8になりrdflibが読めなくなる。どの環境でも同じ生成物になるための要件(設計書§11.1)
- **日英併記の規約: 日本語を `description`、英語を `structured_aliases` + `in_language: en`。** LinkMLの `description` は単一文字列で言語別に持てないため(設計書§5.7)
- **出典を持たない事実をKGに入れない**(設計書§2 原則7)
- **Phase 0 では LLM を使わない**(設計書§8.1)
- **未解決の参照は `UnresolvedReference` として保持し、沈黙させない**(設計書§8.2)
- **SHACL検証に不合格のグラフはストアにロードしない。隔離して報告する**(設計書§8.3)
- **成果物は content-addressed(sha256)、manifestにJenaバージョンを記録する**(設計書§6.3)
- **コードはMIT、ドキュメント・データはCC BY 4.0**(設計書§13)

---

## File Structure

```
japan-government-kg/
├── pyproject.toml                     # uv管理、依存とバージョンピン
├── uv.lock                            # 再現性のためコミットする
├── docker-compose.yml                 # Fuseki(読み取り専用提供)
├── docker/
│   └── jena-tools.Dockerfile          # tdb2.tdbloader を提供する
├── .github/workflows/ci.yml           # 生成・検証・テスト
├── src/jgkg/
│   ├── __init__.py
│   ├── config.py                      # JGKG_BASE_URI ほか設定の単一の入口
│   ├── uris.py                         # URI構築関数。ドメイン文字列を持つ唯一の場所はconfig
│   ├── lake.py                         # スナップショットの保存と読み出し
│   ├── sources.py                      # ソースレジストリ(ライセンス・頻度のメタデータ)
│   ├── connectors/
│   │   ├── __init__.py
│   │   ├── base.py                     # コネクタの共通処理(取得してレイクに保存するだけ)
│   │   └── houjin_bangou.py            # 国税庁 法人番号 全件CSV
│   ├── transform/
│   │   ├── __init__.py
│   │   ├── organization.py             # 法人番号CSV → Organization
│   │   └── ministry.py                 # 国の機関の抽出と府省コードの突合
│   ├── rdf/
│   │   ├── __init__.py
│   │   ├── emit.py                     # Pydanticモデル → 名前付きグラフ
│   │   └── provenance.py               # グラフへのPROV-O出典付与
│   ├── validate.py                     # SHACL検証ゲートと隔離
│   └── build.py                        # 成果物ビルド(tdbloader + manifest + tar.gz)
├── schema/
│   ├── core.yaml                       # LinkML: 6軸の基底クラスとprovenance用語
│   ├── org.yaml                        # LinkML: 組織・府省・法人
│   ├── overlay/
│   │   └── core-axioms.ttl             # LinkMLで書けない公理(加算専用)
│   ├── competency-questions.md         # CQの管理台帳
│   └── generated/                      # 生成物。あえてコミットする
├── data/reference/
│   └── ministry-codes.csv              # 府省コードの参照表(出典を記録)
├── queries/cq/                         # CQに対応するSPARQL
├── tests/
│   ├── conftest.py
│   ├── fixtures/                       # ゴールデンファイル
│   ├── test_uris.py
│   ├── test_schema_consistency.py      # URI整合性・オーバーレイ整合性
│   ├── test_lake.py
│   ├── test_connector_houjin_bangou.py
│   ├── test_transform_organization.py
│   ├── test_transform_ministry.py
│   ├── test_rdf_emit.py
│   ├── test_validate.py
│   ├── test_build.py
│   └── test_competency_questions.py
└── scripts/
    └── build.sh                        # 一連の実行を1コマンドにまとめる
```

**分割の考え方**: `connectors/` は「取得だけ」、`transform/` は「解釈だけ」、`rdf/` は「表現だけ」に責務を限定する。設計書§6.1の境界をそのままディレクトリにしている。パーサを直したときに再取得が不要になり、名寄せの精度改善を他層と無関係に反復できる。

---

### Task 1: リポジトリ骨格とURI構築

**Files:**
- Create: `pyproject.toml`
- Create: `src/jgkg/__init__.py`
- Create: `src/jgkg/config.py`
- Create: `src/jgkg/uris.py`
- Test: `tests/test_uris.py`

**Interfaces:**
- Consumes: なし(最初のタスク)
- Produces:
  - `jgkg.config.Settings` — pydantic-settings のクラス。`base_uri: str` プロパティを持つ
  - `jgkg.config.get_settings() -> Settings`
  - `jgkg.uris.org_uri(houjin_bangou: str) -> str`
  - `jgkg.uris.law_uri(law_id: str) -> str`
  - `jgkg.uris.law_version_uri(law_id: str, date: datetime.date) -> str`
  - `jgkg.uris.graph_uri(source_id: str, fetched_on: datetime.date) -> str`
  - `jgkg.uris.term_uri(module: str, term: str) -> str`

- [ ] **Step 1: `pyproject.toml` を作る**

```toml
[project]
name = "jgkg"
version = "0.1.0"
description = "Japan Government Knowledge Graph - data layer"
requires-python = ">=3.12"
dependencies = [
    "linkml==1.11.1",
    "rdflib>=7.1",
    "pyshacl>=0.29",
    "httpx>=0.28",
    "pydantic>=2.10",
    "pydantic-settings>=2.7",
]

[project.optional-dependencies]
dev = ["pytest>=8.3", "pytest-cov>=6.0", "ruff>=0.9"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/jgkg"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
line-length = 100
target-version = "py312"
```

- [ ] **Step 2: 依存を入れてロックする**

```bash
uv sync --extra dev
```

期待: `uv.lock` が生成される。`linkml` が 1.11.1 で固定されていることを確認する。

- [ ] **Step 3: 失敗するテストを書く**

`tests/test_uris.py`:

```python
import datetime
import pytest
from jgkg import uris
from jgkg.config import Settings


# 既定値と異なるベースURIを使い、設定が実際に読まれていることを証明する。
# .invalid は予約TLDなので、誤って本物のホストを指すことがない。
TEST_BASE = "https://uri-test.invalid/kg"


@pytest.fixture(autouse=True)
def fixed_base(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", TEST_BASE)
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_org_uri_uses_houjin_bangou():
    assert uris.org_uri("8000012070001") == f"{TEST_BASE}/id/org/8000012070001"


def test_org_uri_rejects_malformed_houjin_bangou():
    with pytest.raises(ValueError):
        uris.org_uri("12345")


def test_law_uri_and_version_uri():
    assert uris.law_uri("507M60000100010") == f"{TEST_BASE}/id/law/507M60000100010"
    assert uris.law_version_uri("507M60000100010", datetime.date(2026, 8, 1)) == (
        f"{TEST_BASE}/id/law/507M60000100010/20260801"
    )


def test_graph_uri_encodes_source_and_date():
    assert uris.graph_uri("houjin-bangou", datetime.date(2026, 8, 1)) == (
        f"{TEST_BASE}/graph/houjin-bangou/2026-08-01"
    )


def test_term_uri_uses_fragment():
    assert uris.term_uri("org", "所管") == f"{TEST_BASE}/def/org#所管"


def test_base_uri_trailing_slash_is_normalized(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "https://uri-test.invalid/kg/")
    from jgkg.config import get_settings
    get_settings.cache_clear()
    assert Settings().base_uri == "https://uri-test.invalid/kg"
```

- [ ] **Step 4: テストが失敗することを確認する**

```bash
uv run pytest tests/test_uris.py -v
```

期待: `ModuleNotFoundError: No module named 'jgkg.uris'` で FAIL。

- [ ] **Step 5: `config.py` を実装する**

```python
"""設定の単一の入口。ベースURIのドメイン文字列はここにしか存在しない。"""
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JGKG_", env_file=".env", extra="ignore")

    # ドメイン未確定のため既定は開発用。確定したら .env で上書きする(設計書§4.2)
    base_uri: str = "http://localhost:8080/kg"
    lake_dir: str = "data/lake"
    artifact_dir: str = "data/artifact"
    quarantine_dir: str = "data/quarantine"

    @field_validator("base_uri")
    @classmethod
    def strip_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 6: `uris.py` を実装する**

```python
"""URIの構築。設計書§4.2で固定したパターンをここだけで表現する。"""
import datetime
import re
from urllib.parse import quote

from jgkg.config import get_settings

HOUJIN_BANGOU_RE = re.compile(r"^\d{13}$")


def _base() -> str:
    return get_settings().base_uri


def org_uri(houjin_bangou: str) -> str:
    if not HOUJIN_BANGOU_RE.match(houjin_bangou):
        raise ValueError(f"法人番号は13桁の数字である必要がある: {houjin_bangou!r}")
    return f"{_base()}/id/org/{houjin_bangou}"


def law_uri(law_id: str) -> str:
    if not law_id:
        raise ValueError("法令IDが空である")
    return f"{_base()}/id/law/{quote(law_id, safe='')}"


def law_version_uri(law_id: str, date: datetime.date) -> str:
    return f"{law_uri(law_id)}/{date:%Y%m%d}"


def graph_uri(source_id: str, fetched_on: datetime.date) -> str:
    if not source_id:
        raise ValueError("ソースIDが空である")
    return f"{_base()}/graph/{quote(source_id, safe='')}/{fetched_on:%Y-%m-%d}"


def term_uri(module: str, term: str) -> str:
    # term はパーセントエンコードしない。RDF 1.1 はIRI(RFC 3987)を使い
    # 非ASCII文字をそのまま含められるため、日本語の用語名を符号化すると
    # 読めない識別子になるだけで利点がない
    return f"{_base()}/def/{quote(module, safe='')}#{term}"
```

- [ ] **Step 7: テストが通ることを確認する**

```bash
uv run pytest tests/test_uris.py -v
```

期待: 6件すべて PASS。

- [ ] **Step 8: 既存の `.gitignore` に不足エントリを追記する**

> **`.gitignore` は既に存在する。** このリポジトリは設計フェーズで公開用の `.gitignore` を作っており、`.claude/worktrees/`、`.env.*` / `!.env.example`、Node/フロントエンド、Docker/Fuseki、OS/エディタの除外設定が入っている。**上書きしてはならない。** 既存の内容を確認し、不足している行だけを追記する。

```bash
# まず既存の内容を確認する
cat .gitignore
```

既存ファイルには `data/lake/` と「`schema/generated/` を意図的に無視しない」旨のコメントが既に含まれている。**追記が必要なのは以下の2行だけ**(パイプラインが新たに使うディレクトリ):

```gitignore
data/artifact/
data/quarantine/
```

`# 生データレイク・生成物(設計書§6.1)` のブロック内、`data/lake/` の直後に加える。他の行は触らない。

- [ ] **Step 9: コミットする**

```bash
git add pyproject.toml uv.lock .gitignore src/jgkg/__init__.py src/jgkg/config.py src/jgkg/uris.py tests/test_uris.py
git commit -m "feat: URI構築と設定の単一の入口を追加

ベースURIのドメイン文字列は config.py にのみ存在する(設計書§4.2)。
URIパターンは設計書で固定したものをそのまま表現している。"
```

---

### Task 2: LinkML core モジュールと生成パイプライン

**Files:**
- Create: `schema/core.yaml`
- Create: `schema/generated/.gitkeep`
- Create: `scripts/generate-schema.sh`
- Test: `tests/test_schema_consistency.py`

**Interfaces:**
- Consumes: Task 1 の `jgkg.config`(ベースURIをスキーマのプレフィクスに合わせるため参照する)
- Produces:
  - `schema/generated/core.owl.ttl` — OWL(構造モデル)
  - `schema/generated/core.shacl.ttl` — SHACL(検証用)
  - `schema/generated/core_models.py` — Pydanticモデル。クラス名 `Entity`, `Agent`, `Work`, `Place`, `Event`, `MonetaryItem`, `Concept`
  - `scripts/generate-schema.sh` — 全生成物を作り直すスクリプト

**設計上の注意**: 外部語彙(PROV-O等)を `class_uri` に直接指定しない。自分のURIでクラスを宣言し、対応付けは `exact_mappings` / `close_mappings` で行う。これにより `gen-owl --no-use-native-uris` を指定してもOWLとSHACLが同じIRIを語る(設計書§10のURI整合性)。

- [ ] **Step 1: `schema/core.yaml` を書く**

```yaml
id: http://localhost:8080/kg/def/core
name: jgkg-core
title: 日本政府ナレッジグラフ コアスキーマ
description: >-
  6軸(誰が/何を/どこで/いつ/いくらで/何について)の基底クラスと、
  出典を表す用語を定義する。ドメイン固有のクラスは各ドメインモジュールで
  このモジュールを import して継承する。
license: https://creativecommons.org/licenses/by/4.0/

prefixes:
  jgkgcore: http://localhost:8080/kg/def/core#
  linkml: https://w3id.org/linkml/
  prov: http://www.w3.org/ns/prov#
  skos: http://www.w3.org/2004/02/skos/core#
  dcterms: http://purl.org/dc/terms/
  schema: http://schema.org/
  rdf: http://www.w3.org/1999/02/22-rdf-syntax-ns#
default_prefix: jgkgcore
default_range: string
imports:
  - linkml:types

types:
  LangString:
    uri: rdf:langString
    base: str
    description: >-
      言語タグ付きの文字列。人が読む名称や文章に使う。
      識別子やコードには使わない(それらは言語に依存しないため plain な string を使う)。
      この区別をスキーマに明示することで、どの値が言語依存かがモデルから読み取れる。
      emit が言語タグ付きリテラルを出す一方、既定の `range: string` は
      `sh:datatype xsd:string` を要求するため、この型なしではSHACL検証が必ず落ちる。

slots:
  id:
    identifier: true
    description: このリソースのURI
    range: uriorcurie
  label:
    description: 人間が読む名称
    slot_uri: skos:prefLabel
    range: LangString
  occurred_on:
    description: この出来事が起きた日
    range: date
  valid_from:
    description: この記述が真である期間の始まり
    range: date
  valid_until:
    description: この記述が真である期間の終わり
    range: date
  involves_agent:
    description: この出来事に関与した主体
    range: Agent
  amount_jpy:
    description: 金額(円)
    range: integer
  unresolved_text:
    description: 正準IDに解決できなかった元の参照文字列
    range: LangString
  unresolved_reason:
    description: 解決できなかった理由
    range: UnresolvedReasonEnum
  unresolved_key:
    description: >-
      解決できなかった参照の、ソース側のキー(府省コード等)。ドメイン固有の
      プロパティを UnresolvedReference に足すと閉じたSHACLシェイプに違反するため、
      汎用のキーとしてここで受ける

enums:
  UnresolvedReasonEnum:
    description: 参照が未解決である理由の分類
    # enum_uri を明示しないと、import 側のモジュール(org, all)で名前空間が
    # 再鋳造され、同一の enum が複数のIRIを持つ(実測で確認)。公開する
    # オントロジーの中で同一概念が複数のIRIを持つのは識別子の一貫性に反する
    enum_uri: jgkgcore:UnresolvedReasonEnum
    permissible_values:
      NO_CANDIDATE:
        description: 候補が見つからなかった
      AMBIGUOUS:
        description: 候補が複数あり一意に決められなかった
      OBSOLETE_ORGANIZATION:
        description: 旧省庁名など、現存しない組織を指している

classes:
  Entity:
    abstract: true
    description: 本KGが扱うすべての事物の基底
    slots: [id, label]

  Agent:
    is_a: Entity
    description: 「誰が」の軸。行為の主体。組織と人の上位
    exact_mappings: [prov:Agent]

  Work:
    is_a: Entity
    description: 「何を」の軸。法令・政策・事業・文書・司法判断の上位
    close_mappings: [schema:CreativeWork]

  Place:
    is_a: Entity
    description: 「どこで」の軸。行政区域・住所・地物の上位
    close_mappings: [schema:Place]

  Event:
    is_a: Entity
    description: >-
      「いつ」の軸。時点を持つ出来事。関係を実体化するための中心クラス。
      「AがBに影響した」を直接のエッジにせず、原則としてこのクラスを介す
    slots: [occurred_on, involves_agent]
    close_mappings: [prov:Activity]

  MonetaryItem:
    is_a: Entity
    description: 「いくらで」の軸。予算科目・支出の上位
    slots: [amount_jpy]

  Concept:
    is_a: Entity
    description: 「何について」の軸。主題・指標・制度手続きの上位
    exact_mappings: [skos:Concept]

  UnresolvedReference:
    is_a: Entity
    description: >-
      正準IDに解決できなかった参照。設計書§8.2により、未解決を沈黙させず
      KGに残して計測できるようにするためのクラス
    slots: [unresolved_text, unresolved_reason, unresolved_key]
```

- [ ] **Step 2: 生成スクリプトを書く**

`scripts/generate-schema.sh`:

```bash
#!/usr/bin/env bash
# LinkML から OWL / SHACL / Pydantic を生成する。
# --no-use-native-uris と --default-language ja は設計書§10・§5.7で必須。
set -euo pipefail

OUT=schema/generated
mkdir -p "$OUT"

for module in core org; do
  src="schema/${module}.yaml"
  [ -f "$src" ] || continue
  echo "generating from ${src}"
  uv run gen-owl --no-use-native-uris --default-language ja "$src" > "${OUT}/${module}.owl.ttl"
  uv run gen-shacl --default-language ja "$src" > "${OUT}/${module}.shacl.ttl"
  uv run gen-pydantic "$src" > "${OUT}/${module}_models.py"
done

echo "generated files:"
ls -1 "$OUT"
```

```bash
chmod +x scripts/generate-schema.sh
```

- [ ] **Step 3: 生成を実行する**

```bash
./scripts/generate-schema.sh
```

期待: `schema/generated/core.owl.ttl`、`core.shacl.ttl`、`core_models.py` が作られる。エラーが出た場合はLinkMLのエラーメッセージに従って `core.yaml` を直す(よくある原因は未定義スロットの参照とプレフィクスの欠落)。

- [ ] **Step 4: 生成物が読み込めることを確かめる失敗するテストを書く**

`tests/test_schema_consistency.py`:

```python
"""生成物の整合性テスト。設計書§10の必須項目。"""
from pathlib import Path

import pytest
from rdflib import Graph, OWL, RDF, RDFS, URIRef
from rdflib.namespace import SH

GENERATED = Path("schema/generated")
MODULES = ["core"]


def _load(path: Path) -> Graph:
    g = Graph()
    g.parse(path, format="turtle")
    return g


@pytest.mark.parametrize("module", MODULES)
def test_owl_declares_expected_classes(module):
    g = _load(GENERATED / f"{module}.owl.ttl")
    classes = {str(s) for s in g.subjects(RDF.type, OWL.Class)}
    assert any(c.endswith("#Event") for c in classes), f"Event が宣言されていない: {classes}"
    assert any(c.endswith("#Agent") for c in classes)
    assert any(c.endswith("#UnresolvedReference") for c in classes)


@pytest.mark.parametrize("module", MODULES)
def test_owl_labels_carry_japanese_language_tag(module):
    g = _load(GENERATED / f"{module}.owl.ttl")
    tagged = [o for o in g.objects(None, RDFS.comment) if getattr(o, "language", None) == "ja"]
    assert tagged, "--default-language ja が効いていない(@ja のリテラルが無い)"


@pytest.mark.parametrize("module", MODULES)
def test_shacl_target_classes_match_owl_classes(module):
    """設計書§10 最重要: SHACLの sh:targetClass と OWLのクラスIRIが一致すること。

    gen-owl の --use-native-uris は既定 True で、gen-shacl は class_uri 側を使う。
    既定のままだと OWL とSHACLが別のIRIを語るため、ここで固定する。
    """
    owl_g = _load(GENERATED / f"{module}.owl.ttl")
    shacl_g = _load(GENERATED / f"{module}.shacl.ttl")

    owl_classes = {str(s) for s in owl_g.subjects(RDF.type, OWL.Class)}
    targets = {str(o) for o in shacl_g.objects(None, SH.targetClass)}

    assert targets, "SHACLに sh:targetClass が無い"
    missing = targets - owl_classes
    assert not missing, (
        f"SHACLが対象にしているクラスがOWLに存在しない: {sorted(missing)}\n"
        f"gen-owl に --no-use-native-uris を付け忘れている可能性がある"
    )


@pytest.mark.parametrize("module", MODULES)
def test_pydantic_models_import(module):
    """生成されたPydanticモデルが実際に import できること。"""
    import importlib.util

    path = GENERATED / f"{module}_models.py"
    spec = importlib.util.spec_from_file_location(f"{module}_models", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "Event")
    assert hasattr(mod, "UnresolvedReference")


@pytest.mark.parametrize("module", MODULES)
def test_schema_namespace_matches_config_default(module):
    """LinkMLスキーマの名前空間と設定の既定ベースURIが一致すること。

    ここがずれると、SHACLのシェイプがデータと別の名前空間を対象にするため、
    検証が「対象0件で合格」という空振りになる。最も気づきにくい失敗なので
    テストで固定する。ドメイン確定時は schema/*.yaml と config.py の既定値を
    同時に変更する。
    """
    from jgkg.config import Settings

    default_base = Settings.model_fields["base_uri"].default
    g = _load(GENERATED / f"{module}.owl.ttl")
    classes = [str(s) for s in g.subjects(RDF.type, OWL.Class)]
    own = [c for c in classes if c.startswith("http")]
    assert own, "クラスが宣言されていない"
    assert any(c.startswith(f"{default_base}/def/{module}#") for c in own), (
        f"スキーマの名前空間が設定の既定ベースURI({default_base})と一致しない。"
        f" 実際のクラスIRI例: {own[:3]}"
    )
```

- [ ] **Step 5: テストを実行する**

```bash
uv run pytest tests/test_schema_consistency.py -v
```

期待: 全件 PASS。`test_shacl_target_classes_match_owl_classes` が FAIL する場合は、`gen-owl` に `--no-use-native-uris` が付いているかを確認する。

- [ ] **Step 6: 生成物をコミットする**

```bash
git add schema/core.yaml scripts/generate-schema.sh schema/generated/ tests/test_schema_consistency.py
git commit -m "feat: LinkML coreモジュールと生成パイプラインを追加

6軸の基底クラスとUnresolvedReferenceを定義。生成物はあえてコミットする
(設計書§5.1)。URI整合性テストで OWL と SHACL が同じIRIを語ることを固定した
(設計書§10)。"
```

---

### Task 3: 公理オーバーレイとマージ

**Files:**
- Create: `schema/overlay/core-axioms.ttl`
- Create: `src/jgkg/schema_merge.py`
- Modify: `tests/test_schema_consistency.py`(オーバーレイ整合性テストを追加)

**Interfaces:**
- Consumes: Task 2 の `schema/generated/core.owl.ttl`
- Produces:
  - `jgkg.schema_merge.merge_ontology(generated: list[Path], overlay: list[Path]) -> rdflib.Graph`
  - `jgkg.schema_merge.overlay_terms(overlay: Path) -> set[str]` — オーバーレイが言及する用語のIRI集合

**なぜオーバーレイなのか**: LinkML公式は「LinkMLはスキーマモデリングのフレームワークであり、オントロジーモデリングのフレームワークではない」と明言している。`gen-owl` が出せない公理(軸間の `owl:disjointWith`、外部語彙への `owl:equivalentClass` 等)を加算専用のTTLに置く。上位オントロジーごと分離しないのは、全ドメインクラスの継承を手書きに移す手間を避けるため(設計書§5.5)。

- [ ] **Step 1: オーバーレイを書く**

`schema/overlay/core-axioms.ttl`:

```turtle
# LinkML の gen-owl が出せない公理だけを置く。加算専用。
# 規約(設計書§5.5):
#   - 生成OWLが述べたことを上書き・否定しない
#   - 言及するクラス・プロパティはすべて生成OWLに存在すること(CIで検証)
#   - 肥大化したら LinkML の限界に達した徴候。撤退基準(§5.3)を再評価する
#   - 外部語彙との対応付けは原則スキーマ側(close_mappings/exact_mappings)に置く。
#     スキーマが弱い対応付けを選んでいるものを、ここで owl:equivalentClass に
#     格上げしてはならない(上書きにあたる)

@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix core: <http://localhost:8080/kg/def/core#> .

# 6軸と未解決参照は互いに素である。7クラスの全組み合わせ21ペアを網羅する。
# 上三角の形で書き、重複なく数えられるようにしている(6+5+4+3+2+1 = 21)。
#
# Agent と Place の排他は特に意味がある: 「東京都」という行政区域(Place)と、
# 「東京都」という地方公共団体(Agent、法人番号を持つ)は別のものであり、
# 別のURIで表す。この公理がその区別を強制する。
core:Agent        owl:disjointWith core:Work , core:Place , core:Event , core:MonetaryItem , core:Concept , core:UnresolvedReference .
core:Work         owl:disjointWith core:Place , core:Event , core:MonetaryItem , core:Concept , core:UnresolvedReference .
core:Place        owl:disjointWith core:Event , core:MonetaryItem , core:Concept , core:UnresolvedReference .
core:Event        owl:disjointWith core:MonetaryItem , core:Concept , core:UnresolvedReference .
core:MonetaryItem owl:disjointWith core:Concept , core:UnresolvedReference .
core:Concept      owl:disjointWith core:UnresolvedReference .
```

- [ ] **Step 2: 失敗するテストを追加する**

`tests/test_schema_consistency.py` の末尾に追加:

```python
OVERLAY = Path("schema/overlay")


def test_overlay_terms_all_exist_in_generated_owl():
    """設計書§10: オーバーレイが言及する用語はすべて生成OWLに存在すること。

    存在しない用語への公理は、スキーマへの未反映かタイポである。
    """
    from jgkg.schema_merge import overlay_terms

    owl_g = Graph()
    for p in sorted(GENERATED.glob("*.owl.ttl")):
        owl_g.parse(p, format="turtle")
    declared = {str(s) for s in owl_g.subjects(RDF.type, OWL.Class)}
    declared |= {str(s) for s in owl_g.subjects(RDF.type, OWL.ObjectProperty)}
    declared |= {str(s) for s in owl_g.subjects(RDF.type, OWL.DatatypeProperty)}

    for overlay in sorted(OVERLAY.glob("*.ttl")):
        referenced = overlay_terms(overlay)
        # 自分の名前空間の用語だけを検査する。外部語彙(prov: 等)は対象外
        base = "http://localhost:8080/kg/def/"
        own = {t for t in referenced if t.startswith(base)}
        missing = own - declared
        assert not missing, (
            f"{overlay} が言及する用語が生成OWLに存在しない: {sorted(missing)}"
        )


def test_merged_ontology_contains_both_sources():
    from jgkg.schema_merge import merge_ontology

    merged = merge_ontology(
        generated=sorted(GENERATED.glob("*.owl.ttl")),
        overlay=sorted(OVERLAY.glob("*.ttl")),
    )
    # 生成側由来
    assert (None, RDF.type, OWL.Class) in merged
    # オーバーレイ由来
    assert any(merged.triples((None, OWL.disjointWith, None))), "オーバーレイの公理が入っていない"
```

- [ ] **Step 3: テストが失敗することを確認する**

```bash
uv run pytest tests/test_schema_consistency.py -k overlay -v
```

期待: `ModuleNotFoundError: No module named 'jgkg.schema_merge'` で FAIL。

- [ ] **Step 4: `schema_merge.py` を実装する**

```python
"""生成OWLと手書きオーバーレイのマージ。公開オントロジーはこの結果である。"""
from pathlib import Path

from rdflib import BNode, Graph, Literal, URIRef


def merge_ontology(generated: list[Path], overlay: list[Path]) -> Graph:
    """生成OWLにオーバーレイを加算して1つのグラフにする。

    オーバーレイは加算専用なので、単純な和集合で足りる。
    """
    g = Graph()
    for path in generated:
        g.parse(path, format="turtle")
    for path in overlay:
        g.parse(path, format="turtle")
    return g


def overlay_terms(overlay: Path) -> set[str]:
    """オーバーレイが言及するIRIをすべて集める(主語・述語・目的語)。"""
    g = Graph()
    g.parse(overlay, format="turtle")
    terms: set[str] = set()
    for s, p, o in g:
        for node in (s, p, o):
            if isinstance(node, URIRef):
                terms.add(str(node))
    return terms
```

- [ ] **Step 5: テストが通ることを確認する**

```bash
uv run pytest tests/test_schema_consistency.py -v
```

期待: 全件 PASS。

- [ ] **Step 6: コミットする**

```bash
git add schema/overlay/core-axioms.ttl src/jgkg/schema_merge.py tests/test_schema_consistency.py
git commit -m "feat: 公理オーバーレイとマージを追加

LinkMLで書けない公理(軸間のdisjointWith、PROV-Oへの同値)を加算専用の
手書きTTLに置く(設計書§5.5)。オーバーレイが言及する用語がすべて生成OWLに
存在することをCIで検証する。"
```

---

### Task 4: データレイクとソースレジストリ

**Files:**
- Create: `src/jgkg/sources.py`
- Create: `src/jgkg/lake.py`
- Test: `tests/test_lake.py`

**Interfaces:**
- Consumes: Task 1 の `jgkg.config.get_settings`
- Produces:
  - `jgkg.sources.Source` — dataclass。フィールド `id: str`, `name: str`, `url: str`, `license: str`, `license_url: str`, `frequency: str`, `access: str`
  - `jgkg.sources.SOURCES: dict[str, Source]` — ソースレジストリ
  - `jgkg.sources.get_source(source_id: str) -> Source`
  - `jgkg.lake.Snapshot` — dataclass。`source_id: str`, `fetched_on: datetime.date`, `path: Path`, `sha256: str`, `byte_size: int`
  - `jgkg.lake.save(source_id: str, fetched_on: datetime.date, filename: str, content: bytes) -> Snapshot`
  - `jgkg.lake.load(source_id: str, fetched_on: datetime.date, filename: str) -> bytes`
  - `jgkg.lake.latest(source_id: str) -> datetime.date | None`
  - `jgkg.lake.list_snapshots(source_id: str) -> list[Snapshot]`

**設計上の注意**: ライセンスをソースごとに機械可読で持つのは設計書§11.2の要件。Phase 1で使うソースはすべて商用・再配布可だが、この仕組み自体をPhase 0で作る(Phase 2以降に制約付きソースが入るため、後付けは全面改修になる)。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_lake.py`:

```python
import datetime
import hashlib

import pytest

from jgkg import lake, sources


@pytest.fixture(autouse=True)
def tmp_lake(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_registry_has_houjin_bangou_with_license():
    src = sources.get_source("houjin-bangou")
    assert src.name
    assert src.url.startswith("https://")
    assert src.license, "ライセンスが未記録のソースを登録してはならない(設計書§11.2)"
    assert src.frequency == "monthly"


def test_get_unknown_source_raises():
    with pytest.raises(KeyError):
        sources.get_source("no-such-source")


def test_save_then_load_roundtrip():
    content = b"col1,col2\n1,2\n"
    day = datetime.date(2026, 8, 1)
    snap = lake.save("houjin-bangou", day, "sample.csv", content)

    assert snap.sha256 == hashlib.sha256(content).hexdigest()
    assert snap.byte_size == len(content)
    assert snap.path.exists()
    assert lake.load("houjin-bangou", day, "sample.csv") == content


def test_snapshots_are_immutable():
    day = datetime.date(2026, 8, 1)
    lake.save("houjin-bangou", day, "sample.csv", b"first")
    with pytest.raises(FileExistsError):
        lake.save("houjin-bangou", day, "sample.csv", b"second")


def test_latest_returns_newest_date():
    lake.save("houjin-bangou", datetime.date(2026, 7, 1), "a.csv", b"x")
    lake.save("houjin-bangou", datetime.date(2026, 8, 1), "a.csv", b"y")
    assert lake.latest("houjin-bangou") == datetime.date(2026, 8, 1)


def test_latest_is_none_when_empty():
    assert lake.latest("houjin-bangou") is None
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
uv run pytest tests/test_lake.py -v
```

期待: `ModuleNotFoundError: No module named 'jgkg.sources'` で FAIL。

- [ ] **Step 3: `sources.py` を実装する**

```python
"""ソースレジストリ。ライセンスと更新頻度を機械可読で持つ(設計書§11.2)。

ライセンスが未記録のソースを登録してはならない。アプリはこのメタデータを
使って出典と規約を自動表示する。
"""
from dataclasses import dataclass

GOV_STANDARD_TERMS = "政府標準利用規約(第2.0版)"
GOV_STANDARD_TERMS_URL = "https://www.digital.go.jp/resources/terms_of_use"


@dataclass(frozen=True)
class Source:
    id: str
    name: str
    url: str
    license: str
    license_url: str
    frequency: str  # daily / monthly / annual / ondemand
    access: str     # api / bulk / scrape
    # 期待する文字エンコーディング。同じデータが複数のエンコーディングで配布される
    # ことがあるため、どれを前提にするかを機械可読に記録する(誤ると全行が静かに壊れる)
    encoding: str = "utf-8"
    note: str = ""


SOURCES: dict[str, Source] = {
    "houjin-bangou": Source(
        id="houjin-bangou",
        name="国税庁 法人番号公表サイト 全件データ",
        url="https://www.houjin-bangou.nta.go.jp/download/zenken/",
        license=GOV_STANDARD_TERMS,
        license_url=GOV_STANDARD_TERMS_URL,
        frequency="monthly",
        access="bulk",
        encoding="utf-8",
        note="全件データは月次(前月末時点)。差分は日次。商用・再配布可。"
             "Shift_JIS版とUnicode版の両方が配布されているため、Unicode(UTF-8)版を取得すること",
    ),
    "ministry-codes": Source(
        id="ministry-codes",
        name="府省コード参照表(GIFコードリストより作成)",
        url="https://github.com/JDA-DM/GIF",
        license="CC BY 4.0",
        license_url="https://creativecommons.org/licenses/by/4.0/",
        frequency="ondemand",
        access="bulk",
        note="小規模で安定した参照表のため data/reference/ にコミットして管理する",
    ),
}


def get_source(source_id: str) -> Source:
    if source_id not in SOURCES:
        raise KeyError(f"未登録のソース: {source_id!r}。sources.py に登録してから使う")
    return SOURCES[source_id]
```

- [ ] **Step 4: `lake.py` を実装する**

```python
"""取得時点のスナップショットを不変で保持する。

コネクタは「取得してここに保存する」だけを行う。パースの失敗と取得の失敗を
分離し、パーサ修正時に再取得を不要にするため(設計書§6.1)。
"""
import datetime
import hashlib
import json
from dataclasses import dataclass, asdict
from pathlib import Path

from jgkg.config import get_settings
from jgkg.sources import get_source


@dataclass(frozen=True)
class Snapshot:
    source_id: str
    fetched_on: datetime.date
    path: Path
    sha256: str
    byte_size: int


def _dir(source_id: str, fetched_on: datetime.date) -> Path:
    root = Path(get_settings().lake_dir)
    return root / source_id / fetched_on.isoformat()


def save(source_id: str, fetched_on: datetime.date, filename: str, content: bytes) -> Snapshot:
    """スナップショットを保存する。

    メタデータファイルの存在を「コミット済み」の印として使う。データ本体だけが
    残った中途半端な状態は未コミットとみなし、再保存を許す。これにより
    「一度の失敗が恒久的な再取得不能を生む」ことを避ける(§11.1の冪等性)。
    """
    get_source(source_id)  # 未登録のソースを弾く
    d = _dir(source_id, fetched_on)
    d.mkdir(parents=True, exist_ok=True)
    target = d / filename
    meta_path = d / f"{filename}.meta.json"

    if meta_path.exists():
        raise FileExistsError(
            f"スナップショットは不変である。既にコミット済み: {target}"
        )

    snap = Snapshot(
        source_id=source_id,
        fetched_on=fetched_on,
        path=target,
        sha256=hashlib.sha256(content).hexdigest(),
        byte_size=len(content),
    )
    meta_json = json.dumps(
        {**asdict(snap), "path": str(snap.path), "fetched_on": fetched_on.isoformat()},
        ensure_ascii=False,
        indent=2,
    )

    # データ本体 → メタデータ の順に、それぞれアトミックに置く。
    # 途中で落ちてもメタデータが無いので未コミットと判定され、再実行できる
    _atomic_write(target, content)
    _atomic_write(meta_path, meta_json.encode("utf-8"))
    return snap


def _atomic_write(path: Path, data: bytes) -> None:
    """同一ディレクトリの一時ファイルに書いてから rename する。

    os.replace は同一ファイルシステム上でアトミックで、Windowsでも既存ファイルを
    置き換えられる。一時ファイル名を隠しファイルにしているのは、list_snapshots の
    glob に拾われないようにするため。
    """
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def load(source_id: str, fetched_on: datetime.date, filename: str) -> bytes:
    return (_dir(source_id, fetched_on) / filename).read_bytes()


def list_snapshots(source_id: str) -> list[Snapshot]:
    root = Path(get_settings().lake_dir) / source_id
    if not root.exists():
        return []
    out: list[Snapshot] = []
    for meta in sorted(root.glob("*/*.meta.json")):
        data = json.loads(meta.read_text(encoding="utf-8"))
        out.append(
            Snapshot(
                source_id=data["source_id"],
                fetched_on=datetime.date.fromisoformat(data["fetched_on"]),
                path=Path(data["path"]),
                sha256=data["sha256"],
                byte_size=data["byte_size"],
            )
        )
    return out


def latest(source_id: str) -> datetime.date | None:
    snaps = list_snapshots(source_id)
    return max((s.fetched_on for s in snaps), default=None)
```

- [ ] **Step 5: テストが通ることを確認する**

```bash
uv run pytest tests/test_lake.py -v
```

期待: 6件すべて PASS。

- [ ] **Step 6: コミットする**

```bash
git add src/jgkg/sources.py src/jgkg/lake.py tests/test_lake.py
git commit -m "feat: データレイクとソースレジストリを追加

スナップショットは不変(上書きを例外にする)。ライセンスと更新頻度を
ソースごとに機械可読で持つ(設計書§11.2)。"
```

---

### Task 5: 法人番号コネクタ

**Files:**
- Create: `src/jgkg/connectors/__init__.py`
- Create: `src/jgkg/connectors/base.py`
- Create: `src/jgkg/connectors/houjin_bangou.py`
- Create: `tests/fixtures/houjin_bangou_sample.csv`
- Test: `tests/test_connector_houjin_bangou.py`

**Interfaces:**
- Consumes: Task 4 の `jgkg.lake.save`、`jgkg.sources.get_source`
- Produces:
  - `jgkg.connectors.base.FetchResult` — dataclass。`snapshot: Snapshot`, `skipped: bool`
  - `jgkg.connectors.base.fetch_to_lake(source_id, fetched_on, filename, fetcher) -> FetchResult` — 既存スナップショットがあればスキップする冪等な取得
  - `jgkg.connectors.houjin_bangou.fetch(url: str, fetched_on: datetime.date, client=None) -> FetchResult`
  - `jgkg.connectors.houjin_bangou.FILENAME: str` = `"zenken.csv"`

**手動の準備が必要な点**: 法人番号の全件データはWebフォーム経由で提供され、URLが固定でない可能性がある。**最初の実行時に実URLを確認し、`.env` の `JGKG_HOUJIN_BANGOU_URL` に設定する。** コネクタはURLを引数で受けるため、この確認作業はコードの変更を伴わない。

- [ ] **Step 1: ゴールデンファイルを作る**

`tests/fixtures/houjin_bangou_sample.csv`(法人番号公表サイトの全件CSVは29列のヘッダなしCSV。ここではテストに必要な先頭列のみを持つ簡略版を使い、列位置は変換側で定数化する):

```csv
1,8000012070001,1,2015-10-05,2015-10-05,101,厚生労働省,,,,100,8916,東京都,千代田区,霞が関1-2-2
2,8000012020001,1,2015-10-05,2015-10-05,101,総務省,,,,100,8926,東京都,千代田区,霞が関2-1-2
3,3010001008683,1,2015-10-05,2015-10-05,301,株式会社サンプル,,,,100,0001,東京都,千代田区,千代田1-1
4,7000012050002,1,2015-10-05,2015-10-05,101,財務省,,,,100,8940,東京都,千代田区,霞が関3-1-1
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_connector_houjin_bangou.py`:

```python
import datetime
from pathlib import Path

import httpx
import pytest

from jgkg import lake
from jgkg.connectors import houjin_bangou


@pytest.fixture(autouse=True)
def tmp_lake(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def sample_bytes():
    return Path("tests/fixtures/houjin_bangou_sample.csv").read_bytes()


def _client(payload: bytes) -> httpx.Client:
    def handler(request):
        return httpx.Response(200, content=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_saves_snapshot_to_lake(sample_bytes):
    day = datetime.date(2026, 8, 1)
    result = houjin_bangou.fetch("https://example.test/zenken.zip", day, client=_client(sample_bytes))

    assert result.skipped is False
    assert result.snapshot.source_id == "houjin-bangou"
    assert lake.load("houjin-bangou", day, houjin_bangou.FILENAME) == sample_bytes


def test_fetch_is_idempotent(sample_bytes):
    """同じ取得日に2度呼んでも例外にならず、2度目はスキップされる。

    冪等性は設計書§11.1の要件。中断からの再開を可能にする。
    """
    day = datetime.date(2026, 8, 1)
    houjin_bangou.fetch("https://example.test/z.zip", day, client=_client(sample_bytes))
    second = houjin_bangou.fetch("https://example.test/z.zip", day, client=_client(sample_bytes))

    assert second.skipped is True
    assert second.snapshot.sha256


def test_fetch_raises_on_http_error():
    def handler(request):
        return httpx.Response(503)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(httpx.HTTPStatusError):
        houjin_bangou.fetch("https://example.test/z.zip", datetime.date(2026, 8, 1), client=client)
```

- [ ] **Step 3: テストが失敗することを確認する**

```bash
uv run pytest tests/test_connector_houjin_bangou.py -v
```

期待: `ModuleNotFoundError: No module named 'jgkg.connectors'` で FAIL。

- [ ] **Step 4: `connectors/base.py` を実装する**

```python
"""コネクタの共通処理。取得してレイクに保存するだけを行う。

パース・変換は一切しない。設計書§6.1の[1]をこの責務に限定するのは、
パースの失敗と取得の失敗を分離するため。
"""
import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from jgkg import lake
from jgkg.config import get_settings
from jgkg.lake import Snapshot


@dataclass(frozen=True)
class FetchResult:
    snapshot: Snapshot
    skipped: bool


def _existing(source_id: str, fetched_on: datetime.date, filename: str) -> Snapshot | None:
    for snap in lake.list_snapshots(source_id):
        if snap.fetched_on == fetched_on and snap.path.name == filename:
            return snap
    return None


def fetch_to_lake(
    source_id: str,
    fetched_on: datetime.date,
    filename: str,
    fetcher: Callable[[], bytes],
) -> FetchResult:
    """冪等な取得。既にスナップショットがあれば取得せずスキップする。"""
    existing = _existing(source_id, fetched_on, filename)
    if existing is not None:
        return FetchResult(snapshot=existing, skipped=True)

    content = fetcher()
    snap = lake.save(source_id, fetched_on, filename, content)
    return FetchResult(snapshot=snap, skipped=False)
```

- [ ] **Step 5: `connectors/houjin_bangou.py` を実装する**

```python
"""国税庁 法人番号公表サイト 全件データのコネクタ。

全件データはWebフォーム経由で提供されるため、URLは引数で受ける。
実URLは .env の JGKG_HOUJIN_BANGOU_URL に設定する。
"""
import datetime

import httpx

from jgkg.connectors.base import FetchResult, fetch_to_lake

SOURCE_ID = "houjin-bangou"
FILENAME = "zenken.csv"
TIMEOUT = httpx.Timeout(60.0, read=600.0)  # 全件データは大きいので読み取りを長く取る


def fetch(url: str, fetched_on: datetime.date, client: httpx.Client | None = None) -> FetchResult:
    owns_client = client is None
    c = client or httpx.Client(timeout=TIMEOUT, follow_redirects=True)

    def _get() -> bytes:
        resp = c.get(url)
        resp.raise_for_status()
        return resp.content

    try:
        return fetch_to_lake(SOURCE_ID, fetched_on, FILENAME, _get)
    finally:
        if owns_client:
            c.close()
```

- [ ] **Step 6: `connectors/__init__.py` を作る**

```python
"""ソース別のコネクタ。取得だけを行い、解釈は transform/ が担う。"""
```

- [ ] **Step 7: テストが通ることを確認する**

```bash
uv run pytest tests/test_connector_houjin_bangou.py -v
```

期待: 3件すべて PASS。

- [ ] **Step 8: コミットする**

```bash
git add src/jgkg/connectors/ tests/fixtures/houjin_bangou_sample.csv tests/test_connector_houjin_bangou.py
git commit -m "feat: 法人番号コネクタを追加

取得のみを行い冪等(既存スナップショットがあればスキップ)。URLは引数で
受けるため、実URLの確認はコード変更を伴わない。"
```

---

### Task 6: 法人番号CSVの変換

**Files:**
- Create: `src/jgkg/transform/__init__.py`
- Create: `src/jgkg/transform/organization.py`
- Test: `tests/test_transform_organization.py`

**Interfaces:**
- Consumes: Task 5 のスナップショット、Task 1 の `jgkg.uris.org_uri`
- Produces:
  - `jgkg.lake.path_of(source_id: str, fetched_on: datetime.date, filename: str) -> Path` — Step 0 で追加
  - `jgkg.transform.organization.Organization` — pydantic BaseModel。フィールド `uri: str`, `houjin_bangou: str`, `name: str`, `prefecture: str`, `city: str`, `street: str`, `kind_code: str`, `is_government_organ: bool`
  - `jgkg.transform.organization.parse_file(path: Path, encoding: str = "utf-8") -> Iterator[Organization]` — **実データ用。ファイル全体をメモリに載せない**
  - `jgkg.transform.organization.parse_text(text: str) -> Iterator[Organization]` — 小さなテスト入力用
  - `jgkg.transform.organization.COL` — 列位置の定数(dict)

> **なぜ `bytes` を受けないのか**: 法人番号の全件データは約500万行(約1GB)。`bytes` で読んで `decode()` すると、日本語を含む str はCPythonでUCS-2(2バイト/文字)になるため約2GB、さらに `StringIO` のコピーでピーク5GB近くに達する。Phase 1の想定構成(2vCPU/8GiB)で破綻し、設計書§11.1の「誰の環境でも同じKGが再構築できる」を満たせない。**小さなfixtureでは差が出ないため、テストが通っても実データで壊れる種類の欠陥である。**

- [ ] **Step 0: `jgkg.lake` にパス取得関数を追加する**

解析側がファイルを直接開けるようにする。レイクのディレクトリ構成の知識を `lake.py` の中に留めるため、パスの組み立ては呼び出し側でなくここに置く。

`src/jgkg/lake.py` に追加(既存の関数は変更しない):

```python
def path_of(source_id: str, fetched_on: datetime.date, filename: str) -> Path:
    """スナップショットのファイルパスを返す。

    大きなファイルを bytes で読まずにストリームで処理したい呼び出し側のために、
    パスだけを渡す。存在確認はしない(呼び出し側が open で判断する)。
    """
    return _dir(source_id, fetched_on) / filename
```

`tests/test_lake.py` の末尾に追記:

```python
def test_path_of_matches_saved_location():
    day = datetime.date(2026, 8, 1)
    snap = lake.save("houjin-bangou", day, "sample.csv", b"x")
    assert lake.path_of("houjin-bangou", day, "sample.csv") == snap.path
```

**設計上の注意**: 法人番号全件CSVはヘッダなしで列位置が仕様で決まっている。列位置を定数として1箇所に集め、仕様変更時の修正点を限定する。**決定的パーサのみでLLMは使わない**(設計書§8.1)。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_transform_organization.py`:

```python
from pathlib import Path

import pytest

from jgkg.transform.organization import Organization, parse_file, parse_text

FIXTURE = Path("tests/fixtures/houjin_bangou_sample.csv")


@pytest.fixture(autouse=True)
def fixed_base(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "http://localhost:8080/kg")
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_parses_all_rows():
    orgs = list(parse_file(FIXTURE))
    assert len(orgs) == 4


def test_maps_fields_and_builds_uri():
    orgs = {o.houjin_bangou: o for o in parse_file(FIXTURE)}
    kourou = orgs["8000012070001"]
    assert kourou.name == "厚生労働省"
    assert kourou.uri == "http://localhost:8080/kg/id/org/8000012070001"
    assert kourou.prefecture == "東京都"
    assert kourou.city == "千代田区"


def test_flags_government_organs():
    orgs = {o.houjin_bangou: o for o in parse_file(FIXTURE)}
    assert orgs["8000012070001"].is_government_organ is True   # 種別 101 = 国の機関
    assert orgs["3010001008683"].is_government_organ is False  # 種別 301 = 株式会社


def test_skips_rows_with_invalid_houjin_bangou():
    bad = "1,NOTANUMBER,1,2015-10-05,2015-10-05,101,壊れた行,,,,100,0001,東京都,千代田区,x\n"
    assert list(parse_text(bad)) == []


def test_skips_blank_lines():
    content = "\n\n1,8000012070001,1,2015-10-05,2015-10-05,101,厚生労働省,,,,1,1,東京都,千代田区,x\n\n"
    assert len(list(parse_text(content))) == 1


def test_parse_file_does_not_read_whole_file_into_memory(tmp_path):
    """ファイル全体をメモリに載せないこと。

    実データ(約1GB)で decode + StringIO を経由するとピーク5GB近くに達し、
    Phase 1の想定構成(2vCPU/8GiB)で破綻する。小さなfixtureでは差が出ないため、
    「1行だけ消費した時点でファイル全体が読まれていない」ことで代替検証する。
    """
    big = tmp_path / "many.csv"
    line = "1,8000012070001,1,2015-10-05,2015-10-05,101,厚生労働省,,,,1,1,東京都,千代田区,x\n"
    big.write_text(line * 5000, encoding="utf-8")

    gen = parse_file(big)
    first = next(gen)          # 1件だけ取り出す
    assert first.houjin_bangou == "8000012070001"
    # ジェネレータを閉じる(残りを読まない)。全件読み込みでは到達しない
    gen.close()
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
uv run pytest tests/test_transform_organization.py -v
```

期待: `ModuleNotFoundError: No module named 'jgkg.transform'` で FAIL。

- [ ] **Step 3: `transform/__init__.py` を作る**

```python
"""スナップショットの解釈。決定的パーサのみを使う(設計書§8.1)。"""
```

- [ ] **Step 4: `transform/organization.py` を実装する**

```python
"""法人番号 全件CSV → Organization。

全件CSVはヘッダなしで列位置が仕様で決まっている。列位置はここに集約し、
仕様変更時の修正点を1箇所に限定する。
"""
import csv
import io
from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel

from jgkg.uris import HOUJIN_BANGOU_RE, org_uri

# 全件CSVの列位置(0起点)。仕様変更時はここだけを直す。
COL = {
    "houjin_bangou": 1,
    "kind_code": 5,
    "name": 6,
    "prefecture": 12,
    "city": 13,
    "street": 14,
}

# 法人種別コード 101 = 国の機関
GOVERNMENT_ORGAN_KIND = "101"


class Organization(BaseModel):
    uri: str
    houjin_bangou: str
    name: str
    kind_code: str
    prefecture: str = ""
    city: str = ""
    street: str = ""
    is_government_organ: bool = False


def _cell(row: list[str], key: str) -> str:
    idx = COL[key]
    return row[idx].strip() if idx < len(row) else ""


def parse_file(path: Path, encoding: str = "utf-8") -> Iterator[Organization]:
    """CSVファイルを1行ずつ Organization にする。

    **ファイル全体をメモリに載せない。** 法人番号の全件データは約500万行(約1GB)で、
    bytes で読んで `decode()` すると、日本語を含む str はCPythonでUCS-2(2バイト/文字)
    になるため約2GB、さらに StringIO のコピーでピーク5GB近くに達する。Phase 1の
    想定構成(2vCPU/8GiB)で破綻し、設計書§11.1の「誰の環境でも同じKGが再構築できる」
    を満たせない。ファイルハンドルを csv.reader に直接渡して1行ずつ流す。

    不正な行は黙って捨てず、単に生成しない。法人番号が13桁でない行は取り込まない。
    ここで例外にしないのは、全件データの末尾に集計行などが混じっても処理を
    止めないため。

    一方、エンコーディングの誤りは行単位のノイズではなく全行に及ぶ系統的な誤りなので、
    `errors="strict"` にして `UnicodeDecodeError` で止める。法人番号の全件データは
    Shift_JIS版とUnicode版の両方が配布されており、置換して進むと500万行の法人名
    すべてが静かに壊れる(設計書の「沈黙させない」原則に反する)。期待する配布版は
    ソースレジストリの `Source.encoding` に記録する。
    """
    with path.open("r", encoding=encoding, errors="strict", newline="") as f:
        yield from _parse_reader(csv.reader(f))


def parse_text(text: str) -> Iterator[Organization]:
    """文字列からパースする。小さなテスト入力用。

    実データには使わない(メモリに全載せするため)。実データは parse_file を使う。
    """
    yield from _parse_reader(csv.reader(io.StringIO(text)))


def _parse_reader(reader: Iterator[list[str]]) -> Iterator[Organization]:
    for row in reader:
        if not row or not any(c.strip() for c in row):
            continue
        bangou = _cell(row, "houjin_bangou")
        if not HOUJIN_BANGOU_RE.match(bangou):
            continue
        kind = _cell(row, "kind_code")
        yield Organization(
            uri=org_uri(bangou),
            houjin_bangou=bangou,
            name=_cell(row, "name"),
            kind_code=kind,
            prefecture=_cell(row, "prefecture"),
            city=_cell(row, "city"),
            street=_cell(row, "street"),
            is_government_organ=(kind == GOVERNMENT_ORGAN_KIND),
        )
```

- [ ] **Step 5: テストが通ることを確認する**

```bash
uv run pytest tests/test_transform_organization.py -v
```

期待: 5件すべて PASS。

- [ ] **Step 6: コミットする**

```bash
git add src/jgkg/transform/ tests/test_transform_organization.py
git commit -m "feat: 法人番号CSVの変換を追加

列位置を定数に集約し仕様変更時の修正点を限定。国の機関(種別101)に
フラグを立て、府省マスター構築の入力にする。"
```

---

### Task 7: 府省マスターの構築

**Files:**
- Create: `data/reference/ministry-codes.csv`
- Create: `src/jgkg/transform/ministry.py`
- Test: `tests/test_transform_ministry.py`

**Interfaces:**
- Consumes: Task 6 の `Organization`、Task 3 の `UnresolvedReference` の考え方
- Produces:
  - `jgkg.transform.ministry.Ministry` — pydantic BaseModel。`uri: str`, `houjin_bangou: str`, `ministry_code: str`, `name: str`
  - `jgkg.transform.ministry.UnmatchedMinistry` — pydantic BaseModel。`ministry_code: str`, `name: str`, `reason: str`
  - `jgkg.transform.ministry.load_reference(path: Path) -> list[tuple[str, str]]` — (府省コード, 名称)
  - `jgkg.transform.ministry.build(orgs: Iterable[Organization], reference: list[tuple[str, str]]) -> tuple[list[Ministry], list[UnmatchedMinistry]]`

**設計上の注意**: 府省の正準IDは法人番号(設計書§4.1で `/id/org/` に統一)。府省コードは識別子プロパティとして持ち、コードからの逆引きを可能にする。**突合できなかった府省は捨てずに `UnmatchedMinistry` として返し、件数を報告する**(設計書§8.2)。

- [ ] **Step 1: 参照表を作る**

`data/reference/ministry-codes.csv`。**出典を1行目のコメントに記録する**(設計書§11.2)。Phase 1の縦スライスに必要な府省から始め、必要に応じて追加する:

```csv
# source: デジタル庁 GIF コードリスト (https://github.com/JDA-DM/GIF) / CC BY 4.0
# 小規模で安定した参照表のためリポジトリにコミットして管理する
ministry_code,name
013,総務省
017,財務省
020,厚生労働省
```

- [ ] **Step 2: 失敗するテストを書く**

`tests/test_transform_ministry.py`:

```python
from pathlib import Path

import pytest

from jgkg.transform.ministry import Ministry, build, load_reference
from jgkg.transform.organization import Organization


@pytest.fixture(autouse=True)
def fixed_base(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "http://localhost:8080/kg")
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _org(bangou: str, name: str, kind: str = "101") -> Organization:
    return Organization(
        uri=f"http://localhost:8080/kg/id/org/{bangou}",
        houjin_bangou=bangou,
        name=name,
        kind_code=kind,
        is_government_organ=(kind == "101"),
    )


def test_load_reference_skips_comments():
    ref = load_reference(Path("data/reference/ministry-codes.csv"))
    assert ("020", "厚生労働省") in ref
    assert all(not code.startswith("#") for code, _ in ref)


def test_build_matches_by_name():
    orgs = [_org("8000012070001", "厚生労働省"), _org("8000012020001", "総務省")]
    ministries, unmatched = build(orgs, [("020", "厚生労働省"), ("013", "総務省")])

    by_code = {m.ministry_code: m for m in ministries}
    assert by_code["020"].houjin_bangou == "8000012070001"
    assert by_code["020"].uri == "http://localhost:8080/kg/id/org/8000012070001"
    assert unmatched == []


def test_build_reports_unmatched_instead_of_dropping():
    """突合できなかった府省を沈黙させない(設計書§8.2)。"""
    orgs = [_org("8000012070001", "厚生労働省")]
    ministries, unmatched = build(orgs, [("020", "厚生労働省"), ("999", "存在しない省")])

    assert len(ministries) == 1
    assert len(unmatched) == 1
    assert unmatched[0].ministry_code == "999"
    assert unmatched[0].reason == "NO_CANDIDATE"


def test_build_ignores_non_government_organizations():
    orgs = [_org("3010001008683", "厚生労働省", kind="301")]  # 同名だが株式会社
    ministries, unmatched = build(orgs, [("020", "厚生労働省")])

    assert ministries == []
    assert len(unmatched) == 1


def test_build_reports_ambiguous_matches():
    orgs = [_org("8000012070001", "厚生労働省"), _org("8000012070002", "厚生労働省")]
    ministries, unmatched = build(orgs, [("020", "厚生労働省")])

    assert ministries == []
    assert unmatched[0].reason == "AMBIGUOUS"
```

- [ ] **Step 3: テストが失敗することを確認する**

```bash
uv run pytest tests/test_transform_ministry.py -v
```

期待: `ModuleNotFoundError: No module named 'jgkg.transform.ministry'` で FAIL。

- [ ] **Step 4: `transform/ministry.py` を実装する**

```python
"""府省マスターの構築。

正準IDは法人番号(設計書§4.1)。府省コードは識別子プロパティとして持つ。
突合できなかったものは捨てずに返し、件数を報告できるようにする(§8.2)。
"""
import csv
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel

from jgkg.transform.organization import Organization


class Ministry(BaseModel):
    uri: str
    houjin_bangou: str
    ministry_code: str
    name: str


class UnmatchedMinistry(BaseModel):
    ministry_code: str
    name: str
    reason: str  # NO_CANDIDATE / AMBIGUOUS


def load_reference(path: Path) -> list[tuple[str, str]]:
    """府省コード参照表を読む。# で始まる行はコメントとして飛ばす。"""
    out: list[tuple[str, str]] = []
    with path.open(encoding="utf-8") as f:
        rows = [line for line in f if not line.lstrip().startswith("#")]
    reader = csv.DictReader(rows)
    for row in reader:
        code = (row.get("ministry_code") or "").strip()
        name = (row.get("name") or "").strip()
        if code and name:
            out.append((code, name))
    return out


def build(
    orgs: Iterable[Organization],
    reference: list[tuple[str, str]],
) -> tuple[list[Ministry], list[UnmatchedMinistry]]:
    """国の機関のみを対象に、名称で府省コードと突合する。

    同名が複数ある場合は AMBIGUOUS として未解決にする。誤って1つを選ぶより、
    未解決として可視化する方が公共財として正しい。
    """
    candidates: dict[str, list[Organization]] = {}
    for org in orgs:
        if not org.is_government_organ:
            continue
        candidates.setdefault(org.name, []).append(org)

    ministries: list[Ministry] = []
    unmatched: list[UnmatchedMinistry] = []

    for code, name in reference:
        matches = candidates.get(name, [])
        if len(matches) == 1:
            org = matches[0]
            ministries.append(
                Ministry(
                    uri=org.uri,
                    houjin_bangou=org.houjin_bangou,
                    ministry_code=code,
                    name=name,
                )
            )
        else:
            unmatched.append(
                UnmatchedMinistry(
                    ministry_code=code,
                    name=name,
                    reason="AMBIGUOUS" if len(matches) > 1 else "NO_CANDIDATE",
                )
            )

    return ministries, unmatched
```

- [ ] **Step 5: テストが通ることを確認する**

```bash
uv run pytest tests/test_transform_ministry.py -v
```

期待: 5件すべて PASS。

- [ ] **Step 6: コミットする**

```bash
git add data/reference/ministry-codes.csv src/jgkg/transform/ministry.py tests/test_transform_ministry.py
git commit -m "feat: 府省マスターの構築を追加

正準IDは法人番号、府省コードは識別子プロパティ(設計書§4.1)。突合できな
かった府省は UnmatchedMinistry として返し沈黙させない(§8.2)。同名が複数
ある場合は誤って選ばずAMBIGUOUSにする。"
```

---

### Task 8: RDF出力と出典グラフ

**Files:**
- Create: `src/jgkg/rdf/__init__.py`
- Create: `src/jgkg/rdf/provenance.py`
- Create: `src/jgkg/rdf/emit.py`
- Test: `tests/test_rdf_emit.py`

**Interfaces:**
- Consumes: Task 6 の `Organization`、Task 7 の `Ministry`/`UnmatchedMinistry`、Task 1 の `jgkg.uris`
- Produces:
  - `jgkg.rdf.provenance.provenance_graph(source_id, fetched_on, sha256, parser_version) -> rdflib.Graph` — グラフ自体についての記述
  - `jgkg.rdf.emit.NS` — dict。`core`, `org` の名前空間 URIRef
  - `jgkg.rdf.emit.emit_organizations(orgs, source_id, fetched_on) -> rdflib.Dataset`
  - `jgkg.rdf.emit.emit_ministries(ministries, unmatched, source_id, fetched_on) -> rdflib.Dataset`
  - `jgkg.rdf.emit.write_nquads(ds: rdflib.Dataset, path: Path) -> None`

**設計上の注意**: 出典は**名前付きグラフ単位**でPROV-Oで持つ(設計書§8.4)。RDF-starは使わない。グラフ自体についての記述は、そのグラフの中ではなくデフォルトグラフ側に書く(グラフを置換したときにメタデータも一緒に入れ替わるようにするため、同じグラフURIのメタデータをメタデータ用グラフにまとめる)。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_rdf_emit.py`:

```python
import datetime

import pytest
from rdflib import RDF, Dataset, Literal, URIRef
from rdflib.namespace import PROV, SKOS

from jgkg.rdf import emit
from jgkg.transform.ministry import Ministry, UnmatchedMinistry
from jgkg.transform.organization import Organization

DAY = datetime.date(2026, 8, 1)


@pytest.fixture(autouse=True)
def fixed_base(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "http://localhost:8080/kg")
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _org(bangou="8000012070001", name="厚生労働省", kind="101"):
    return Organization(
        uri=f"http://localhost:8080/kg/id/org/{bangou}",
        houjin_bangou=bangou,
        name=name,
        kind_code=kind,
        prefecture="東京都",
        is_government_organ=(kind == "101"),
    )


def test_organizations_land_in_the_named_graph_for_the_source():
    ds = emit.emit_organizations([_org()], "houjin-bangou", DAY)
    expected_graph = URIRef("http://localhost:8080/kg/graph/houjin-bangou/2026-08-01")

    contexts = {g.identifier for g in ds.contexts() if len(g) > 0}
    assert expected_graph in contexts


def test_organization_has_label_and_identifier():
    ds = emit.emit_organizations([_org()], "houjin-bangou", DAY)
    subject = URIRef("http://localhost:8080/kg/id/org/8000012070001")

    labels = [str(o) for o in ds.objects(subject, SKOS.prefLabel)]
    assert "厚生労働省" in labels


def test_no_fact_without_provenance():
    """設計書§2 原則7: 出典を持たない事実をKGに入れない。

    データを含むすべての名前付きグラフに、そのグラフについてのPROV-O記述が
    存在すること。
    """
    ds = emit.emit_organizations([_org()], "houjin-bangou", DAY)

    data_graphs = {
        g.identifier
        for g in ds.contexts()
        if len(g) > 0 and "/graph/" in str(g.identifier) and "provenance" not in str(g.identifier)
    }
    assert data_graphs, "データを含むグラフが無い"

    for gid in data_graphs:
        described = list(ds.objects(gid, PROV.wasDerivedFrom))
        assert described, f"出典の記述が無いグラフがある: {gid}"


def test_provenance_records_fetch_date_and_checksum():
    ds = emit.emit_organizations([_org()], "houjin-bangou", DAY, sha256="abc123")
    gid = URIRef("http://localhost:8080/kg/graph/houjin-bangou/2026-08-01")

    times = [str(o) for o in ds.objects(gid, PROV.generatedAtTime)]
    assert any("2026-08-01" in t for t in times)


def test_unmatched_ministries_are_emitted_not_dropped():
    ds = emit.emit_ministries(
        [Ministry(uri="http://localhost:8080/kg/id/org/8000012070001",
                  houjin_bangou="8000012070001", ministry_code="020", name="厚生労働省")],
        [UnmatchedMinistry(ministry_code="999", name="存在しない省", reason="NO_CANDIDATE")],
        "ministry-codes",
        DAY,
    )
    core = emit.NS["core"]
    unresolved = [s for s in ds.subjects(RDF.type, core["UnresolvedReference"])]
    assert unresolved, "未解決の府省がKGに出力されていない(設計書§8.2)"


def test_write_nquads_roundtrips(tmp_path):
    ds = emit.emit_organizations([_org()], "houjin-bangou", DAY)
    out = tmp_path / "out.nq"
    emit.write_nquads(ds, out)

    reloaded = Dataset()
    reloaded.parse(out, format="nquads")
    assert len(list(reloaded.quads())) == len(list(ds.quads()))
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
uv run pytest tests/test_rdf_emit.py -v
```

期待: `ModuleNotFoundError: No module named 'jgkg.rdf'` で FAIL。

- [ ] **Step 3: `rdf/__init__.py` を作る**

```python
"""Pydanticモデルから名前付きグラフを組み立てる層。"""
```

- [ ] **Step 4: `rdf/provenance.py` を実装する**

```python
"""グラフ自体についてのPROV-O記述。

出典は名前付きグラフ単位で持つ(設計書§8.4)。RDF-starは使わない。
出典の単位が「ソース×取得日」であり、トリプル単位の注釈はPhase 1では過剰。
"""
import datetime

from rdflib import Graph, Literal, URIRef, XSD
from rdflib.namespace import DCTERMS, PROV

from jgkg.sources import get_source

PARSER_VERSION = "0.1.0"


def provenance_graph(
    graph_uri: str,
    source_id: str,
    fetched_on: datetime.date,
    sha256: str | None = None,
    parser_version: str = PARSER_VERSION,
) -> Graph:
    """指定した名前付きグラフについての記述を返す。

    「どのソースの、いつ取得したファイルから、どのパーサバージョンで生成したか」
    を記録する。
    """
    src = get_source(source_id)
    g = Graph()
    subject = URIRef(graph_uri)

    g.add((subject, PROV.wasDerivedFrom, URIRef(src.url)))
    g.add((subject, PROV.generatedAtTime, Literal(fetched_on, datatype=XSD.date)))
    g.add((subject, DCTERMS.source, Literal(src.name)))
    g.add((subject, DCTERMS.license, URIRef(src.license_url)))
    g.add((subject, DCTERMS.rights, Literal(src.license)))
    g.add((subject, PROV.wasGeneratedBy, Literal(f"jgkg/{parser_version}")))
    if sha256:
        g.add((subject, PROV.value, Literal(f"sha256:{sha256}")))
    return g
```

- [ ] **Step 5: `rdf/emit.py` を実装する**

```python
"""Pydanticモデル → 名前付きグラフ。

データは「ソース×取得日」の名前付きグラフに入れる。そのグラフについての
PROV-O記述は、置換の単位を揃えるため専用のメタデータグラフに入れる。
"""
import datetime
from collections.abc import Iterable
from pathlib import Path

from rdflib import Dataset, Graph, Literal, Namespace, RDF, URIRef
from rdflib.namespace import SKOS

from jgkg.config import get_settings
from jgkg.rdf.provenance import provenance_graph
from jgkg.transform.ministry import Ministry, UnmatchedMinistry
from jgkg.transform.organization import Organization
from jgkg.uris import graph_uri


def _ns() -> dict[str, Namespace]:
    base = get_settings().base_uri
    return {
        "core": Namespace(f"{base}/def/core#"),
        "org": Namespace(f"{base}/def/org#"),
    }


class _NSProxy:
    """テストから emit.NS["core"] で参照できるようにする薄いラッパ。"""

    def __getitem__(self, key: str) -> Namespace:
        return _ns()[key]


NS = _NSProxy()


def _metadata_graph_uri() -> str:
    return f"{get_settings().base_uri}/graph/provenance"


def _new_dataset(source_id: str, fetched_on: datetime.date, sha256: str | None) -> tuple[Dataset, Graph]:
    ds = Dataset()
    gid = graph_uri(source_id, fetched_on)
    data = ds.graph(URIRef(gid))

    meta = ds.graph(URIRef(_metadata_graph_uri()))
    for triple in provenance_graph(gid, source_id, fetched_on, sha256=sha256):
        meta.add(triple)
    return ds, data


def emit_organizations(
    orgs: Iterable[Organization],
    source_id: str,
    fetched_on: datetime.date,
    sha256: str | None = None,
) -> Dataset:
    ns = _ns()
    ds, data = _new_dataset(source_id, fetched_on, sha256)

    for org in orgs:
        s = URIRef(org.uri)
        # 型は「最も具体的なもの1つ」だけを出す。上位型(core:Agent 等)を材質化
        # しないのは、LinkMLの生成SHACLが閉じたシェイプであり、上位クラスが
        # 宣言していないプロパティが違反になるため。上位型はOWLの階層から導ける
        most_specific = "GovernmentOrgan" if org.is_government_organ else "Organization"
        data.add((s, RDF.type, ns["org"][most_specific]))
        data.add((s, SKOS.prefLabel, Literal(org.name, lang="ja")))
        data.add((s, ns["org"]["houjinBangou"], Literal(org.houjin_bangou)))
        data.add((s, ns["org"]["organizationKindCode"], Literal(org.kind_code)))
        if org.prefecture:
            data.add((s, ns["org"]["prefectureName"], Literal(org.prefecture, lang="ja")))
        if org.city:
            data.add((s, ns["org"]["cityName"], Literal(org.city, lang="ja")))
    return ds


def emit_ministries(
    ministries: Iterable[Ministry],
    unmatched: Iterable[UnmatchedMinistry],
    source_id: str,
    fetched_on: datetime.date,
    sha256: str | None = None,
) -> Dataset:
    ns = _ns()
    ds, data = _new_dataset(source_id, fetched_on, sha256)
    base = get_settings().base_uri

    for m in ministries:
        s = URIRef(m.uri)
        data.add((s, RDF.type, ns["org"]["Ministry"]))
        data.add((s, ns["org"]["ministryCode"], Literal(m.ministry_code)))

    for u in unmatched:
        s = URIRef(f"{base}/id/unresolved/ministry/{u.ministry_code}")
        data.add((s, RDF.type, ns["core"]["UnresolvedReference"]))
        data.add((s, ns["core"]["unresolved_text"], Literal(u.name, lang="ja")))
        data.add((s, ns["core"]["unresolved_reason"], Literal(u.reason)))
        # ドメイン固有の org:ministryCode ではなく core の汎用キーに入れる。
        # UnresolvedReference は org: のプロパティを宣言しておらず、閉じたシェイプに
        # 違反するため。CQ P0-5 が core:UnresolvedReference を直接問えるよう
        # サブクラス化はしない(推論なしのFusekiでは上位型が引けない)
        data.add((s, ns["core"]["unresolved_key"], Literal(u.ministry_code)))
    return ds


def write_nquads(ds: Dataset, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ds.serialize(destination=str(path), format="nquads", encoding="utf-8")
```

- [ ] **Step 6: `schema/org.yaml` を作り、使ったクラスとプロパティを定義する**

`emit.py` が参照した `org` モジュールの用語を、LinkMLで定義する。**生成OWLに存在しない用語をデータで使ってはならない**(Task 9のSHACL検証で弾かれる)。

```yaml
id: http://localhost:8080/kg/def/org
name: jgkg-org
title: 日本政府ナレッジグラフ 組織モジュール
description: 組織(府省・法人)を表すクラスとプロパティ。正準IDは法人番号。
license: https://creativecommons.org/licenses/by/4.0/

prefixes:
  jgkgorg: http://localhost:8080/kg/def/org#
  jgkgcore: http://localhost:8080/kg/def/core#
  linkml: https://w3id.org/linkml/
  skos: http://www.w3.org/2004/02/skos/core#
  schema: http://schema.org/
default_prefix: jgkgorg
default_range: string
imports:
  - linkml:types
  - core

slots:
  houjinBangou:
    description: >-
      国税庁が付与する13桁の法人番号。組織の正準ID。
      required にしないのは、出典管理のためグラフをソース別に分けており、
      1つのエンティティの記述が複数グラフに分かれるため。SHACL検証はグラフ単位
      (グラフが置換の単位)なので、グラフを跨いだ必須制約は原理的に検証できない。
      「全Organizationが法人番号を持つ」ことはCQのSPARQLテストで担保する
    pattern: "^\\d{13}$"
  organizationKindCode:
    description: 法人番号公表サイトの法人種別コード
  ministryCode:
    description: GIFコードリストの府省コード
  prefectureName:
    description: 所在地の都道府県名
    range: LangString
  cityName:
    description: 所在地の市区町村名
    range: LangString

classes:
  Organization:
    is_a: Agent
    description: 法人番号を持つ組織
    slots: [houjinBangou, organizationKindCode, prefectureName, cityName]
    close_mappings: [schema:Organization]

  GovernmentOrgan:
    is_a: Organization
    description: 法人種別が国の機関である組織

  Ministry:
    is_a: GovernmentOrgan
    description: 府省。府省コードで識別できる国の機関
    slots: [ministryCode]
```

- [ ] **Step 7: スキーマを再生成する**

```bash
./scripts/generate-schema.sh
```

期待: `schema/generated/org.owl.ttl`、`org.shacl.ttl`、`org_models.py` が追加される。

- [ ] **Step 8: `test_schema_consistency.py` の `MODULES` に `org` を加える**

```python
MODULES = ["core", "org"]
```

- [ ] **Step 9: すべてのテストが通ることを確認する**

```bash
uv run pytest tests/ -v
```

期待: 全件 PASS。URI整合性テストが `org` モジュールにも適用される。

- [ ] **Step 10: コミットする**

```bash
git add src/jgkg/rdf/ schema/org.yaml schema/generated/ tests/test_rdf_emit.py tests/test_schema_consistency.py
git commit -m "feat: RDF出力と出典グラフを追加

データは「ソース×取得日」の名前付きグラフに入れ、出典はPROV-Oで
グラフ自体に付ける(設計書§8.4)。出典を持たないグラフが無いことを
テストで固定した。未解決の府省もKGに出力する(§8.2)。"
```

---

### Task 9: SHACL検証ゲート

**Files:**
- Create: `schema/all.yaml`
- Modify: `scripts/generate-schema.sh`(モジュールのループに `all` を追加)
- Create: `src/jgkg/validate.py`
- Test: `tests/test_validate.py`

**Interfaces:**
- Consumes: Task 8 の `Dataset`、`schema/generated/all.shacl.ttl`(Step 0 で生成)
- Produces:
  - `jgkg.validate.ValidationResult` — dataclass。`graph_uri: str`, `conforms: bool`, `report_text: str`
  - `jgkg.validate.SHAPES_FILENAME` = `"all.shacl.ttl"`
  - `jgkg.validate.validate_dataset(ds: Dataset, shapes_dir: Path) -> list[ValidationResult]`
  - `jgkg.validate.quarantine(ds: Dataset, results: list[ValidationResult], out_dir: Path) -> list[Path]` — 不合格グラフを隔離して書き出す
  - `jgkg.validate.passing_dataset(ds: Dataset, results: list[ValidationResult]) -> Dataset`

**設計上の注意**: **不合格のグラフはストアにロードしない**(設計書§8.3)。「一部が壊れていても入れてしまう」ことを許すと公共財としての信頼性が最初に崩れるため、厳格側に倒す。不合格分は隔離ディレクトリに出力し、違反内容を人が読める形で報告する。

- [ ] **Step 0: 検証用の統合スキーマを作る**

> **なぜ必要か**: `org.yaml` が `core` を import するため、`org.shacl.ttl` にも core のクラスのNodeShapeが生成される(実測: `jgkgcore` への参照36件、`jgkgcore:Agent` が core/org 両ファイルに各3回)。モジュール別のSHACLをマージすると**同一クラスに閉じたシェイプが2つ適用され、許可プロパティ集合の積になって偽の違反を起こす**。全モジュールを束ねたスキーマから1つのSHACLを生成し、それだけを読む。
>
> 「`org` が `core` を import しているから `org.shacl.ttl` だけ読めばよい」という案は採らない。将来 `law` / `budget` が兄弟モジュールとして増えたとき、どれ1つを読んでも他がカバーされず壊れる。

`schema/all.yaml`:

```yaml
id: http://localhost:8080/kg/def/all
name: jgkg-all
title: 日本政府ナレッジグラフ 全モジュール統合(検証用)
description: >-
  SHACL検証のために全モジュールを1つに束ねるだけのスキーマ。ここから生成した
  all.shacl.ttl を検証の唯一の入力にする。モジュール別に生成すると、import された
  上位モジュールのシェイプが各ファイルに重複して現れ、閉じたシェイプが同一クラスに
  複数適用されて偽の違反になるため。
  新しいドメインモジュールを追加したら、必ずここの imports にも追加する。
license: https://creativecommons.org/licenses/by/4.0/

prefixes:
  jgkgall: http://localhost:8080/kg/def/all#
  linkml: https://w3id.org/linkml/
default_prefix: jgkgall
default_range: string
imports:
  - linkml:types
  - core
  - org
```

`scripts/generate-schema.sh` のループに `all` を追加する(**他の行は変更しない**):

```bash
for module in core org all; do
```

生成して確認する:

```bash
./scripts/generate-schema.sh
```

期待: `schema/generated/all.owl.ttl`、`all.shacl.ttl`、`all_models.py` が追加される。`all.shacl.ttl` に `jgkgcore:Agent` と `jgkgorg:Organization` の両方の `sh:targetClass` が含まれること(`grep 'sh:targetClass' schema/generated/all.shacl.ttl` で確認)。

- [ ] **Step 0b: enum のIRIが1つに定まっていることを検証する**

> **なぜ必要か**: `UnresolvedReasonEnum` が `core.owl.ttl` では `def/core#UnresolvedReasonEnum`、`org.owl.ttl` では `def/org#UnresolvedReasonEnum` という**別IRIでシリアライズされている**ことが判明している(import された enum が import 側の名前空間で再鋳造される)。**コミット必須の公開オントロジーの中で同一概念が2つのIRIを持つ構造的矛盾**であり、識別子の一貫性を中核に置く本設計と衝突する。`all.yaml` を追加すると `def/all#` という3つ目が生まれる恐れもある。

`tests/test_schema_consistency.py` の末尾に追記:

```python
def test_enum_has_a_single_iri_across_generated_owl():
    """同一の enum が複数のIRIで宣言されていないこと。

    import された enum が import 側の名前空間で再鋳造されると、公開する
    オントロジーの中で同一概念が複数のIRIを持つ。識別子の一貫性を中核に置く
    設計と衝突するため、ここで固定する。
    """
    from collections import defaultdict

    by_local_name: dict[str, set[str]] = defaultdict(set)
    for path in sorted(GENERATED.glob("*.owl.ttl")):
        g = _load(path)
        for s in g.subjects(RDF.type, OWL.Class):
            iri = str(s)
            if "#" not in iri:
                continue
            local = iri.rsplit("#", 1)[1]
            if local.endswith("Enum"):
                by_local_name[local].add(iri)

    conflicts = {name: sorted(iris) for name, iris in by_local_name.items() if len(iris) > 1}
    assert not conflicts, f"同一の enum が複数のIRIで宣言されている: {conflicts}"
```

**このテストは現状では落ちる見込みです。** 落ちた場合の対処:

1. `schema/core.yaml` の `UnresolvedReasonEnum` に `enum_uri` を明示できるか**実機で確認する**(`gen-owl --help`、LinkMLのメタモデルを `enum_uri` でgrep、実際に書いて生成してみる)。**公式ドキュメントの記述を根拠にしないこと** — このプロジェクトでは既に、ドキュメントに載っているオプションがリリース版に存在しなかった前例がある
2. `enum_uri` で解決するならそれを使う
3. 解決しない場合は**テストを緩めず報告する。** 私が判定する(選択肢としては、enum をやめて `pattern` 付きの文字列にする、`all.owl.ttl` だけを公開成果物とする、等がある)

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_validate.py`:

```python
import datetime
from pathlib import Path

import pytest
from rdflib import Dataset, Literal, RDF, URIRef

from jgkg import validate
from jgkg.rdf import emit
from jgkg.transform.organization import Organization

DAY = datetime.date(2026, 8, 1)
SHAPES = Path("schema/generated")


@pytest.fixture(autouse=True)
def fixed_base(monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "http://localhost:8080/kg")
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _valid_org():
    return Organization(
        uri="http://localhost:8080/kg/id/org/8000012070001",
        houjin_bangou="8000012070001",
        name="厚生労働省",
        kind_code="101",
        is_government_organ=True,
    )


def test_valid_dataset_conforms():
    ds = emit.emit_organizations([_valid_org()], "houjin-bangou", DAY)
    results = validate.validate_dataset(ds, SHAPES)

    data_results = [r for r in results if "provenance" not in r.graph_uri]
    assert data_results, "検証対象のグラフが無い"
    assert all(r.conforms for r in data_results), [r.report_text for r in data_results if not r.conforms]


def test_malformed_houjin_bangou_fails_validation():
    """法人番号のパターン制約に違反するデータは不合格になること。"""
    ds = emit.emit_organizations([_valid_org()], "houjin-bangou", DAY)
    gid = URIRef("http://localhost:8080/kg/graph/houjin-bangou/2026-08-01")
    g = ds.graph(gid)
    bad = URIRef("http://localhost:8080/kg/id/org/9999999999999")
    ns = emit.NS["org"]
    g.add((bad, RDF.type, ns["Organization"]))
    g.add((bad, ns["houjinBangou"], Literal("BROKEN")))

    results = validate.validate_dataset(ds, SHAPES)
    failing = [r for r in results if not r.conforms]
    assert failing, "不正な法人番号が検証を通ってしまった"


def test_quarantine_writes_failing_graphs(tmp_path):
    ds = Dataset()
    gid = URIRef("http://localhost:8080/kg/graph/broken/2026-08-01")
    g = ds.graph(gid)
    ns = emit.NS["org"]
    subj = URIRef("http://localhost:8080/kg/id/org/1")
    g.add((subj, RDF.type, ns["Organization"]))
    g.add((subj, ns["houjinBangou"], Literal("NOPE")))

    results = validate.validate_dataset(ds, SHAPES)
    written = validate.quarantine(ds, results, tmp_path)

    assert written, "隔離ファイルが書かれていない"
    assert any(p.suffix == ".txt" for p in written), "違反内容の報告が書かれていない"


def test_passing_dataset_excludes_failing_graphs():
    ds = emit.emit_organizations([_valid_org()], "houjin-bangou", DAY)
    broken_gid = URIRef("http://localhost:8080/kg/graph/broken/2026-08-01")
    bg = ds.graph(broken_gid)
    ns = emit.NS["org"]
    subj = URIRef("http://localhost:8080/kg/id/org/2")
    bg.add((subj, RDF.type, ns["Organization"]))
    bg.add((subj, ns["houjinBangou"], Literal("NOPE")))

    results = validate.validate_dataset(ds, SHAPES)
    clean = validate.passing_dataset(ds, results)

    contexts = {str(c.identifier) for c in clean.contexts() if len(c) > 0}
    assert str(broken_gid) not in contexts, "不合格グラフがロード対象に残っている"
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
uv run pytest tests/test_validate.py -v
```

期待: `ModuleNotFoundError: No module named 'jgkg.validate'` で FAIL。

- [ ] **Step 3: `validate.py` を実装する**

```python
"""SHACL検証ゲート。不合格のグラフはストアにロードしない(設計書§8.3)。

「一部が壊れていても入れてしまう」ことを許すと、公共財としての信頼性が
最初に崩れる。ここは厳格側に倒す。
"""
from dataclasses import dataclass
from pathlib import Path

from pyshacl import validate as shacl_validate
from rdflib import Dataset, Graph, URIRef


@dataclass(frozen=True)
class ValidationResult:
    graph_uri: str
    conforms: bool
    report_text: str


SHAPES_FILENAME = "all.shacl.ttl"


def _load_shapes(shapes_dir: Path) -> Graph:
    """検証用のSHACLシェイプを読む。

    **モジュール別のSHACLをマージしてはならない。** `org.yaml` は `core` を import する
    ため `org.shacl.ttl` にも core のクラスのNodeShapeが生成される。両方を読むと同一
    クラスに閉じたシェイプが2つ適用され、許可プロパティ集合の積になって偽の違反を
    起こす。全モジュールを束ねた `all.yaml` から生成した単一ファイルだけを読む。
    """
    path = shapes_dir / SHAPES_FILENAME
    if not path.exists():
        raise FileNotFoundError(
            f"SHACLシェイプが見つからない: {path}。"
            " scripts/generate-schema.sh を実行する"
        )
    shapes = Graph()
    shapes.parse(path, format="turtle")
    return shapes


def validate_dataset(ds: Dataset, shapes_dir: Path) -> list[ValidationResult]:
    """名前付きグラフごとに検証する。グラフが置換の単位なので検証も同じ単位で行う。"""
    shapes = _load_shapes(shapes_dir)
    results: list[ValidationResult] = []

    for ctx in ds.contexts():
        if len(ctx) == 0:
            continue
        target = Graph()
        for triple in ctx:
            target.add(triple)

        conforms, _report_graph, report_text = shacl_validate(
            data_graph=target,
            shacl_graph=shapes,
            advanced=True,
            inplace=False,
        )
        results.append(
            ValidationResult(
                graph_uri=str(ctx.identifier),
                conforms=bool(conforms),
                report_text=report_text,
            )
        )
    return results


def quarantine(ds: Dataset, results: list[ValidationResult], out_dir: Path) -> list[Path]:
    """不合格グラフとその違反内容を隔離ディレクトリに書き出す。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for r in results:
        if r.conforms:
            continue
        stem = r.graph_uri.rstrip("/").replace("://", "_").replace("/", "_")
        nq = out_dir / f"{stem}.nq"
        txt = out_dir / f"{stem}.report.txt"

        g = Graph()
        for triple in ds.graph(URIRef(r.graph_uri)):
            g.add(triple)
        g.serialize(destination=str(nq), format="nt", encoding="utf-8")
        txt.write_text(r.report_text, encoding="utf-8")
        written.extend([nq, txt])
    return written


def passing_dataset(ds: Dataset, results: list[ValidationResult]) -> Dataset:
    """検証を通ったグラフだけを含む新しいDatasetを返す。"""
    failing = {r.graph_uri for r in results if not r.conforms}
    clean = Dataset()
    for ctx in ds.contexts():
        if len(ctx) == 0 or str(ctx.identifier) in failing:
            continue
        target = clean.graph(ctx.identifier)
        for triple in ctx:
            target.add(triple)
    return clean
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
uv run pytest tests/test_validate.py -v
```

期待: 4件すべて PASS。`test_malformed_houjin_bangou_fails_validation` が FAIL する場合は、`schema/org.yaml` の `houjinBangou` に `pattern` が設定され再生成されているかを確認する。

- [ ] **Step 5: コミットする**

```bash
git add schema/all.yaml schema/generated/ scripts/generate-schema.sh src/jgkg/validate.py tests/test_validate.py
git commit -m "feat: SHACL検証ゲートを追加

名前付きグラフ単位で検証し、不合格のグラフはロード対象から外して隔離する
(設計書§8.3)。違反内容を人が読める形で書き出す。"
```

---

### Task 10: 成果物ビルドとmanifest

**Files:**
- Create: `docker/jena-tools.Dockerfile`
- Create: `.env.example`
- Create: `src/jgkg/build.py`
- Test: `tests/test_build.py`

**Interfaces:**
- Consumes: Task 9 の `passing_dataset`、Task 8 の `write_nquads`
- Produces:
  - `jgkg.build.Manifest` — pydantic BaseModel。`release: str`, `created_on: str`, `jena_version: str`, `sha256: str`, `byte_size: int`, `graphs: list[str]`, `sources: dict[str, str]`, `triple_count: int`
  - `jgkg.build.write_manifest(m: Manifest, path: Path) -> None`
  - `jgkg.build.build_manifest(nquads: Path, tarball: Path, jena_version: str, release: str, sources: dict[str, str]) -> Manifest`
  - `jgkg.build.verify_manifest(manifest_path: Path, tarball: Path) -> None` — sha256 が一致しなければ例外

**設計上の注意**: 成果物は content-addressed にし、manifestに **Jenaバージョンを記録する**(設計書§6.3)。TDB2のオンディスク形式はJenaのバージョンに紐づくため、ビルド側と実行側でずれると読めなくなる恐れがある。インデックス構築はCI側で行い、実行環境のCPUを使わない(バーストVMのクレジット枯渇対策)。

- [ ] **Step 1: Jenaツールのコンテナを定義する**

`docker/jena-tools.Dockerfile`:

```dockerfile
# TDB2 のインデックス構築に使う。Jena のバージョンは manifest に記録するため
# ここで固定し、実行側と照合する(設計書§6.3)。
FROM eclipse-temurin:21-jre

# JENA_VERSION は .env で指定する。最初の実行時に Apache Jena の
# 現行安定版を確認して設定する。
ARG JENA_VERSION
ENV JENA_HOME=/opt/apache-jena-${JENA_VERSION}
ENV PATH=${JENA_HOME}/bin:${PATH}
ENV JGKG_JENA_VERSION=${JENA_VERSION}

RUN set -eux; \
    apt-get update && apt-get install -y --no-install-recommends curl ca-certificates; \
    rm -rf /var/lib/apt/lists/*; \
    curl -fsSL -o /tmp/jena.tar.gz \
      "https://archive.apache.org/dist/jena/binaries/apache-jena-${JENA_VERSION}.tar.gz"; \
    tar -xzf /tmp/jena.tar.gz -C /opt; \
    rm /tmp/jena.tar.gz; \
    tdb2.tdbloader --version || true

WORKDIR /work
```

- [ ] **Step 2: `.env.example` を作る**

```dotenv
# ベースURI。ドメイン確定まで開発用のまま使う(設計書§4.2)
# 確定するまでKGを外部に公開しない
JGKG_BASE_URI=http://localhost:8080/kg

# Apache Jena のバージョン。TDB2のオンディスク形式に紐づくため固定する
# 最初の実行時に現行安定版を確認して設定し、manifestに記録される
JENA_VERSION=

# 法人番号 全件データのURL。Webフォーム経由で提供されるため
# 最初の実行時に実URLを確認して設定する
JGKG_HOUJIN_BANGOU_URL=
```

- [ ] **Step 3: 失敗するテストを書く**

`tests/test_build.py`:

```python
import hashlib
import json
from pathlib import Path

import pytest

from jgkg import build


def test_build_manifest_records_checksum_and_jena_version(tmp_path):
    nq = tmp_path / "kg.nq"
    nq.write_text(
        '<http://a/s> <http://a/p> <http://a/o> <http://a/g> .\n', encoding="utf-8"
    )
    tarball = tmp_path / "kg.tar.gz"
    tarball.write_bytes(b"fake tarball content")

    m = build.build_manifest(
        nquads=nq,
        tarball=tarball,
        jena_version="5.0.0",
        release="2026-08-01",
        sources={"houjin-bangou": "2026-08-01"},
    )

    assert m.jena_version == "5.0.0"
    assert m.sha256 == hashlib.sha256(b"fake tarball content").hexdigest()
    assert m.byte_size == len(b"fake tarball content")
    assert m.triple_count == 1
    assert m.graphs == ["http://a/g"]
    assert m.sources == {"houjin-bangou": "2026-08-01"}


def test_build_manifest_rejects_empty_jena_version(tmp_path):
    """Jenaバージョンの記録漏れを許さない(設計書§6.3)。"""
    nq = tmp_path / "kg.nq"
    nq.write_text("", encoding="utf-8")
    tarball = tmp_path / "kg.tar.gz"
    tarball.write_bytes(b"x")

    with pytest.raises(ValueError, match="Jena"):
        build.build_manifest(nquads=nq, tarball=tarball, jena_version="",
                             release="r", sources={})


def test_verify_manifest_detects_corruption(tmp_path):
    tarball = tmp_path / "kg.tar.gz"
    tarball.write_bytes(b"original")
    nq = tmp_path / "kg.nq"
    nq.write_text("", encoding="utf-8")

    m = build.build_manifest(nquads=nq, tarball=tarball, jena_version="5.0.0",
                             release="r", sources={})
    manifest_path = tmp_path / "manifest.json"
    build.write_manifest(m, manifest_path)

    build.verify_manifest(manifest_path, tarball)  # 一致するので例外なし

    tarball.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="sha256"):
        build.verify_manifest(manifest_path, tarball)


def test_write_manifest_is_readable_json(tmp_path):
    nq = tmp_path / "kg.nq"
    nq.write_text("", encoding="utf-8")
    tarball = tmp_path / "kg.tar.gz"
    tarball.write_bytes(b"x")
    m = build.build_manifest(nquads=nq, tarball=tarball, jena_version="5.0.0",
                             release="2026-08-01", sources={})
    path = tmp_path / "manifest.json"
    build.write_manifest(m, path)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["release"] == "2026-08-01"
    assert data["jena_version"] == "5.0.0"
```

- [ ] **Step 4: テストが失敗することを確認する**

```bash
uv run pytest tests/test_build.py -v
```

期待: `ModuleNotFoundError: No module named 'jgkg.build'` で FAIL。

- [ ] **Step 5: `build.py` を実装する**

```python
"""成果物ビルドとmanifest。

インデックスをCIが生成する成果物として扱い、実行環境から切り離す
(設計書§6.3)。content-addressed にして破損を検出し、Jenaバージョンを
記録して実行側と照合できるようにする。
"""
import hashlib
import json
from pathlib import Path

from pydantic import BaseModel


class Manifest(BaseModel):
    release: str
    created_on: str
    jena_version: str
    sha256: str
    byte_size: int
    triple_count: int
    graphs: list[str]
    sources: dict[str, str]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _count_triples(path: Path) -> int:
    """N-Quadsの行数を数える。

    全体をメモリに載せない(実データでは数千万行になる)。

    **グラフURIはここで推測しない。** リテラルには空白も `>` も含まれうるため、
    テキストからグラフ項を判別するには本物の字句解析が必要で、素朴な文字列操作では
    3項トリプル行のオブジェクトIRIをグラフURIと誤認する(実測で確認済み:
    `<http://a/s> <http://a/p> <http://a/o> .` から `http://a/o` が混入した)。
    manifestはリリースの記録なので、偽のグラフURIの混入は記録の汚染になる。
    グラフ一覧は Dataset を持つ呼び出し側から受け取る。
    """
    count = 0
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            count += 1
    return count


def build_manifest(
    nquads: Path,
    tarball: Path,
    jena_version: str,
    release: str,
    sources: dict[str, str],
    graphs: list[str],
) -> Manifest:
    if not jena_version:
        raise ValueError(
            "Jenaバージョンが空である。TDB2のオンディスク形式はJenaのバージョンに"
            "紐づくため、記録を省略できない(設計書§6.3)"
        )
    return Manifest(
        release=release,
        created_on=release,
        jena_version=jena_version,
        sha256=_sha256(tarball),
        byte_size=tarball.stat().st_size,
        triple_count=_count_triples(nquads),
        graphs=sorted(graphs),
        sources=sources,
    )


def write_manifest(m: Manifest, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(m.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def verify_manifest(
    manifest_path: Path,
    tarball: Path,
    expected_jena_version: str | None = None,
) -> None:
    """成果物のsha256と、任意でJenaバージョンが一致することを確かめる。

    実行側が起動時にこれを呼ぶことで、Neptuneのsegment自動修復に相当する
    「壊れたデータを検出する」能力をチェックサムで安価に得る。

    `expected_jena_version` を渡すと、実行側のJenaバージョンが成果物を作った
    ものと一致するかも確かめる。**TDB2のオンディスク形式はJenaのバージョンに
    紐づく**ため、記録しただけで照合しなければ意味がない(照合されない
    バージョン記録は記録の演技にすぎない)。
    """
    m = Manifest(**json.loads(manifest_path.read_text(encoding="utf-8")))
    actual = _sha256(tarball)
    if actual != m.sha256:
        raise ValueError(
            f"成果物のsha256が一致しない。manifest={m.sha256} actual={actual}"
        )
    if expected_jena_version is not None and expected_jena_version != m.jena_version:
        raise ValueError(
            "Jenaバージョンが一致しない。TDB2のオンディスク形式はバージョンに紐づくため"
            f"読めない可能性がある。manifest={m.jena_version} runtime={expected_jena_version}"
        )
```

- [ ] **Step 6: テストが通ることを確認する**

```bash
uv run pytest tests/test_build.py -v
```

期待: 4件すべて PASS。

- [ ] **Step 7: コミットする**

```bash
git add docker/jena-tools.Dockerfile .env.example src/jgkg/build.py tests/test_build.py
git commit -m "feat: 成果物ビルドとmanifestを追加

content-addressed(sha256)にして破損を検出し、Jenaバージョンをmanifestに
記録して実行側と照合できるようにする(設計書§6.3)。N-Quadsは行単位で
走査し全体をメモリに載せない。"
```

---

### Task 11: パイプラインの結線とdocker-compose

**Files:**
- Create: `src/jgkg/pipeline.py`
- Create: `scripts/build.sh`
- Create: `docker-compose.yml`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: Task 5〜10 のすべて
- Produces:
  - `jgkg._io.atomic_write(path: Path, data: bytes) -> None` — Step 0 で切り出す共有ヘルパー
  - `jgkg.pipeline.PipelineReport` — pydantic BaseModel。`release: str`, `organizations: int`, `ministries: int`, `unmatched_ministries: int`, `graphs_validated: int`, `graphs_quarantined: int`, `graphs: list[str]`
  - `jgkg.pipeline.run(fetched_on: datetime.date, out_dir: Path) -> PipelineReport`

- [ ] **Step 0: 積み残しの2件を直す**

前タスクのレビューで挙がった、複数タスクに跨るため統合タスクで扱うことにした2件を先に片付ける。

**(a) `_atomic_write` の重複を共有ヘルパーに切り出す**

`src/jgkg/lake.py` と `src/jgkg/build.py` に**1バイトも違わない同一の `_atomic_write`** がある。片方だけ直すと壊れる典型的な重複なので、共有する。

`src/jgkg/_io.py` を新規作成:

```python
"""ファイル入出力の共通処理。

アトミック書き込みは lake(スナップショット)と build(manifest)の両方で必要で、
同一のロジックが重複していたため切り出した。片方だけ直すと壊れる類の重複だった。
"""
import os
from pathlib import Path


def atomic_write(path: Path, data: bytes) -> None:
    """同一ディレクトリの一時ファイルに書いてから rename する。

    os.replace は同一ファイルシステム上でアトミックで、Windowsでも既存ファイルを
    置き換えられる。一時ファイル名を隠しファイルにしているのは、スナップショットの
    メタデータを glob で探す処理に拾われないようにするため。
    """
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
```

`src/jgkg/lake.py` と `src/jgkg/build.py` から `_atomic_write` の定義を削除し、`from jgkg._io import atomic_write` に置き換える(呼び出し箇所の名前も `atomic_write` に変える)。**それ以外のロジックは変更しない。**

**(b) `passing_dataset` の `default_union` を補う**

`src/jgkg/validate.py` の `passing_dataset` が `Dataset()` を `default_union=True` なしで生成している。現状は `contexts()` 走査のみなので実害はないが、**この欠落はこのプロジェクトで既に2件の実害を出しており**(CQテストのfixture、emitのテスト)、将来このDatasetをSPARQLや `.objects()` で問い合わせた瞬間に3件目が起きる。

```python
    clean = Dataset(default_union=True)
```

に変更する。**それ以外は変更しない。**

変更後、既存テストが通ることを確認する:

```bash
uv run pytest tests/ -v
```

期待: 60件PASS(件数は変わらない)。

**設計上の注意**: 各段の処理件数・失敗件数・解決率をパイプラインの出力として記録する(設計書§11.1 観測性)。**府省の突合率は計測して報告するが、Phase 0 の完了条件にしない**(目標値は最初の実測後に設定し、推測値を先に置かない。設計書§8.2)。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_pipeline.py`:

```python
import datetime
from pathlib import Path

import pytest

from jgkg import lake, pipeline
from jgkg.connectors import houjin_bangou

DAY = datetime.date(2026, 8, 1)


@pytest.fixture(autouse=True)
def tmp_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "http://localhost:8080/kg")
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    monkeypatch.setenv("JGKG_QUARANTINE_DIR", str(tmp_path / "quarantine"))
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def seeded_lake():
    content = Path("tests/fixtures/houjin_bangou_sample.csv").read_bytes()
    lake.save("houjin-bangou", DAY, houjin_bangou.FILENAME, content)


def test_run_produces_nquads_and_report(seeded_lake, tmp_path):
    out = tmp_path / "out"
    report = pipeline.run(DAY, out)

    assert report.organizations == 4       # 入力の全件数
    assert report.government_organs == 3   # KGに入れた件数(株式会社1件を除外)
    assert report.ministries >= 1
    assert (out / "kg.nq").exists()


def test_run_reports_unmatched_ministries(seeded_lake, tmp_path):
    """参照表にあってデータに無い府省を件数として報告する(設計書§8.2)。

    fixtureの参照表3府省はすべてfixture CSVに国の機関として存在するので、
    正常系では突合率100%になる。ここを厳密に固定することで、突合が壊れた
    ときに検出できる(`>= 0` のような常に真のassertでは検出できない)。
    """
    report = pipeline.run(DAY, tmp_path / "out")
    assert report.ministries == 3, "参照表の3府省すべてが突合されるべき"
    assert report.unmatched_ministries == 0, "正常系で未突合が出てはならない"


def test_run_is_idempotent(seeded_lake, tmp_path):
    out = tmp_path / "out"
    first = pipeline.run(DAY, out)
    second = pipeline.run(DAY, out)
    assert first.organizations == second.organizations
    assert (out / "kg.nq").exists()


def test_run_fails_when_snapshot_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        pipeline.run(DAY, tmp_path / "out")
```

- [ ] **Step 2: テストが失敗することを確認する**

```bash
uv run pytest tests/test_pipeline.py -v
```

期待: `ModuleNotFoundError: No module named 'jgkg.pipeline'` で FAIL。

- [ ] **Step 3: `pipeline.py` を実装する**

```python
"""パイプラインの結線。取得済みスナップショットからN-Quadsまでを1本にする。

各段の件数を PipelineReport として返す。観測性は設計書§11.1の要件。
"""
import datetime
from pathlib import Path

from pydantic import BaseModel
from rdflib import Dataset

from jgkg import lake, validate
from jgkg.config import get_settings
from jgkg.connectors import houjin_bangou
from jgkg.rdf import emit
from jgkg.transform import ministry as ministry_mod
from jgkg.transform import organization as org_mod

MINISTRY_REFERENCE = Path("data/reference/ministry-codes.csv")
SHAPES_DIR = Path("schema/generated")


class PipelineReport(BaseModel):
    release: str
    # 入力スナップショットから解析した全件数。スナップショット破損や欠落の検知に使う
    organizations: int
    # そのうちKGに入れた件数(国の機関のみ)。organizations との差が
    # 「絞り込みで除外された数」になる。両方を出さないと、レポートを読んだ人が
    # 「解析した件数がKGに入っている」と誤解する
    government_organs: int
    ministries: int
    unmatched_ministries: int
    graphs_validated: int
    graphs_quarantined: int
    # 検証を通ったグラフのURI一覧。manifest に渡すため正確な値をここで持つ
    # (N-Quadsのテキストから推測すると、リテラルに含まれる `>` や3項行の
    #  オブジェクトIRIを誤認する。実測で確認済み)
    graphs: list[str]


def _merge(target: Dataset, source: Dataset) -> None:
    for ctx in source.contexts():
        if len(ctx) == 0:
            continue
        g = target.graph(ctx.identifier)
        for triple in ctx:
            g.add(triple)


def run(fetched_on: datetime.date, out_dir: Path) -> PipelineReport:
    settings = get_settings()

    # ファイルパスを渡してストリームで解析する。bytes で読むと実データ(約1GB)で
    # メモリが破綻する(§Task 6 の説明を参照)
    snapshot_path = lake.path_of("houjin-bangou", fetched_on, houjin_bangou.FILENAME)
    if not snapshot_path.exists():
        raise FileNotFoundError(
            f"スナップショットが無い: {snapshot_path}。先にコネクタで取得する"
        )
    # **1パスで「全件数」と「国の機関のみのリスト」を分離する。**
    # 全法人(約500万件)を list() すると pydantic オブジェクトで数GB、さらに emit が
    # rdflib に 3000万トリプルを載せるため破綻する。Phase 0 の目的は基盤の確立であり、
    # 任意の法人が必要になるのは Phase 1 の縦スライス(支出先法人)。設計書§6.2.3の
    # 「規模の問題は分割で対処し、1つを大きくするな」に従う。
    # 全件数も数えるのは、スナップショット破損や欠落を検知するため(§11.1の観測性)
    total_organizations = 0
    orgs: list[org_mod.Organization] = []
    for o in org_mod.parse_file(snapshot_path):
        total_organizations += 1
        if o.is_government_organ:
            orgs.append(o)

    reference = ministry_mod.load_reference(MINISTRY_REFERENCE)
    ministries, unmatched = ministry_mod.build(orgs, reference)

    # default_union=True を忘れないこと。rdflibの既定はFalseで、名前付きグラフを
    # 跨いだ参照が空になる。この欠落は本計画で既に3度発生している
    ds = Dataset(default_union=True)
    _merge(ds, emit.emit_organizations(orgs, "houjin-bangou", fetched_on))
    _merge(ds, emit.emit_ministries(ministries, unmatched, "ministry-codes", fetched_on))

    results = validate.validate_dataset(ds, SHAPES_DIR)
    quarantined = [r for r in results if not r.conforms]
    if quarantined:
        validate.quarantine(ds, results, Path(settings.quarantine_dir))

    clean = validate.passing_dataset(ds, results)
    out_dir.mkdir(parents=True, exist_ok=True)
    emit.write_nquads(clean, out_dir / "kg.nq")

    return PipelineReport(
        release=fetched_on.isoformat(),
        organizations=total_organizations,
        government_organs=len(orgs),
        ministries=len(ministries),
        unmatched_ministries=len(unmatched),
        graphs_validated=len(results),
        graphs_quarantined=len(quarantined),
        # Dataset から正確なグラフURIを取る。テキストから推測してはならない
        graphs=sorted(str(c.identifier) for c in clean.contexts() if len(c) > 0),
    )
```

- [ ] **Step 4: テストが通ることを確認する**

```bash
uv run pytest tests/test_pipeline.py -v
```

期待: 4件すべて PASS。

- [ ] **Step 5: Fusekiのアセンブラ設定を作る**

`fuseki/kg.ttl`。**`tdb2:unionDefaultGraph true` が要点。** これが無いと、`GRAPH` 句を使わないCQクエリが既定グラフ(空)を見て0件になる。CQテストは rdflib 側で `Dataset(default_union=True)` を使っているので、提供側も同じ意味論に揃える。

```turtle
# 成果物のTDB2インデックスを読み取り専用で提供する。
@prefix fuseki: <http://jena.apache.org/fuseki#> .
@prefix rdf:    <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix ja:     <http://jena.hpl.hp.com/2005/11/Assembler#> .
@prefix tdb2:   <http://jena.apache.org/2016/tdb#> .

<#service> rdf:type fuseki:Service ;
    fuseki:name "kg" ;
    # クエリのみを公開する。更新は成果物の差し替えで行う(設計書§6.3)
    fuseki:endpoint [ fuseki:operation fuseki:query ] ;
    fuseki:dataset <#dataset> .

<#dataset> rdf:type tdb2:DatasetTDB2 ;
    tdb2:location "/fuseki/databases/kg" ;
    # 名前付きグラフの和集合を既定グラフにする。CQテスト側の
    # Dataset(default_union=True) と意味論を揃えるため必須
    tdb2:unionDefaultGraph true .
```

- [ ] **Step 6: `docker-compose.yml` を作る**

```yaml
# 読み取り専用のKG提供と、インデックス構築ツール。
# 成果物(TDB2インデックス)は data/artifact/tdb2 に展開しておく。
services:
  fuseki:
    # **タグを固定する。** TDB2のオンディスク形式はJenaのバージョンに紐づくため、
    # `:latest` だとイメージ更新で成果物が読めなくなる恐れがある。インデックスを
    # 作る jena-tools 側と同じバージョンに揃える
    image: apache/jena-fuseki:${JENA_VERSION:?JENA_VERSION を .env に設定する}
    ports:
      - "3030:3030"
    command: ["/jena-fuseki/fuseki-server", "--config=/fuseki/config/kg.ttl"]
    environment:
      - ADMIN_PASSWORD=${FUSEKI_ADMIN_PASSWORD:-change-me-in-env}
    volumes:
      - ./fuseki:/fuseki/config:ro
      # ブロックデバイス上のローカルディレクトリをマウントする。
      # TDB2はメモリマップドファイルを使うため、ネットワークファイル共有
      # (SMB/NFS)上に置かないこと(設計書§6.3)
      - ./data/artifact/tdb2:/fuseki/databases/kg:ro
    restart: unless-stopped

  jena-tools:
    build:
      context: .
      dockerfile: docker/jena-tools.Dockerfile
      args:
        JENA_VERSION: ${JENA_VERSION:?JENA_VERSION を .env に設定する}
    volumes:
      - ./data:/work/data
    profiles:
      - tools
```

- [ ] **Step 7: ビルドスクリプトを作る**

`scripts/build.sh`:

```bash
#!/usr/bin/env bash
# 取得済みスナップショットから成果物までを1コマンドで作る。
# インデックス構築はコンテナ側で行い、実行環境のCPUを使わない
# (バーストVMのクレジット枯渇対策。設計書§6.3)
set -euo pipefail

: "${JENA_VERSION:?JENA_VERSION を .env に設定する}"
FETCHED_ON="${1:?使い方: scripts/build.sh YYYY-MM-DD}"

OUT="data/artifact/${FETCHED_ON}"
mkdir -p "$OUT"

echo "== スキーマ生成 =="
./scripts/generate-schema.sh

echo "== パイプライン実行(検証を含む) =="
uv run python -c "
import datetime, json, pathlib
from jgkg import pipeline
report = pipeline.run(datetime.date.fromisoformat('${FETCHED_ON}'), pathlib.Path('${OUT}'))
pathlib.Path('${OUT}/pipeline-report.json').write_text(
    report.model_dump_json(indent=2), encoding='utf-8')
print(report.model_dump_json(indent=2))
"

echo "== TDB2インデックス構築 =="
docker compose --profile tools run --rm jena-tools \
  tdb2.tdbloader --loc "/work/${OUT}/tdb2" "/work/${OUT}/kg.nq"

echo "== 成果物のtar.gz化とmanifest =="
tar -czf "${OUT}/tdb2.tar.gz" -C "$OUT" tdb2
uv run python -c "
import json, pathlib
from jgkg import build
out = pathlib.Path('${OUT}')
report = json.loads((out / 'pipeline-report.json').read_text(encoding='utf-8'))
m = build.build_manifest(
    nquads=out / 'kg.nq',
    tarball=out / 'tdb2.tar.gz',
    jena_version='${JENA_VERSION}',
    release='${FETCHED_ON}',
    sources={'houjin-bangou': '${FETCHED_ON}'},
    graphs=report['graphs'],
)
build.write_manifest(m, out / 'manifest.json')
print(m.model_dump_json(indent=2))
"

echo "完了: ${OUT}"
```

```bash
chmod +x scripts/build.sh
```

- [ ] **Step 8: 2回に分けてコミットする**

> **Step 0 の変更と本体の変更は別のコミットにする。** 1回でまとめると `refactor:` と `feat:` が混ざり、後から履歴を追いにくい。**各回で `git diff --cached --stat` を確認**して、意図したファイルだけがステージされていることを確かめる(他のエージェントがステージした変更を巻き込む事故が実際に起きている)。

まず Step 0 の分:

```bash
git add src/jgkg/_io.py src/jgkg/lake.py src/jgkg/build.py src/jgkg/validate.py
git diff --cached --stat   # 4ファイルだけであることを確認
git commit -m "refactor: アトミック書き込みを共有ヘルパーに切り出しdefault_unionを補う

lake.pyとbuild.pyに1バイトも違わない同一の_atomic_writeがあり、片方だけ
直すと壊れる典型的な重複だった。src/jgkg/_io.py に切り出して共有する。

あわせてvalidate.pyのpassing_datasetにDataset(default_union=True)を補った。
この欠落は本プロジェクトで既に2件の実害を出しており(CQテストのfixture、
emitのテスト)、現状はcontexts()走査のみで実害はないが、将来このDatasetを
SPARQLで問い合わせた瞬間に3件目が起きる箇所だった。

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

次に本体:

```bash
git add src/jgkg/pipeline.py scripts/build.sh docker-compose.yml fuseki/kg.ttl tests/test_pipeline.py
git commit -m "feat: パイプラインの結線とdocker-composeを追加

各段の件数をPipelineReportとして記録(設計書§11.1)。インデックス構築は
コンテナ側で行い実行環境のCPUを使わない。Fusekiは読み取り専用マウント。"
```

---

### Task 12: コンピテンシー質問のテストとCI

**Files:**
- Create: `schema/competency-questions.md`
- Create: `queries/cq/p0-01-organization-lookup.rq`
- Create: `queries/cq/p0-02-ministry-list.rq`
- Create: `queries/cq/p0-03-provenance-of-edge.rq`
- Create: `queries/cq/p0-04-release-freshness.rq`
- Create: `queries/cq/p0-05-unresolved-count.rq`
- Create: `tests/test_competency_questions.py`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 11 の `pipeline.run` が出す `kg.nq`
- Produces:
  - `tests/test_competency_questions.py` — 各 `.rq` を rdflib の Dataset に対して実行し、期待結果と比較する
  - CI ワークフロー

**設計上の注意**: CQに答えられないオントロジーは不合格とする(設計書§1.2 完了条件A)。Phase 0 では組織ドメインに関するCQ P0-1〜P0-5 を対象とし、**CQ1〜CQ10 は法令・予算データが入る計画Bで扱う**。CQが増えたらテストが増える構造にしておく。

- [ ] **Step 1: CQ台帳を作る**

`schema/competency-questions.md`:

```markdown
# コンピテンシー質問(CQ)台帳

オントロジーは「良さそうなクラスを並べる」のではなく、**KGが答えられるべき
質問を先に文書化し、それに答えられるかで妥当性を判定する**(設計書§5.6)。
CQに答えられないオントロジーは、クラスがどれだけ整っていても不合格とする。

各CQには `queries/cq/` に対応するSPARQLがあり、`tests/test_competency_questions.py`
がテストとして実行する。**CQを追加したらテストも増える。**

## Phase 0(組織ドメイン)

| ID | 質問 | クエリ |
|---|---|---|
| P0-1 | ある法人番号の組織の名称と所在地は何か | `p0-01-organization-lookup.rq` |
| P0-2 | 府省の一覧と、それぞれの法人番号・府省コードは何か | `p0-02-ministry-list.rq` |
| P0-3 | ある関係は、どの一次資料の何日取得分に基づくか | `p0-03-provenance-of-edge.rq` |
| P0-4 | このリリースは各ソースについていつ時点のデータを含むか | `p0-04-release-freshness.rq` |
| P0-5 | 正準IDに解決できなかった参照はどれだけあるか | `p0-05-unresolved-count.rq` |

P0-3〜P0-5 は「**データの欠けと鮮度そのものを問える**」ことを要求している。
公共財として、答えられない部分がどこかを利用者が知れることを設計の一部とする。

## Phase 1(計画Bで実装)

設計書§5.6 の CQ1〜CQ10。法令・予算データが入ってから対象になる。
```

- [ ] **Step 2: SPARQLを書く**

`queries/cq/p0-01-organization-lookup.rq`:

```sparql
# CQ P0-1: ある法人番号の組織の名称と所在地は何か
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX org:  <http://localhost:8080/kg/def/org#>

SELECT ?name ?prefecture WHERE {
  ?s org:houjinBangou "8000012070001" ;
     skos:prefLabel ?name .
  OPTIONAL { ?s org:prefectureName ?prefecture }
}
```

`queries/cq/p0-02-ministry-list.rq`:

```sparql
# CQ P0-2: 府省の一覧と、それぞれの法人番号・府省コードは何か
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX org:  <http://localhost:8080/kg/def/org#>

SELECT ?ministry ?name ?houjinBangou ?ministryCode WHERE {
  ?ministry a org:Ministry ;
            org:ministryCode ?ministryCode ;
            org:houjinBangou ?houjinBangou ;
            skos:prefLabel ?name .
}
ORDER BY ?ministryCode
```

`queries/cq/p0-03-provenance-of-edge.rq`:

```sparql
# CQ P0-3: ある関係は、どの一次資料の何日取得分に基づくか
PREFIX prov:    <http://www.w3.org/ns/prov#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX org:     <http://localhost:8080/kg/def/org#>

SELECT ?graph ?source ?fetchedOn ?license WHERE {
  GRAPH ?graph { ?s org:houjinBangou "8000012070001" }
  ?graph prov:wasDerivedFrom ?source ;
         prov:generatedAtTime ?fetchedOn ;
         dcterms:rights ?license .
}
```

`queries/cq/p0-04-release-freshness.rq`:

```sparql
# CQ P0-4: このリリースは各ソースについていつ時点のデータを含むか
PREFIX prov:    <http://www.w3.org/ns/prov#>
PREFIX dcterms: <http://purl.org/dc/terms/>

SELECT ?sourceName ?fetchedOn WHERE {
  ?graph prov:generatedAtTime ?fetchedOn ;
         dcterms:source ?sourceName .
}
ORDER BY ?sourceName
```

`queries/cq/p0-05-unresolved-count.rq`:

```sparql
# CQ P0-5: 正準IDに解決できなかった参照はどれだけあるか
PREFIX core: <http://localhost:8080/kg/def/core#>

SELECT ?reason (COUNT(?s) AS ?count) WHERE {
  ?s a core:UnresolvedReference ;
     core:unresolved_reason ?reason .
}
GROUP BY ?reason
```

`queries/cq/p0-06-organizations-without-houjin-bangou.rq`:

```sparql
# CQ P0-6: 法人番号を持たないOrganizationは存在するか(0件であるべき)
# SHACLの required では担保できない制約をここで見る。グラフをソース別に
# 分けているため、グラフ単位のSHACL検証ではグラフを跨いだ必須制約を
# 検証できない。その代償措置。
PREFIX org: <http://localhost:8080/kg/def/org#>

SELECT ?s WHERE {
  ?s a ?type .
  VALUES ?type { org:Organization org:GovernmentOrgan org:Ministry }
  FILTER NOT EXISTS { ?s org:houjinBangou ?bangou }
}

- [ ] **Step 3: 失敗するテストを書く**

`tests/test_competency_questions.py`:

```python
"""CQテスト。CQに答えられないオントロジーは不合格(設計書§1.2 完了条件A)。

CQが増えたらここに1件追加する。オントロジー変更のリグレッション検知の主手段。
"""
import datetime
from pathlib import Path

import pytest
from rdflib import Dataset

from jgkg import lake, pipeline
from jgkg.connectors import houjin_bangou

DAY = datetime.date(2026, 8, 1)
CQ_DIR = Path("queries/cq")


@pytest.fixture(autouse=True)
def tmp_env(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_BASE_URI", "http://localhost:8080/kg")
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    monkeypatch.setenv("JGKG_QUARANTINE_DIR", str(tmp_path / "quarantine"))
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def kg(tmp_path):
    content = Path("tests/fixtures/houjin_bangou_sample.csv").read_bytes()
    lake.save("houjin-bangou", DAY, houjin_bangou.FILENAME, content)
    out = tmp_path / "out"
    pipeline.run(DAY, out)

    # default_union=True が必須。既定(False)では既定グラフが空のため、
    # GRAPH句を使わないCQクエリがすべて0件になる。本番のFusekiでも
    # tdb2:unionDefaultGraph true を設定して同じ意味論に揃える(Task 11)
    ds = Dataset(default_union=True)
    ds.parse(out / "kg.nq", format="nquads")
    return ds


def _query(ds: Dataset, name: str):
    return list(ds.query((CQ_DIR / name).read_text(encoding="utf-8")))


def test_cq_p0_01_organization_lookup(kg):
    rows = _query(kg, "p0-01-organization-lookup.rq")
    assert rows, "CQ P0-1 に答えられない"
    assert str(rows[0][0]) == "厚生労働省"


def test_cq_p0_02_ministry_list(kg):
    rows = _query(kg, "p0-02-ministry-list.rq")
    assert rows, "CQ P0-2 に答えられない"
    codes = {str(r[3]) for r in rows}
    assert "020" in codes


def test_cq_p0_03_provenance_of_edge(kg):
    """出典を辿れることはCQの一つ。ここが通らなければ原則7が守れていない。"""
    rows = _query(kg, "p0-03-provenance-of-edge.rq")
    assert rows, "CQ P0-3 に答えられない(グラフの出典が辿れない)"
    graph, source, fetched_on, license_ = rows[0]
    assert "2026-08-01" in str(fetched_on)
    assert str(license_)


def test_cq_p0_04_release_freshness(kg):
    rows = _query(kg, "p0-04-release-freshness.rq")
    assert rows, "CQ P0-4 に答えられない(鮮度が問えない)"
    assert any("2026-08-01" in str(r[1]) for r in rows)


def test_cq_p0_05_unresolved_count(kg):
    """未解決が0件でもクエリ自体は成立すること。件数を問える構造が要件。"""
    rows = _query(kg, "p0-05-unresolved-count.rq")
    assert isinstance(rows, list)


def test_cq_p0_06_every_organization_has_houjin_bangou(kg):
    """法人番号を持たないOrganizationが存在しないこと。

    SHACLでは担保できない制約をここで見る。グラフをソース別に分けているため
    1エンティティの記述が複数グラフに分かれ、グラフ単位のSHACL検証では
    グラフを跨いだ必須制約を検証できない。設計書の判断に対する代償措置。
    """
    rows = _query(kg, "p0-06-organizations-without-houjin-bangou.rq")
    assert rows == [], f"法人番号を持たないOrganizationがある: {rows}"
```

- [ ] **Step 4: テストを実行する**

```bash
uv run pytest tests/test_competency_questions.py -v
```

期待: 5件すべて PASS。FAIL する場合は、SPARQLのプレフィクスが `JGKG_BASE_URI` と一致しているかを確認する(テストは `http://localhost:8080/kg` を使う)。

- [ ] **Step 5: CIワークフローを作る**

`.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: ["**"]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v5

      - name: Set up Python
        run: uv python install 3.12

      - name: Install dependencies
        run: uv sync --extra dev

      - name: Lint
        run: uv run ruff check src tests

      - name: Regenerate schema and fail if it differs from the committed output
        run: |
          ./scripts/generate-schema.sh
          git diff --exit-code schema/generated/ || {
            echo "::error::生成物がコミットされたものと異なる。scripts/generate-schema.sh を実行してコミットする"
            exit 1
          }

      - name: Assert the base URI appears only in config
        run: |
          # ドメイン文字列を config.py 以外に書かないことを固定する(設計書§4.2)
          if grep -rn --include="*.py" "localhost:8080/kg" src/ | grep -v "src/jgkg/config.py"; then
            echo "::error::ベースURIが config.py 以外に書かれている(設計書§4.2)"
            exit 1
          fi

      - name: Test
        run: uv run pytest tests/ -v
```

- [ ] **Step 6: CIが想定通り動くことをローカルで確かめる**

```bash
uv run ruff check src tests
./scripts/generate-schema.sh && git diff --exit-code schema/generated/
uv run pytest tests/ -v
```

期待: すべて成功する。`git diff` が差分を出す場合は、生成物をコミットし直す。

- [ ] **Step 7: コミットする**

```bash
git add schema/competency-questions.md queries/cq/ tests/test_competency_questions.py .github/workflows/ci.yml
git commit -m "feat: CQテストとCIを追加

Phase 0 のCQ P0-1〜P0-5をSPARQLテストとして固定した(設計書§1.2 完了条件A)。
P0-3〜P0-5はデータの欠けと鮮度そのものを問えることを要求する。
CIは生成物の差分とベースURIの散逸も検出する。"
```

---

## Phase 0 の完了条件

以下がすべて満たされたら計画Aは完了とする。

- [ ] `uv run pytest tests/ -v` が全件成功する
- [ ] `./scripts/generate-schema.sh` の出力がコミット済みの生成物と一致する
- [ ] URI整合性テストが通る(SHACLの `sh:targetClass` と OWLのクラスIRIが一致)
- [ ] オーバーレイ整合性テストが通る(オーバーレイの用語がすべて生成OWLに存在)
- [ ] CQ P0-1〜P0-5 のすべてにSPARQLで答えられる
- [ ] `scripts/build.sh <日付>` が成果物(`tdb2.tar.gz` + `manifest.json`)を生成する
- [ ] manifestに Jenaバージョン・sha256・グラフ一覧・ソースごとの取得日が記録される
- [ ] `docker compose up fuseki` で成果物を読み取り専用で提供できる
- [ ] `pipeline-report.json` に組織件数・府省件数・未突合件数・隔離グラフ件数が記録される

**Phase 0 で実測して記録すること**(設計書§6.3、推測値を先に置かない):
- 国の機関と府省を投入したTDB2インデックスの実サイズと、1件あたりのトリプル数・バイト数。**この単価から全法人(約500万件)を投入した場合のサイズを外挿し、サーバーレスコンテナ環境の一時ディスク上限(Azure Container Apps では最大8 GiB)に収まるかを判断する。**全件の実投入は plan B で行う(§Goal の範囲注記を参照)
- 府省の突合率(`ministries / (ministries + unmatched_ministries)`)
- パイプライン全体の実行時間とインデックス構築時間

---

## 計画Aの自己レビュー

**1. 設計書のカバレッジ**

| 設計書の項目 | 実装タスク |
|---|---|
| §4.1 正準ID(法人番号) | Task 6, 7 |
| §4.2 URIパターン・ベースURIの集約 | Task 1、CI(Task 12) |
| §5.1 LinkML単一ソース・生成物のコミット | Task 2 |
| §5.4 モジュール構成(core, org) | Task 2, 8 |
| §5.5 公理オーバーレイ | Task 3 |
| §5.6 CQ駆動 | Task 12 |
| §5.7 バージョンピン・日本語ラベル | Global Constraints、Task 2 |
| §6.1 コンポーネント分割 | File Structure、Task 4〜9 |
| §6.3 成果物方式・manifest・Jenaバージョン | Task 10, 11 |
| §8.1 決定的パーサのみ(LLM不使用) | Task 6 |
| §8.2 未解決を沈黙させない | Task 7, 8 |
| §8.3 SHACL検証ゲート | Task 9 |
| §8.4 名前付きグラフ+PROV-O | Task 8 |
| §10 URI整合性テスト(最重要) | Task 2 |
| §10 オーバーレイ整合性テスト | Task 3 |
| §11.1 再現性・冪等性・観測性 | Task 5, 11 |
| §11.2 ライセンスの機械可読管理 | Task 4 |

**計画Bに送る項目**(この計画の対象外であることを明示): §5.6のCQ1〜CQ10、§7の法令・予算ソースと二経路の接続、§8.1の名寄せ三段(blocking含む)、§6.4の更新の一巡とリリース切替。

**計画Cに送る項目**: §9のAPI層と可視化アプリ。

**2. プレースホルダ検査**: 「TBD」「後で実装」「適切なエラー処理を追加」に相当する記述はない。実URL・Jenaバージョンの2点は**手動確認が必要な項目として明示**し、コード変更を伴わない形(引数・環境変数)にしてある。

**3. 型の一貫性**: `Organization`(Task 6)→ `ministry.build`(Task 7)→ `emit.emit_organizations`/`emit_ministries`(Task 8)→ `validate.validate_dataset`(Task 9)→ `pipeline.run`(Task 11)で、渡す型と関数名が一致している。`emit.NS["core"]` の参照方法をTask 8で定義し、Task 9のテストでも同じ形で使っている。`HOUJIN_BANGOU_RE` はTask 1で定義しTask 6で import している。

**4. 自己レビューで修正した不整合(記録として残す)**

当初、テストのベースURIを `https://example.test/kg` に、LinkMLスキーマの名前空間を `http://localhost:8080/kg` にしていた。この状態では **SHACLのシェイプがデータと別の名前空間を対象にするため、検証が「対象0件で合格」という空振りになる。** SHACL検証ゲート(§8.3)が機能しているように見えて実際は何も検証していない、最も気づきにくい失敗である。

修正内容:
- 名前空間が関係するタスク(6以降)のテストは、スキーマと同じ `http://localhost:8080/kg` を使う
- URI構築のテスト(Task 1)は設定が実際に読まれることを証明する必要があるため、既定値と異なる `https://uri-test.invalid/kg` を使う(`.invalid` は予約TLDなので本物のホストを指す事故がない)
- **`test_schema_namespace_matches_config_default` を追加**し、スキーマの名前空間と設定の既定ベースURIが一致することをCIで固定した。ドメイン確定時は `schema/*.yaml` と `config.py` の既定値を同時に変更する

---

*計画A完了後、計画B(法令・予算ドメインと縦スライス)に進む。*
