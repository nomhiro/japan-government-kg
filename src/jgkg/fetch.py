"""取得段の実行経路。1つのディスパッチャCLIにする(最終レビューO3)。

`src/jgkg/connectors/*.py` には `fetch`/`fetch_all` はあるが、それを呼ぶ
コマンドがリポジトリに存在しなかった。`scripts/build.sh` はスナップショットが
無いと「先にコネクタで取得する」と案内するが、その「先に」を実行する経路が
無かった——取得が手作業のままでは、更新の一巡(仕様§1.2(C))を人の記憶に
依存させてしまう。

**コネクタごとに `__main__` を足すのではなく、ここに1つのディスパッチャを
置く。** `scripts/build.sh`(`--source ID=YYYY-MM-DD`)と `src/jgkg/pipeline.py`
が既に `--source` の規約を使っており、一巡が `fetch → build → serve` と
同じ語彙で読めるようにする。

    uv run python -m jgkg.fetch --source egov-law
    uv run python -m jgkg.fetch --source rs-system --year 2025
    uv run python -m jgkg.fetch --source houjin-bangou
    uv run python -m jgkg.fetch --source egov-law --source rs-system --year 2025
    uv run python -m jgkg.fetch --law-id 412CO0000000315

**`--law-id`(C-1)は`--source`とは独立した軸。** `--source egov-law`は
全件メタデータ(`/api/2/laws`)を取るが、`--law-id`は指定した法令1件の
本文(`/api/2/law_data/<law_id>`)だけを取る。両方を同じ呼び出しで
指定できる。

**このモジュールは実際に外部へアクセスしない場面でも安全に import できる。**
実取得はA-4(別タスク)で行う。ここは経路を作るところまで(テストに実
ネットワークを含めない。仕様§10)。

**検査の粒度に非対称がある(A-1レビュー指摘。安全側なので挙動は変えていない)。**
`--source`を複数渡したとき、事前検査(上書き拒否・URL未設定)は**1つでも
引っかかればバッチ全体を止める**が、実行時の取得失敗は**源ごとに独立**
していて他の源は試みられる(下記`main`のtry/except参照)。利用者が
気づきにくい非対称であることに注意すること。
"""
import argparse
import datetime
import sys
from collections.abc import Callable

from jgkg import lake, sources
from jgkg.config import get_settings
from jgkg.connectors import egov_law, houjin_bangou, rs_system
from jgkg.connectors.base import FetchResult


def _reject_egov_law_data_via_source(fetched_on: object, year: object, url: object) -> object:
    """`--source egov-law-data` は意図的に使えない(C-2裁定)。

    `egov-law-data` は law_id ごとに取得する源で、全件走査に相当する意味が
    無い。DISPATCHに結線しないと`unwired`検査が「このリポジトリ側の欠陥」
    という誤った主張をしてしまう(実際には意図的な設計であり、結線漏れ
    ではない)。結線した上で、ここで案内エラーを出す——`main`の
    `except Exception`経由でsource_id付きのエラーとして表示される。
    """
    raise ValueError(
        "egov-law-dataは法令1件ずつ取得する(全件走査に相当する意味を持たない)。"
        "--source ではなく --law-id <法令ID> を使うこと"
        "(例: uv run python -m jgkg.fetch --law-id 412CO0000000315)"
    )


# 取得対象の源とその関数を1箇所に集約する(dictから導出。個々の`if`分岐に
# ちりばめない)。source_idがここに無ければ「登録済みだがfetch未対応」を
# 意味する(_reject_if_not_fetchable が local_path で先に弾かないかぎり、
# それはこのモジュールの結線漏れであり利用者の入力ミスではない——区別する。
# egov-law-dataは例外で、結線はあるが意図的に案内エラーを返す)。
DISPATCH: dict[str, Callable[..., object]] = {
    "egov-law": lambda fetched_on, year, url: egov_law.fetch(fetched_on),
    "egov-law-data": _reject_egov_law_data_via_source,
    "houjin-bangou": lambda fetched_on, year, url: houjin_bangou.fetch(url, fetched_on),
    "rs-system": lambda fetched_on, year, url: rs_system.fetch_all(year, fetched_on),
}


def _parse_date(s: str) -> datetime.date:
    try:
        return datetime.date.fromisoformat(s)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--fetched-on が ISO 形式(YYYY-MM-DD)でない: {s!r}"
        ) from exc


