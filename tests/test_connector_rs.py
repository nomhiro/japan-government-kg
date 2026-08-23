import csv
import datetime
import io
import time
import zipfile
from pathlib import Path

import httpx
import pytest

from jgkg import lake
from jgkg.connectors import rs_system
from jgkg.transform import ministry, rs_columns

REPO_ROOT = Path(__file__).parent.parent
MINISTRY_CODES_CSV = REPO_ROOT / "data" / "reference" / "ministry-codes.csv"

FIXTURES = Path(__file__).parent / "fixtures"
YEAR = 2025
DAY = datetime.date(2026, 8, 1)


@pytest.fixture(autouse=True)
def tmp_lake(tmp_path, monkeypatch):
    monkeypatch.setenv("JGKG_LAKE_DIR", str(tmp_path / "lake"))
    from jgkg.config import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _zip_of(csv_bytes: bytes, member: str) -> bytes:
    """RSの実配布と同じ形(zip内にCSVが1本だけ)でテスト用に包む。

    tests/zenken_rows.py の zipped() は法人番号全件データの配布形
    (zip + .asc署名)を写したもので、RSの実配布(zip内はCSV1本のみ、実測)とは
    形が違うため流用しない。ここに専用の最小ヘルパを持つ。
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, csv_bytes)
    return buf.getvalue()


def _header_of(sample_bytes: bytes) -> list[str]:
    """fixtureの1行目(ヘッダ)をBOM除去して読む。"""
    text = sample_bytes.decode("utf-8-sig")
    return next(csv.reader(io.StringIO(text)))


PAYEE_SAMPLE = (FIXTURES / "rs_sample.csv").read_bytes()
LAW_SAMPLE = (FIXTURES / "rs_law_sample.csv").read_bytes()
BUDGET_SAMPLE = (FIXTURES / "rs_budget_sample.csv").read_bytes()


def _budget_rows_for_project(project_id: str) -> list[list[str]]:
    reader = csv.reader(io.StringIO(BUDGET_SAMPLE.decode("utf-8-sig")))
    next(reader)  # header
    idx_pid = rs_columns.RS_FILES["budget_summary"].col["project_id"]
    return [row for row in reader if row[idx_pid] == project_id]


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _zip_responder(payload_by_url: dict[str, bytes]):
    """URLごとに固定のzipバイト列を返すハンドラ。未登録URLは404。"""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url not in payload_by_url:
            return httpx.Response(404)
        return httpx.Response(
            200, content=payload_by_url[url], headers={"content-type": "application/zip"}
        )

    return handler


# ============================================================
# fetch_group: 単一グループファイルの取得・保存
# ============================================================


def test_fetch_group_saves_snapshot_to_lake():
    """1本のグループファイルが、配布形態(zip)のまま保存されること。"""
    payload = _zip_of(PAYEE_SAMPLE, "5-1_RS_2025_支出先_支出情報.csv")
    url = rs_system.url_for("payee_payment_information", YEAR)
    client = _client(_zip_responder({url: payload}))

    result = rs_system.fetch_group("payee_payment_information", YEAR, DAY, client=client)

    assert result.skipped is False
    assert result.snapshot.source_id == rs_system.SOURCE_ID
    filename = rs_system.filename_for("payee_payment_information", YEAR)
    assert lake.load(rs_system.SOURCE_ID, DAY, filename) == payload


def test_fetch_group_is_idempotent():
    """同じ取得日に2度呼んでも、2度目はネットワークに触れずスキップされる。"""
    payload = _zip_of(PAYEE_SAMPLE, "5-1_RS_2025_支出先_支出情報.csv")
    url = rs_system.url_for("payee_payment_information", YEAR)
    client = _client(_zip_responder({url: payload}))

    first = rs_system.fetch_group("payee_payment_information", YEAR, DAY, client=client)
    assert first.skipped is False

    def _explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError("2度目の取得はネットワークに触れないはず")

    exploding_client = _client(_explode)
    second = rs_system.fetch_group(
        "payee_payment_information", YEAR, DAY, client=exploding_client
    )
    assert second.skipped is True
    assert second.snapshot.sha256 == first.snapshot.sha256


def test_fetch_group_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = _client(handler)
    with pytest.raises(httpx.HTTPStatusError):
        rs_system.fetch_group("payee_payment_information", YEAR, DAY, client=client)


def test_fetch_group_raises_on_soft_404_html_response():
    """存在しない年度・ファイル名で、CloudFrontがHTTP 200 + SPAのindex.html
    シェルを返す実測済みの挙動を再現する(rs_system.py モジュールdocstring
    「既知の罠」参照)。ステータスコードだけを見て保存してはならない。
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'<!doctype html><html lang="ja"><head></head><body>'
            b'<div id="root"></div></body></html>',
            headers={"content-type": "text/html"},
        )

    client = _client(handler)
    with pytest.raises(rs_system.UnexpectedResponseError):
        rs_system.fetch_group("payee_payment_information", YEAR, DAY, client=client)

    # 誤った応答がスナップショットとして残っていないこと(サイレントに壊れていない)
    assert lake.list_snapshots(rs_system.SOURCE_ID) == []


