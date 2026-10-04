"""RS公開事業詳細の収集。python -m jgkg.connectors.rs_api --year 2026"""
import argparse
import hashlib
import json
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx

from jgkg.collection import REGISTRY_PATH
from jgkg.collection_runs import CollectionRun

BASE = "https://rssystem.go.jp/api/projects/"


class Reader:
    def __init__(self, client: httpx.Client, interval: float = 2):
        self.client = client
        self.interval = interval
        self.last = 0.0

    def get(self, url: str):
        for attempt in range(3):
            time.sleep(max(0, self.interval - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            try:
                response = self.client.get(url)
            except httpx.TransportError:
                if attempt == 2:
                    raise
                time.sleep(2 ** (attempt + 1))
                continue
            if response.status_code == 429 or response.status_code >= 500:
                if attempt == 2:
                    response.raise_for_status()
                value = response.headers.get("Retry-After", "")
                try:
                    delay = float(value)
                except ValueError:
                    try:
                        delay = (parsedate_to_datetime(value)
                                 - datetime.now(UTC)).total_seconds()
                    except (ValueError, TypeError):
                        delay = 2 ** (attempt + 1)
                # 長い停止要求は呼び出しを失敗させ、後で明示的に再開する。
                if delay > 60:
                    raise RuntimeError(f"Retry-After={value}。指定時間後に同じrun_idで再開")
                time.sleep(max(0, delay))
                continue
            response.raise_for_status()
            if response.status_code != 200 or "json" not in response.headers.get(
                "content-type", ""
            ).lower():
                raise ValueError(f"JSON以外の応答。SPAフォールバック等を保存しない: {url}")
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("JSONオブジェクトではない")
            return response, data
        raise RuntimeError("再試行上限")


def inventory(reader: Reader, run: CollectionRun, year: int, phase: str) -> dict:
    rows = {}
    page = 1
    expected = None
    while True:
        # next URLは直接追わない。同一ホスト・年度を固定してページ番号を構築。
        url = f"{BASE}?fiscal_year={year}&page_size=1000&page={page}"
        response, data = reader.get(url)
        count = data.get("count")
        if type(count) is not int or count < 0 or not isinstance(data.get("results"), list):
            raise ValueError("一覧形式不一致")
        if expected is not None and expected != count:
            raise ValueError("走査中に件数が変化")
        expected = count
        for row in data["results"]:
            uid = str(UUID(row["id"]))
            if uid in rows or row.get("fiscal_year") != year or row.get("is_published") is not True:
                raise ValueError("重複ID・年度不一致・非公開行")
            rows[uid] = row.get("updated_at")
        run.store(f"{phase}-page-{page}", url, response.content,
                  response.headers.get("content-type", ""))
        if data.get("next") is None:
            if len(rows) != expected:
                raise ValueError("一覧件数と一意ID数が不一致")
            return rows
        if not data["results"] or len(rows) >= expected:
            raise ValueError("一覧ページが進まない")
        page += 1


def collect(year: int, root: Path, run_id: str, limit: int | None = None,
            client: httpx.Client | None = None, interval: float = 2) -> dict:
    if not 2000 <= year <= 2100 or (limit is not None and limit < 1):
        raise ValueError("年度または件数上限が不正")
    run = CollectionRun(root, "rs-project-details", run_id, {"fiscal_year": year})
    owned = client is None
    client = client or httpx.Client(timeout=60, follow_redirects=False,
                                    headers={"User-Agent": "JGKG public-data collector"})
    try:
        with run.locked():
            run.state["source_id"] = "rs-system-api-details"
            contract_hash = hashlib.sha256(REGISTRY_PATH.read_bytes()).hexdigest()
            if run.state.get("contract_sha256", contract_hash) != contract_hash:
                raise ValueError("収集契約が変わったため新しいrun_idで取得する")
            run.state["contract_sha256"] = contract_hash
            run.state.update(fetched_count=0, discovery_complete=False)
            reader = Reader(client, interval)
            initial = inventory(reader, run, year, "start")
            run.state.update(discovery_complete=True, expected_count=len(initial))
            run.save()
            fetched = 0
            for uid, updated in initial.items():
                if limit is not None and fetched >= limit:
                    break
                key = f"detail-{uid}"
                raw = run.cached(key)
                record = run.state["snapshots"].get(key, {})
                # 更新日時がないときは毎回取得。null==nullを鮮度確認にしない。
                if raw is None or updated is None or record.get("list_updated_at") != updated:
                    response, data = reader.get(f"{BASE}{uid}/")
                    raw = response.content
                else:
                    response = None
                    data = json.loads(raw)
                if (data.get("id") != uid or data.get("fiscal_year") != year
                        or data.get("is_published") is not True):
                    raise ValueError(f"詳細のID・年度・公開状態不一致: {uid}")
                if response is not None:
                    run.store(key, str(response.url), raw,
                              response.headers.get("content-type", ""))
                    run.state["snapshots"][key]["list_updated_at"] = updated
                fetched += 1
                run.state.update(fetched_count=fetched, checkpoint=uid)
                run.save()
            final = inventory(reader, run, year, "end")
            stable = initial == final
            run.finish(stable and fetched == len(initial), fetched_count=fetched,
                       expected_count=len(initial), inventory_stable=stable,
                       graph_validated=False)
            return run.state
    finally:
        if owned:
            client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--run-id", default=None, help="同じIDを指定して再開")
    parser.add_argument("--limit", type=int, help="標本確認用。全件未取得ならpartial")
    parser.add_argument("--root", type=Path, default=Path("data/collection-runs"))
    args = parser.parse_args()
    run_id = args.run_id or uuid4().hex
    print(f"run_id={run_id}", flush=True)
    state = collect(args.year, args.root, run_id, args.limit)
    print(json.dumps({key: state[key] for key in
                      ("status", "expected_count", "fetched_count", "inventory_stable")},
                     ensure_ascii=False))
    return 0 if state["status"] == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