def _already_fetched(source_id: str, fetched_on: datetime.date) -> bool:
    """`data/lake/<source_id>/<fetched_on>/` に、既にコミット済みのスナップショットが

    **1件でも**あるか。rs-systemのように複数ファイルを持つ源では、ファイル
    単位ではなく source_id + fetched_on 単位で判定する——**この関数の粒度は
    「その日付に何か1つでもコミット済みならTrue」であり、rs-systemが5本中
    3本目で失敗した場合も1・2本目が既にコミットされているためTrueを返す**
    (=4本目以降を取りに行く再開にも`--allow-overwrite`が必要になる。
    `--allow-overwrite`のヘルプ文言参照)。

    **ただし`--allow-overwrite`を明示して再開しても、1・2本目が政府の
    サーバへ再度取得されるわけではない。** この関数(CLIの事前拒否)と、
    `rs_system.fetch_all`が内部で呼ぶ`fetch_to_lake`(`connectors/base.py`)の
    ファイル単位の冪等性は**別の層**である。前者は「進める前に確認するか」
    だけを判定し、後者が実際にネットワークへ触れるかを決める。1・2本目は
    後者によって実際にスキップされる(実測。
    `tests/test_connector_rs.py::test_fetch_all_resumes_after_a_partial_failure_without_refetching_committed_groups`)。
    「このCLIの事前拒否がsource_id+fetched_on単位までしか見ない粗さ」と
    「実際に再取得が起きるか」は別の問いであり、後者は起きない。

    **`scripts/build.sh` の裁定B31ガード(ディレクトリが空でないか)とは
    検出条件を変えている(`lake.list_snapshots`——つまり`.meta.json`の
    有無で判定する)。** この違いが効くのは、**1本もコミットされていない**
    状態(`lake.save()`はデータ本体→メタデータの順にアトミックに書くため、
    データ本体だけが残ってメタデータが無いことがある。`lake.save`の
    docstring: 「一度の失敗が恒久的な再取得不能を生むことを避ける」)。
    この場合、非空ディレクトリ判定(B31方式)なら中途半端なファイルの
    存在だけで拒否してしまうが、`list_snapshots`(`.meta.json`基準)なら
    「何もコミットされていない」と正しく判定し、`--allow-overwrite`無しで
    そのまま再開できる。
    """
    return any(s.fetched_on == fetched_on for s in lake.list_snapshots(source_id))


def _law_data_already_fetched(law_id: str, fetched_on: datetime.date) -> bool:
    """特定の法令1件の本文(law_id)のスナップショットが既にあるか。

    **`_already_fetched`(上)とは意図的に別の粒度にしている。** `_already_fetched`は
    source_id + fetched_on単位(ファイル名を見ない、rs-systemの複数ファイルを
    想定した粗さ)。`egov-law`(全件メタデータ)と`egov-law-data`(法令本文)を
    別のsource_idに分けた(C-2裁定)ため、両者を混同する誤検出は無くなったが、
    **`egov-law-data`という同じsource_idの下でも、同じ日に複数の異なる
    law_idを取得することがある**(例: `--law-id A --law-id B`)。ファイル名を
    見ない粗い判定だと、Aを取得済みの日にBを取りに行くと無関係なAの存在で
    「既に取得済み」と誤って拒否してしまう。ここではファイル名まで見て
    判定することで、この誤検出を防ぐ。
    """
    filename = egov_law.law_data_filename(law_id)
    return any(
        s.fetched_on == fetched_on and s.path.name == filename
        for s in lake.list_snapshots(egov_law.LAW_DATA_SOURCE_ID)
    )