# 2026-08-23 に実際に rssystem.go.jp へGETして200 OK(application/zip)を
# 確認した実URL(5本すべて。task-6-report.md「叩いたURL」参照)。
# レビュー指摘7: 以前はorganization_informationの1本だけを固定していたため、
# 残り4本のファイル名テンプレートに将来誤字が入っても検知できなかった
VERIFIED_URLS: dict[str, str] = {
    "organization_information": (
        "https://rssystem.go.jp/files/2025/rs/"
        "1-1_RS_2025_%E5%9F%BA%E6%9C%AC%E6%83%85%E5%A0%B1_"
        "%E7%B5%84%E7%B9%94%E6%83%85%E5%A0%B1.zip"
    ),
    "project_summary": (
        "https://rssystem.go.jp/files/2025/rs/"
        "1-2_RS_2025_%E5%9F%BA%E6%9C%AC%E6%83%85%E5%A0%B1_"
        "%E4%BA%8B%E6%A5%AD%E6%A6%82%E8%A6%81%E7%AD%89.zip"
    ),
    "policy_measure_laws_and_regulations": (
        "https://rssystem.go.jp/files/2025/rs/"
        "1-3_RS_2025_%E5%9F%BA%E6%9C%AC%E6%83%85%E5%A0%B1_"
        "%E6%94%BF%E7%AD%96%E3%83%BB%E6%96%BD%E7%AD%96%E3%80%81%E6%B3%95%E4%BB%A4%E7%AD%89.zip"
    ),
    "budget_summary": (
        "https://rssystem.go.jp/files/2025/rs/"
        "2-1_RS_2025_%E4%BA%88%E7%AE%97%E3%83%BB%E5%9F%B7%E8%A1%8C_"
        "%E3%82%B5%E3%83%9E%E3%83%AA.zip"
    ),
    "payee_payment_information": (
        "https://rssystem.go.jp/files/2025/rs/"
        "5-1_RS_2025_%E6%94%AF%E5%87%BA%E5%85%88_"
        "%E6%94%AF%E5%87%BA%E6%83%85%E5%A0%B1.zip"
    ),
}


def test_url_for_matches_the_url_verified_against_the_real_network():
    """2026-08-23 に実際に rssystem.go.jp へGETして確認した実URLと一致すること。

    url_for() は urllib.parse.quote で組み立てる。この値がずれれば
    (例: quoteの safe引数やUnicode正規化が変わった場合)、実サーバーには
    通らないのに単体テストは気付かない。**FETCHED_GROUPS(実取得済みの5本)
    すべてを固定する**(レビュー指摘7。以前はorganization_informationの
    1本だけだった)。
    """
    assert set(VERIFIED_URLS.keys()) == set(rs_system.FETCHED_GROUPS), (
        "VERIFIED_URLSがFETCHED_GROUPSと1対1で対応していない"
    )
    for group, expected_url in VERIFIED_URLS.items():
        assert rs_system.url_for(group, 2025) == expected_url, group


