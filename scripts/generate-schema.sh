#!/usr/bin/env bash
# LinkML から OWL / SHACL / Pydantic を生成する。
# --no-use-native-uris は設計書§10で必須(OWLとSHACLが同じIRIを語ることを保証する)。
# 日本語の言語タグは linkml==1.11.1 のCLIに該当オプションが無いため後処理で付ける。
set -euo pipefail

# Windowsのコンソールコードページ(cp932)でstdoutが開かれると、リダイレクト先の
# Turtleが不正なUTF-8になりrdflibが読めない。どの環境でも同じ生成物になるよう固定する
# (設計書§11.1の再現性要件)
export PYTHONUTF8=1

# Windows(Git Bash/MSYS)は、単独の"/"のようなCLI引数を「POSIXパスらしき文字列」と
# 誤認してWindowsパス(例: "C:/Program Files/Git/")に書き換える。下の
# --enum-iri-separator / がまさにこの形で、実測でも変換され、gen-owlが
# 「有効なURIに見えない」例外で落ちた。Linux(CI)では発生しないため、Windows側だけの
# 生成物が壊れて気づかれない事故になる——どの環境で実行しても同じ生成物になるよう、
# ここで無効化する(設計書§11.1の再現性要件と同じ理由)
export MSYS_NO_PATHCONV=1

OUT=schema/generated
mkdir -p "$OUT"

# **モジュール名を列挙しない。** ここに書き忘れると、そのモジュールの生成物が
# 作られず(あるいは古いまま残り)、検証が静かに素通しになる。schema/*.yaml が
# 対象の定義そのものである(レビューI6と同じ型の欠陥をここでも避ける)
for src in schema/*.yaml; do
  [ -f "$src" ] || continue
  module="$(basename "$src" .yaml)"
  echo "generating from ${src}"
  # **--no-mergeimports を足さないこと(観察O5・設計書§5.5決定44)。**
  # children_are_mutually_disjoint(core.yaml の Entity)はそのモジュールが
  # 直接importする範囲内でしか直接の子クラスを集めない。--no-mergeimports を
  # 付けると core 以外の4モジュールでは子が0件になり公理が黙って抑止される。
  # 21ペアの検査(tests/test_schema_consistency.py)は生成物5ファイルを
  # 合流させてから見るため、core.owl.ttl だけに公理が残っていればテストは
  # 緑のままこの欠落を見逃す
  # --enum-iri-separator / (既定は"#")。裁定B66: 列挙型の許容値のURIは既定で
  # "{enum_uri}#{値}"と作られるが、enum_uri自体が既に"{base}/def/{module}#{列挙型名}"
  # という#入りのハッシュURIなので、既定のままだと2つ目の"#"が生まれ
  # RFC 3986 §3.5(fragmentのpcharに"#"は含まれない)に非適合のIRIになる
  # (実測: 本番の/def/core, /def/budget, /def/allに8件)。フラグメントは"/"を
  # 許容する(pchar / "/" / "?")ため、区切りを"/"にすると列挙型名と値名を
  # 保ったまま単一の"#"に収まる(例: .../core#UnresolvedReasonEnum/AMBIGUOUS)。
  # 許容値ごとに`meaning:`を書く案は見送った——値を足すたびに書き忘れれば
  # 同じ欠陥が再発する「導出すべき値を手書きする」型そのものになるため、
  # 生成規則側の1箇所を直すほうがこのプロジェクトの方針に合う
  uv run gen-owl --no-use-native-uris --enum-iri-separator / "$src" > "${OUT}/${module}.owl.ttl"
  uv run gen-shacl "$src" > "${OUT}/${module}.shacl.ttl"
  uv run gen-pydantic "$src" > "${OUT}/${module}_models.py"
  uv run python -m jgkg.schema_lang "${OUT}/${module}.owl.ttl" "${OUT}/${module}.shacl.ttl"
done

# **生成物はLinuxで作ること。WindowsとLinuxで並び順が変わる(裁定B100)。**
#
# 実測(2026-09-11): 同じ `schema/budget.yaml` から生成しても、Windowsと
# Linuxで `schema/generated/{all,budget}.{owl,shacl}.ttl` の**プロパティ形状の
# 並び順が変わる**(150行が入れ替わる。内容は同じ)。`sh:order` を持つのに
# rdflib のシリアライズ順が違う —— 日本語の長い `sh:description` を持つ
# 形状どうしが入れ替わった。
#
# **症状はローカル緑・CI赤である。** Windowsで生成→Windowsで再生成すると
# 同じ順になるので `git status` は何も言わない。CI(Linux)で再生成すると
# 別の順になり「生成物がコミットされたものと異なる」で落ちる。
# 実際にそれで CI run 34564101411 が失敗した。
#
# **正はLinuxの出力とする**(CIがそれで検査するため)。Windowsで再生成した
# 場合は、コミット前に次でLinuxの出力に置き換えること:
#
#   MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd -W):/w" -w /w -e PYTHONUTF8=1 -e UV_PROJECT_ENVIRONMENT=/tmp/venv python:3.12-slim bash -c 'pip install -q uv && uv sync --quiet && bash ./scripts/generate-schema.sh'
#
# **`MSYS_NO_PATHCONV=1` を必ず付けること**(Windows の Git Bash から実行する場合)。
# 付けないと Git Bash が `-w /w` を `W:/` に変換し、
# `docker: the working directory 'W:/' is invalid` で落ちる(実測)。
#
# **`UV_PROJECT_ENVIRONMENT` を必ず渡すこと** —— 省くとコンテナの `uv sync` が
# マウントした `.venv` をLinux用に上書きし、ホスト側の環境が壊れる(実際に踏んだ)。
case "$(uname -s 2>/dev/null || echo unknown)" in
  Linux*) ;;
  *)
    echo "警告: Linux以外で生成した。**コミットする前にLinuxで生成し直すこと**" >&2
    echo "      (WindowsとLinuxでTurtleの並び順が変わる。上のコメント参照)" >&2
    ;;
esac

echo "generated files:"
ls -1 "$OUT"
