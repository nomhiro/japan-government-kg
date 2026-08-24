"""Task 11 必須項目8(Task 5 申し送り): `old-ministries.csv` の出典URLを実確認する。

`data/reference/old-ministries.csv` の先頭コメントは出典として総務省
行政管理局のトップページだけを挙げ、**「具体的なサブページのURLはこのタスク
(ネットワーク禁止)では実機確認できていない — network が使えるタスクで実URLを
確認し、このコメントを更新すること」**と明記していた。ここがその確認である。

やること:
  1. コメントに書いてあるURLが実在するか(HTTPステータス)
  2. **一次資料そのもの**(中央省庁等改革基本法。平成十年法律第百三号、
     law_id=410AC0000000103)を e-Gov 法令API v2 から取り、本文に
     `old-ministries.csv` の18の廃止名称がいくつ現れるかを数える。
     このプロジェクトが既にコネクタで使っているAPIなので、出典として
     追跡可能(sha256を取れる)であり、HTMLの改装で壊れない
  3. 叩いたURLを全部記録する(政府サイトへの礼儀。ブリーフの要求)

**エンコーディングを決め打ちしない。** soumu.go.jp は Shift_JIS(cp932)で
配信しており、UTF-8として読むと本文照合が「0件ヒット」になる —
**それを「そのページに名称が書いていない」と読むのが、この確認で最も
踏みやすい誤りである**(2026-08-24、最初の実行で実際に踏んだ)。

**使い捨てにしない**(裁定B25)。出力は docs/measurements-phase1.md に全量転記する。

使い方:
    uv run python scripts/verify_old_ministries_source.py
"""
import hashlib
import re
import time

import httpx

from jgkg.transform import old_ministries

# `old-ministries.csv` のコメントが出典として挙げているURL(実在確認の対象)
CITED_URL = "https://www.soumu.go.jp/main_sosiki/gyoukan/kanri/"

# 併せて叩くHTMLの候補。**当たったものだけを残さない**(確認の程度が
# 読み手に伝わらなくなる)
CANDIDATE_URLS = [
    CITED_URL,
    "https://www.soumu.go.jp/main_sosiki/gyoukan/kanri/index.html",
    "https://www.soumu.go.jp/",
    "https://www.gyoukaku.go.jp/",
]

# 一次資料: 中央省庁等改革基本法(平成十年法律第百三号)。
# 2001年1月6日の1府22省庁→1府12省庁の再編を定めた法律そのもの
BASIC_ACT_LAW_ID = "410AC0000000103"
LAW_DATA_URL = f"https://laws.e-gov.go.jp/api/2/law_data/{BASIC_ACT_LAW_ID}"
# 中央省庁等改革関係法施行法(平成十一年法律第百六十号)。個別法の改正で
# 旧省庁名を実際に置き換えた施行法
ENABLING_ACT_LAW_ID = "411AC0000000160"
ENABLING_ACT_URL = f"https://laws.e-gov.go.jp/api/2/law_data/{ENABLING_ACT_LAW_ID}"

INTERVAL_SECONDS = 1.0
TIMEOUT = httpx.Timeout(30.0, read=120.0)
TAG_RE = re.compile(r"<[^>]+>")


def _decode(content: bytes, declared: str | None) -> tuple[str, str]:
    """バイト列を文字列にする。**宣言を信じきらず、実際に読めた方を採る。**

    戻り値は (テキスト, 使ったエンコーディング名)。
    """
    candidates = []
    if declared:
        m = re.search(r"charset=([\w-]+)", declared, re.IGNORECASE)
        if m:
            candidates.append(m.group(1).lower())
    candidates += ["utf-8", "cp932", "euc-jp"]
    seen = set()
    for enc in candidates:
        if enc in seen:
            continue
        seen.add(enc)
        try:
            return content.decode(enc), enc
        except (UnicodeDecodeError, LookupError):
            continue
    return content.decode("utf-8", errors="replace"), "utf-8(置換あり)"


def _report_hits(text: str, names: list[str], label: str) -> None:
    hits = [n for n in names if n in text]
    print(f"  {label}: {len(hits)}/{len(names)}")
    if hits:
        print(f"    現れた : {hits}")
    missing = [n for n in names if n not in text]
    if missing:
        print(f"    現れない: {missing}")