# ============================================================
# fetch_all: 複数グループファイルのオーケストレーション
# ============================================================


def test_fetch_all_fetches_every_requested_group_with_correct_filenames():
    groups = rs_system.FETCHED_GROUPS
    payload = _zip_of(PAYEE_SAMPLE, "dummy.csv")  # プラミング検証には内容は無関係
    payload_by_url = {rs_system.url_for(g, YEAR): payload for g in groups}
    client = _client(_zip_responder(payload_by_url))

    results = rs_system.fetch_all(YEAR, DAY, groups=groups, client=client)

    assert set(results.keys()) == set(groups)
    for group in groups:
        assert results[group].skipped is False
        filename = rs_system.filename_for(group, YEAR)
        assert lake.load(rs_system.SOURCE_ID, DAY, filename) == payload


def test_fetch_all_sleeps_between_files_but_not_before_the_first(monkeypatch):
    """ファイル間に待機を挟むこと(公共のCDNへの礼儀。このタスクのネットワーク特例が要求する)。"""
    sleeps: list[float] = []
    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(seconds))

    groups = rs_system.FETCHED_GROUPS
    payload = _zip_of(PAYEE_SAMPLE, "dummy.csv")
    payload_by_url = {rs_system.url_for(g, YEAR): payload for g in groups}
    client = _client(_zip_responder(payload_by_url))

    rs_system.fetch_all(YEAR, DAY, groups=groups, client=client)

    assert sleeps == [rs_system.FILE_INTERVAL_SECONDS] * (len(groups) - 1)


# ============================================================
# rs_columns: 列対応の照合記録がfixtureの実データと矛盾しないこと
# ============================================================


def test_verify_header_accepts_the_real_fixture_header():
    header = _header_of(PAYEE_SAMPLE)
    rs_columns.verify_header("payee_payment_information", header)  # 例外にならない

    law_header = _header_of(LAW_SAMPLE)
    rs_columns.verify_header("policy_measure_laws_and_regulations", law_header)


def test_verify_header_rejects_wrong_column_count():
    header = _header_of(PAYEE_SAMPLE)[:-1]  # 1列減らす
    with pytest.raises(rs_columns.ColumnLayoutError):
        rs_columns.verify_header("payee_payment_information", header)


def test_verify_header_rejects_a_renamed_column():
    """列数は合っているが、列名が1つ違う(列がずれた実データを模す)。"""
    header = list(_header_of(PAYEE_SAMPLE))
    assert header[19] == "法人番号"  # 実データの実際の値(照合記録どおり)であることの確認
    header[19] = "法人番号_ずれた列名"  # 列がずれた実データを模す
    with pytest.raises(rs_columns.ColumnLayoutError):
        rs_columns.verify_header("payee_payment_information", header)


def test_fixture_rows_have_the_expected_recipient_houjin_bangou_presence():
    """fixtureが要求どおり、法人番号がある行・無い行の両方を含むこと。

    無い行のうち1件は構造的な空欄(ブロック行)、1件は実質的な欠落
    (その他支出先=TRUEの束ね)である(rs_columns.py 照合記録参照)。
    """
    reader = csv.reader(io.StringIO(PAYEE_SAMPLE.decode("utf-8-sig")))
    header = next(reader)
    idx_houjin = rs_columns.RS_FILES["payee_payment_information"].col[
        "recipient_houjin_bangou"
    ]
    idx_other = header.index("その他支出先")
    rows = list(reader)

    houjin_values = [row[idx_houjin].strip() for row in rows]
    assert any(v for v in houjin_values), "法人番号がある行が無い"
    assert any(not v for v in houjin_values), "法人番号が無い行が無い"
    assert any(row[idx_other] == "TRUE" for row in rows), (
        "「その他支出先」で束ねられた(実質的に法人番号が欠落する)行が無い"
    )


