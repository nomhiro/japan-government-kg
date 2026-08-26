"""C-1: 法令の対応表から旧省庁→新府省の継承マッピングを抽出し、

`data/reference/ministry-succession.csv` を書き出す。

`jgkg.fetch --law-id <law_id>` で取得済みのレイクスナップショット
(`egov-law-data` source_idの下。egov_law.LAW_DATA_SOURCE_ID参照)を読み、
`jgkg.transform.ministry_succession` でTableノードを抽出したのち、
`data/reference/old-ministries.csv` の18名称のうち何件を解決できたかを
表示する(C-1ブリーフの受け入れ条件)。

**使い捨てにしない**(裁定B25)。出力(解決件数・未解決の名称・落とした
行数)は `task-C1-report.md` に転記する。

使い方:
    uv run python scripts/extract_ministry_succession.py
    uv run python scripts/extract_ministry_succession.py --law-id 412CO0000000315
"""
import argparse
import json
import sys

from jgkg import lake
from jgkg.connectors import egov_law
from jgkg.transform import ministry_succession as ms
from jgkg.transform.old_ministries import load_old_ministries

DEFAULT_LAW_ID = "412CO0000000315"
OUTPUT_PATH = "data/reference/ministry-succession.csv"

_HEADER_COMMENT = """\
# source: {law_id}「中央省庁等改革のための国の行政組織関係法律の整備等に
#   関する法律附則第三条の審議会等の委員等に類する者及び従前の府省等の
#   相当の新府省等を定める政令」(C-1、controller実機確認・実装者再取得)
#   https://laws.e-gov.go.jp/api/2/law_data/{law_id}
#   実測: status=200, {byte_size} bytes, sha256={sha256}
#   取得日: {fetched_on}(レイク: {lake_path})
#
# 抽出方法: law_full_textを再帰的に走査してtag=="Table"のノードを見つけ、
#   ヘッダ行の文言(「従前」「新」)で列の意味を導出する(列の位置を
#   決め打ちにしない。src/jgkg/transform/ministry_succession.py 参照)。
#   old_name/new_nameは末尾の括弧限定(例:「(造幣局...を除く。)」)を
#   取り除いた形。row_indexは選んだTableノードのchildren内での生の添字
#   (ヘッダ行が0。レイクの生JSONを開いて children[row_index] を数えれば
#   同じ行にたどり着ける)
#
# 注意: 全59行のうち8行(総理府の外局だった庁・委員会)は「総理府」+
#   外局名を連結した形でしか現れない(例:「総理府北海道開発庁」)。
#   old_name列はこの連結を分解していない生の抽出結果であり、
#   data/reference/old-ministries.csv の18名称への解決(prefix-
#   decomposition。同モジュールのresolve_old_ministries参照)は
#   このファイルの行そのものには反映していない
#
# scope: このファイルは「対応表を抽出した、出典付きの参照データ」まで
#   (C-1)。オントロジー側の変更(AbolishedGovernmentOrgan・succeededBy)や
#   パイプラインへの結線(OLD_MINISTRYの解決)は次のタスクの範囲
old_text,new_text,old_name,new_name,source_law_id,row_index
"""


def _csv_field(value: str) -> str:
    if any(c in value for c in (",", '"', "\n")):
        return '"' + value.replace('"', '""') + '"'
    return value


def _latest_law_data_snapshot(law_id: str) -> lake.Snapshot:
    filename = egov_law.law_data_filename(law_id)
    candidates = [
        s for s in lake.list_snapshots(egov_law.LAW_DATA_SOURCE_ID) if s.path.name == filename
    ]
    if not candidates:
        raise FileNotFoundError(
            f"law_id={law_id!r} のレイクスナップショットが無い。"
            f"先に `uv run python -m jgkg.fetch --law-id {law_id}` を実行すること"
        )
    return max(candidates, key=lambda s: s.fetched_on)


def main() -> int:
    # Windows上でstdout/stderrがパイプ(subprocess等)に繋がっていると、
    # 既定の文字コードがコンソール(UTF-8)ではなくシステムのANSIコードページ
    # (このマシンではcp932)に落ちることがある(2026-08-26、このスクリプトの
    # テストをsubprocess経由で実行して実際に踏んだ: 子プロセスがcp932で
    # 書き出し、`encoding="utf-8"`で読む親プロセス側がUnicodeDecodeErrorで
    # 落ちた)。出力先を問わずUTF-8に固定する
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--law-id", default=DEFAULT_LAW_ID)
    args = parser.parse_args()

    snapshot = _latest_law_data_snapshot(args.law_id)
    raw = snapshot.path.read_bytes()
    law_full_text = json.loads(raw)["law_full_text"]

    extraction = ms.extract_succession_rows(law_full_text, source_law_id=args.law_id)

    lines = [
        _HEADER_COMMENT.format(
            law_id=args.law_id,
            byte_size=snapshot.byte_size,
            sha256=snapshot.sha256,
            fetched_on=snapshot.fetched_on.isoformat(),
            # snapshot.path から直接導出する(テンプレート文字列に
            # source_id/日付/ファイル名を書き分けて再構築しない)。
            # C-2で law_data の source_id を移した際、ここが手書きの
            # テンプレートのままだと存在しないパスを報告してしまう
            # ところだった(レビュー指摘)
            lake_path=snapshot.path.as_posix(),
        )
    ]
    for row in extraction.rows:
        lines.append(
            ",".join(
                _csv_field(v)
                for v in (
                    row.old_text, row.new_text, row.old_name, row.new_name,
                    row.source_law_id, str(row.row_index),
                )
            )
            + "\n"
        )
    with open(OUTPUT_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.writelines(lines)

    print(f"書き出し: {OUTPUT_PATH}({len(extraction.rows)}行)")
    print(
        f"落とした行: {len(extraction.dropped_rows)}件"
        + (f" {extraction.dropped_rows}" if extraction.dropped_rows else "")
    )

    target_names = load_old_ministries()
    coverage = ms.resolve_old_ministries(extraction.rows, frozenset(target_names))
    print(f"\n18名称の網羅({len(target_names)}件中):")
    for r in sorted(coverage.resolved, key=lambda r: r.target_name):
        print(f"  解決: {r.target_name} -> {r.row.new_name}  [{r.mechanism}]")
    if coverage.unresolved:
        for name in coverage.unresolved:
            print(f"  未解決: {name}")
    else:
        print("  未解決なし(18/18)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