def main(argv: list[str] | None = None) -> int:
    # Windowsの既定コンソール(cp932)は成功メッセージに使う em dash(—)を
    # エンコードできず、UnicodeEncodeErrorでCLI全体が落ちる(2026-08-26、
    # C-1の実取得——`--law-id 412CO0000000315`——で実際に踏んだ。取得自体は
    # 成功しレイクへの保存も完了していたが、その後の出力整形だけで落ちて
    # いた)。テストのcapsys等、reconfigureを持たないストリームには触れない
    for _stream in (sys.stdout, sys.stderr):
        if hasattr(_stream, "reconfigure"):
            # errorsだけでなくencodingも明示する。ambientの文字コードを
            # 保つ(errorsだけ変える)方式だと、出力先がパイプ(subprocess、
            # `| tee`等)の場合に子プロセスがcp932で書き出してしまい、
            # UTF-8を期待して読む側(他のツール・テスト)が
            # UnicodeDecodeErrorで落ちる(2026-08-26、姉妹スクリプト
            # scripts/extract_ministry_succession.pyのテストで実際に踏んだ。
            # tests/test_fetch.pyのsubprocessテスト参照)
            _stream.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser(
        description="取得段(コネクタ)を呼ぶディスパッチャ。source_idごとに"
        "必要な引数が違う(--year はrs-systemのみ、houjin-bangouは.envのURL)"
    )
    parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        choices=sorted(sources.SOURCES),
        default=None,
        metavar="ID",
        help="取得する源のID。**複数回指定できる**(例: --source egov-law "
        "--source rs-system --year 2025)。data/reference/ にコミットして"
        "管理する参照表(ministry-codesなど。sources.py の local_path 参照)は"
        "取得対象ではない",
    )
    parser.add_argument(
        "--law-id",
        action="append",
        dest="law_ids",
        default=None,
        metavar="ID",
        help="法令1件の本文(law_full_text)を取得するe-Gov法令ID"
        "(例: --law-id 412CO0000000315)。**--sourceとは独立した軸**"
        "(egov-lawの全件メタデータではなく、指定した法令だけを取る)。"
        "複数回指定できる",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="rs-system の対象事業年度。**rs-system 以外に付けるとエラー**"
        "(黙って無視しない)",
    )
    parser.add_argument(
        "--fetched-on",
        type=_parse_date,
        default=None,
        metavar="YYYY-MM-DD",
        help="取得日として記録する日付。既定は実行日(今日)。再現性のために"
        "上書きできる",
    )
    parser.add_argument(
        "--allow-overwrite",
        action="store_true",
        help="同じ (source, fetched-on) に既にコミット済みのスナップショットが"
        "あっても続行する(scripts/build.sh の --allow-overwrite と同じ思想:"
        "意図的なバイパスではなく意図の表明を要求する)。"
        "**実際に上書きすることは無い**——lake.save() はコミット済みスナップ"
        "ショットへの上書きを常に拒否するため、このフラグが実際にすることは"
        "コネクタの冪等スキップ(ネットワークに触れず終了)を許すことだけ。"
        "部分的に失敗した取得(例: rs-systemの5本中3本目で失敗)の再開にも"
        "このフラグの明示が必要になる(意図的なコスト。build.shと同じ)",
    )
    args = parser.parse_args(argv)

    if not args.sources and not args.law_ids:
        parser.error(
            "--source を1つ以上、または --law-id を1つ以上渡す"
            "(例: --source egov-law / --law-id 412CO0000000315)"
        )

    # 同じ源・同じ法令IDが複数回渡されても1回だけ扱う(順序は最初の出現を保つ)
    requested = list(dict.fromkeys(args.sources or []))
    requested_law_ids = list(dict.fromkeys(args.law_ids or []))

    # --- 引数の形だけで判定できる検査(exit 2。argparseの使い方の誤り) ---
    # ここは静的なレジストリ(sources.py)と argv だけで判定できるので、
    # ファイルシステムやネットワークに触れる前に全部弾く(fail fast)。
    for source_id in requested:
        source = sources.get_source(source_id)
        if source.local_path is not None:
            # **"ministry-codes" と文字列で比較しない。** 「取得対象ではない」
            # の定義そのもの(local_path=コミット済み参照表)から判定する
            # ——手書きの1要素除外リストにしない(最終レビュー⚠️Cと同じ型)。
            parser.error(
                f"{source.id!r} は取得対象ではない(コミット済みの参照表。"
                f"{source.local_path} を直接編集する)。取得を試みなかった"
            )

    if "rs-system" in requested and args.year is None:
        parser.error("--source rs-system には --year が必要(対象の事業年度)")
    if args.year is not None and "rs-system" not in requested:
        parser.error(
            f"--year は rs-system 以外の源には付けられない"
            f"(渡された --source: {', '.join(requested)})"
        )

    unwired = [s for s in requested if sources.get_source(s).local_path is None and s not in DISPATCH]
    if unwired:
        # 上のlocal_path検査を通過したのにDISPATCHに無い = sources.pyには
        # 登録されているがこのモジュールの結線が漏れている(利用者の入力
        # ミスではなく、このリポジトリ側の欠陥)。将来ソースが増えたときに
        # 「エラーにもならず何も起きない」を防ぐための安全網
        parser.error(
            f"{unwired} は sources.py に登録されているが jgkg.fetch の "
            "DISPATCH に結線されていない(このリポジトリ側の欠陥。"
            "src/jgkg/fetch.py の DISPATCH に追加すること)"
        )

    # CLIの既定値としての「今日」。--fetched-on で明示できるようにしてあり、
    # テストは常に明示値を渡す(freshness.pyの同じ箇所と同じ理由)
    fetched_on = args.fetched_on or datetime.date.today()  # noqa: DTZ011

    # --- 状態(レイク・.env)に触れないと判定できない検査(exit 1) ---
    if not args.allow_overwrite:
        for source_id in requested:
            if _already_fetched(source_id, fetched_on):
                lake_dir = get_settings().lake_dir
                print(
                    f"エラー: {lake_dir}/{source_id}/{fetched_on.isoformat()}/ には"
                    "既にコミット済みのスナップショットがある。続行するなら"
                    "--allow-overwrite を明示すること"
                    "(実際に上書きはしない——コネクタは同じ取得日なら"
                    "ネットワークに触れずスキップする。このフラグは"
                    "「気づかず同じ日を叩いた」ことを防ぐための確認)",
                    file=sys.stderr,
                )
                return 1
        for law_id in requested_law_ids:
            if _law_data_already_fetched(law_id, fetched_on):
                lake_dir = get_settings().lake_dir
                filename = egov_law.law_data_filename(law_id)
                print(
                    f"エラー: {lake_dir}/{egov_law.LAW_DATA_SOURCE_ID}/{fetched_on.isoformat()}/"
                    f"{filename} には既にコミット済みのスナップショットがある。"
                    "続行するなら --allow-overwrite を明示すること"
                    "(実際に上書きはしない——コネクタは同じ取得日なら"
                    "ネットワークに触れずスキップする)",
                    file=sys.stderr,
                )
                return 1

    url = ""
    if "houjin-bangou" in requested:
        url = get_settings().houjin_bangou_url
        if not url:
            print(
                "エラー: 環境変数 JGKG_HOUJIN_BANGOU_URL が未設定(または空)。"
                "houjin-bangou の全件データはURLに月次で変わる識別子"
                "(selDlFileNo)を含むため、ソースコードに書けない。次の手順で"
                "値を確認し .env に設定する:\n"
                "  1. https://www.houjin-bangou.nta.go.jp/download/zenken/ を開く\n"
                "  2.「全国・CSV形式・Unicode」の行の doDownload(<番号>) の"
                "<番号>を確認する(Shift-JIS版ではないこと)\n"
                "  3. .env に次の形で設定する:\n"
                "     JGKG_HOUJIN_BANGOU_URL=https://www.houjin-bangou.nta.go.jp/"
                "download/zenken/index.html?event=download&selDlFileNo=<番号>\n"
                "(番号は月次のデータ更新ごとに変わる。詳細は .env.example のコメント参照)",
                file=sys.stderr,
            )
            return 1

    failed: list[str] = []
    for source_id in requested:
        try:
            result = DISPATCH[source_id](fetched_on, args.year, url)
        except Exception as exc:  # noqa: BLE001 — 1つの源の失敗で他を止めない。
            # 何が失敗したかを利用者に伝えるのが目的で、例外型を狭めると
            # コネクタが投げうる全種類(httpx.HTTPStatusError,
            # IncompleteSnapshotError, UnexpectedResponseError, ...)を
            # このモジュールが把握し続けないといけなくなる(結合を増やす)
            print(f"{source_id}: 失敗 — {exc}", file=sys.stderr)
            failed.append(source_id)
            continue

        if isinstance(result, FetchResult):
            results = {source_id: result}
        else:
            # rs_system.fetch_all() は group名をキーにした dict を返す
            results = result  # type: ignore[assignment]

        for label, r in results.items():
            state = "スキップ(既にコミット済み。ネットワークに触れていない)" if r.skipped else "取得完了"
            # 単一ファイルの源(egov-law/houjin-bangou)はlabel==source_idで
            # 冗長になる(例: "egov-law (egov-law): ..."。A-1レビュー指摘)。
            # rs-systemのようにgroup名がlabelになる場合だけ括弧で示す
            name = source_id if label == source_id else f"{source_id} ({label})"
            print(f"{name}: {state} — {r.snapshot.path}")

    for law_id in requested_law_ids:
        try:
            law_result = egov_law.fetch_law_data(law_id, fetched_on)
        except Exception as exc:  # noqa: BLE001 — 上のDISPATCHループと同じ理由
            print(f"law-id {law_id}: 失敗 — {exc}", file=sys.stderr)
            failed.append(f"law-id:{law_id}")
            continue
        state = (
            "スキップ(既にコミット済み。ネットワークに触れていない)"
            if law_result.skipped else "取得完了"
        )
        print(f"law-id {law_id}: {state} — {law_result.snapshot.path}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