def test_fixture_law_rows_have_a_basis_law_with_egov_style_law_id():
    """fixtureの根拠法令行が、e-Govと同形式のlaw_idを持つこと(検証1の根拠)。"""
    reader = csv.reader(io.StringIO(LAW_SAMPLE.decode("utf-8-sig")))
    next(reader)  # header
    spec = rs_columns.RS_FILES["policy_measure_laws_and_regulations"]
    idx_text = spec.col["basis_law_text"]
    idx_id = spec.col["basis_law_id"]

    rows = list(reader)
    assert all(row[idx_text] for row in rows), "法令名が空の行がある"
    for row in rows:
        law_id = row[idx_id]
        # e-Gov law_id の実測形式(例: 322AC0000000120, 503AC0000000036):
        # 英数字15文字程度。厳密な文法検査ではなく、明らかに空・極端に短い値
        # (列がずれた場合に起きる)だけを弾く
        assert law_id.isalnum(), f"law_idが英数字ではない: {law_id!r}"
        assert len(law_id) >= 10, f"law_idが短すぎる: {law_id!r}"


def test_find_budget_aggregate_row_picks_the_right_row_for_the_simple_case():
    """レビュー指摘2: project 828(総務省/消防庁。列5≠6でもある実例)の
    単純な集計+明細ペアから、集計行だけを正しく拾えること。
    """
    rows = _budget_rows_for_project("828")
    assert len(rows) == 2  # 集計1 + 明細1
    agg = rs_columns.find_budget_aggregate_row(rows, "2025")
    spec = rs_columns.RS_FILES["budget_summary"]
    assert agg[spec.col["budget_amount"]] == "95667000"
    assert agg[spec.col["ministry_name"]] == "総務省"


def test_find_budget_aggregate_row_ignores_multiple_detail_rows():
    """project 159は明細行が2件(特別会計の勘定が2つに分かれる)あるが、
    集計行は例外なく1件に絞れること。
    """
    rows = _budget_rows_for_project("159")
    assert len(rows) == 3  # 集計1 + 明細2
    agg = rs_columns.find_budget_aggregate_row(rows, "2023")
    spec = rs_columns.RS_FILES["budget_summary"]
    assert agg[spec.col["budget_amount"]] == "10041533000"


def test_find_budget_aggregate_row_treats_the_string_zero_as_non_empty():
    """project 5551はゼロ予算だが、'0'という文字列は空文字ではないので、
    集計行として正しく拾えること。

    踏みやすい罠は「予算が0なら実質的にデータが無い行と同じ」と誤解し、
    '0'を明細行の空欄と混同すること(意味的な誤り。Pythonの文字列真偽値
    としては非空文字列は常にTruthyなので、`if amount:`という素朴な判定でも
    偶然正しく動く。危険なのは`amount in ("", "0")`のように**明示的に'0'を
    「無い」扱いする**実装)。ゼロ予算は実データに実在する正規の値である。
    """
    rows = _budget_rows_for_project("5551")
    agg = rs_columns.find_budget_aggregate_row(rows, "2025")
    spec = rs_columns.RS_FILES["budget_summary"]
    assert agg[spec.col["budget_amount"]] == "0"


def test_find_budget_aggregate_row_raises_when_the_fiscal_year_is_absent():
    """指定した予算年度の行が無ければ、空を返さずColumnLayoutErrorにすること。"""
    rows = _budget_rows_for_project("828")
    with pytest.raises(rs_columns.ColumnLayoutError):
        rs_columns.find_budget_aggregate_row(rows, "1999")


def test_ministry_name_uses_column_5_not_column_6_when_they_disagree():
    """レビュー指摘3: project 828(危険物事故防止対策の推進)は列5≠列6の
    実例([5]政策所管府省庁='総務省' [6]府省庁='消防庁')。RS_COLの
    ministry_nameは列5(総務省)を指すこと。

    将来誰かが「列6の方が素直な名前だから」と書き換えても、payee/lawの
    fixtureは列5=列6の行しか無いため検知できない(レビュー指摘3)。この
    テストが、列5・列6が実際に異なる実データ行で検査する最初のテスト。
    """
    rows = _budget_rows_for_project("828")
    spec = rs_columns.RS_FILES["budget_summary"]
    idx_ministry = spec.col["ministry_name"]
    idx_col6 = 6  # 「府省庁」列。RS_COLでは論理名を割り当てていない

    agg = rs_columns.find_budget_aggregate_row(rows, "2025")
    assert agg[idx_ministry] == "総務省"
    assert agg[idx_col6] == "消防庁"
    assert agg[idx_ministry] != agg[idx_col6], "fixtureが列5≠列6の実例でなくなっている"