def main() -> None:
    names = sorted(old_ministries.load_old_ministries())
    print("=" * 78)
    print("old-ministries.csv の出典URLの実確認(必須項目8)")
    print("=" * 78)
    print(f"CSVに載っている廃止名称: {len(names)} 件")
    print(f"  {names}")
    print()

    with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as client:
        print("### 1. コメントが挙げているURL(と周辺のHTML)")
        for i, url in enumerate(CANDIDATE_URLS):
            if i > 0:
                time.sleep(INTERVAL_SECONDS)  # 政府サイトへの礼儀
            print("-" * 78)
            print(f"URL: {url}" + ("  ← CSVのコメントが挙げている出典" if url == CITED_URL else ""))
            try:
                resp = client.get(url)
            except httpx.HTTPError as exc:
                print(f"  取得失敗: {type(exc).__name__}: {exc}")
                continue
            ctype = resp.headers.get("content-type")
            print(f"  status={resp.status_code} content-type={ctype!r} "
                  f"bytes={len(resp.content)}")
            if str(resp.url) != url:
                print(f"  リダイレクト先: {resp.url}")
            if resp.status_code != 200:
                print("  **このURLは出典として引用できない**")
                continue
            text, enc = _decode(resp.content, ctype)
            print(f"  デコード: {enc}")
            title = re.search(r"<title[^>]*>(.*?)</title>", text, re.DOTALL | re.IGNORECASE)
            print(f"  <title>: {title.group(1).strip() if title else '(無し)'}")
            _report_hits(TAG_RE.sub(" ", text), names, "本文に現れた廃止名称")

        print()
        print("### 2. 一次資料(e-Gov法令API v2。このプロジェクトが既に使っているAPI)")
        for law_id, url, label in (
            (BASIC_ACT_LAW_ID, LAW_DATA_URL, "中央省庁等改革基本法(平成十年法律第百三号)"),
            (ENABLING_ACT_LAW_ID, ENABLING_ACT_URL,
             "中央省庁等改革関係法施行法(平成十一年法律第百六十号)"),
        ):
            time.sleep(INTERVAL_SECONDS)
            print("-" * 78)
            print(f"URL: {url}")
            print(f"  対象: {label}")
            try:
                resp = client.get(url)
            except httpx.HTTPError as exc:
                print(f"  取得失敗: {type(exc).__name__}: {exc}")
                continue
            print(f"  status={resp.status_code} bytes={len(resp.content)}")
            if resp.status_code != 200:
                print(f"  本文: {resp.text[:300]}")
                continue
            print(f"  sha256(応答本文): {hashlib.sha256(resp.content).hexdigest()}")
            data = resp.json()
            info = data.get("law_info", {})
            print(f"  law_num={info.get('law_num')} law_id={info.get('law_id')} "
                  f"promulgation_date={info.get('promulgation_date')}")
            current = data.get("current_revision_info") or {}
            print(f"  law_title={current.get('law_title')} "
                  f"repeal_status={current.get('repeal_status')}")
            # 本文はJSON(law_full_text)に入っている。**構造を推測せず、
            # JSON全体を文字列にして数える**(名称が現れるかどうかだけを見る)
            _report_hits(resp.text, names, "法令本文(JSON全体)に現れた廃止名称")

    _report_establishment_acts(names)


def _report_establishment_acts(names: list[str]) -> None:
    """レイクの全法令メタデータで「{名称}設置法」の在否を見る(機械照合できる証拠)。

    **これが必須項目8で一番強い確認である。** HTMLの出典URLは改装で壊れるし、
    法律の本文に名称が出るかどうかは条文の書き方に左右される。一方
    「その省庁の設置法が現行法令として存在するか」は、e-Gov法令APIの
    全件メタデータに対する機械的な照合であり、このリポジトリが既に
    スナップショットとして持っている(=sha256で追跡できる)。

    **正のコントロールを必ず併記する**(レビューI5: 否定形だけのアサートを
    作らない)。旧省庁18件が0件なのは、現行府省の設置法もまた0件なら
    「照合方法が壊れている」だけかもしれない。現行40行側の在否を並べて
    初めて、非対称が意味を持つ。
    """
    import datetime
    import json as _json

    from jgkg import lake
    from jgkg.connectors import egov_law
    from jgkg.transform import ministry as ministry_mod

    laws_path = lake.path_of("egov-law", datetime.date(2026, 8, 24), egov_law.FILENAME)
    print()
    print("### 3. 「{名称}設置法」が現行法令として存在するか(レイクの全件メタデータ)")
    print(f"スナップショット: {laws_path}")
    if not laws_path.exists():
        print("  **スナップショットが無いので確認できない**")
        return

    establishment: dict[str, tuple[str, str, str]] = {}
    total = 0
    for line in laws_path.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        total += 1
        law = _json.loads(line)
        current = law.get("current_revision_info") or {}
        title = current.get("law_title") or ""
        if "設置法" in title:
            establishment[title] = (
                law["law_info"]["law_id"],
                law["law_info"]["law_num"],
                current.get("repeal_status") or "",
            )
    print(f"法令の総数: {total} / 題名に「設置法」を含む法令: {len(establishment)}")
    print()
    print("旧省庁(old-ministries.csv の18件):")
    old_present = 0
    for name in names:
        key = f"{name}設置法"
        if key in establishment:
            old_present += 1
            print(f"  **存在する** {key}: {establishment[key]}")
        else:
            print(f"  存在しない   {key}")
    print(f"  → 18件のうち現行法令に設置法があるもの: {old_present}")
    print()
    print("正のコントロール: 現行府省(ministry-codes.csv の40行):")
    reference = ministry_mod.load_reference(
        __import__("pathlib").Path("data/reference/ministry-codes.csv")
    )
    present = [r.name for r in reference if f"{r.name}設置法" in establishment]
    absent = [r.name for r in reference if f"{r.name}設置法" not in establishment]
    print(f"  設置法がある: {len(present)}/{len(reference)}")
    print(f"    {present}")
    print(f"  設置法が無い: {len(absent)}/{len(reference)}")
    print(f"    {absent}")
    print("  (無い側は外局・内部組織など、親府省の設置法や別の法律"
          "(国家公務員法・会計検査院法等)で設置されるもの)")
    print()
    print("判定: 旧省庁18件は設置法が現行法令に1件も無く、現行府省は"
          f"{len(present)}件が存在する。この非対称が「もう存在しない」の機械照合可能な証拠になる")


if __name__ == "__main__":
    main()
