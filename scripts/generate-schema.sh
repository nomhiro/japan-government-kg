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

echo "generated files:"
ls -1 "$OUT"