def test_kensei_jun_matches_ministry_name_1to1_and_agrees_with_the_reference_table():
    """レビュー指摘1: 列4(建制順)が[5]ministry_nameと1対1対応すること、かつ
    data/reference/ministry-codes.csv の kensei_jun 列と一致すること
    (どちらも2026-08-23のRS実データ由来なので一致するはず)。

    fixtureに含まれる実在の対応(実測): 内閣官房=1、デジタル庁=13。
    **kensei_junは識別子(府省コード)として使わない**(裁定B15)。この
    テストは値の一貫性のみを検査する。
    """
    reference_kensei_jun = {
        row.name: row.kensei_jun
        for row in ministry.load_reference(MINISTRY_CODES_CSV)
        if row.kensei_jun is not None
    }
    assert reference_kensei_jun, "ministry-codes.csv にkensei_jun列の値が1つも無い"

    for sample, group in [
        (PAYEE_SAMPLE, "payee_payment_information"),
        (LAW_SAMPLE, "policy_measure_laws_and_regulations"),
    ]:
        reader = csv.reader(io.StringIO(sample.decode("utf-8-sig")))
        next(reader)  # header
        spec = rs_columns.RS_FILES[group]
        idx_ministry = spec.col["ministry_name"]
        idx_kensei = spec.col["kensei_jun"]

        seen: dict[str, str] = {}
        for row in reader:
            name, kensei = row[idx_ministry], row[idx_kensei]
            if name in seen:
                assert seen[name] == kensei, (
                    f"{group}: {name!r} の建制順が行によって違う"
                    f"({seen[name]!r} vs {kensei!r})"
                )
            seen[name] = kensei

            assert name in reference_kensei_jun, (
                f"{group}: {name!r} が data/reference/ministry-codes.csv に無い"
            )
            assert reference_kensei_jun[name] == kensei, (
                f"{group}: {name!r} の建制順がministry-codes.csvと食い違う"
                f"(fixture={kensei!r}, 参照表={reference_kensei_jun[name]!r})"
            )


# ============================================================
# rs_system と rs_columns の配線一貫性
# ============================================================


def test_all_fetched_groups_have_a_verified_column_spec():
    for group in rs_system.FETCHED_GROUPS:
        assert group in rs_columns.RS_FILES


def test_rs_col_entries_agree_with_the_per_file_column_spec():
    for logical_name, (group, idx) in rs_columns.RS_COL.items():
        spec = rs_columns.RS_FILES[group]
        assert 0 <= idx < spec.expected_columns
        assert spec.col[logical_name] == idx


def test_no_group_is_both_fetched_and_unverified():
    assert set(rs_system.FETCHED_GROUPS).isdisjoint(rs_columns.RS_UNVERIFIED_GROUPS)


def test_every_group_filename_is_accounted_for():
    """rs_system(全15本のファイル名)と rs_columns(確認済み5本+未確認10本)が
    1対1で対応していること(取りこぼし・重複registrationを防ぐ)。
    """
    all_groups = set(rs_system.RS_GROUP_FILENAMES.keys())
    accounted = set(rs_columns.RS_FILES.keys()) | set(rs_columns.RS_UNVERIFIED_GROUPS)
    assert all_groups == accounted


def test_column_layout_error_matches_organization_pys_base_class():
    """レビュー指摘6: organization.pyのColumnLayoutErrorと同じ基底クラス
    (ValueError)であること。docstringが「同じ考え方」と書いているのに
    実装がRuntimeErrorだった食い違いを、型として固定する。
    """
    assert issubclass(rs_columns.ColumnLayoutError, ValueError)
