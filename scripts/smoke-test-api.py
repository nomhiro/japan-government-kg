"""自己完結イメージ2本(serve-fuseki・serve-api)を実HTTP面から確認する(D-6b-1)。

**「起動した」で終わらせない。** `scripts/measure-cold-read.py`の
`VacuousMeasurement`(0件を測ったら例外にする)と同じ考え方を、
APIの5エンドポイントに適用する——200が返ることではなく、**返ってきた
本文が実データを持つこと**をアサートする。

対象(task-D6b1-brief.md #5):
  - `GET /entity/{id}` が実データを返す(属性・出典グラフが実際にある)
  - `GET /entity/org/abolished/<厚生省>`(パーセントエンコードが必要なID。
    裁定B69・B73の対象)が引ける——この経路を外すと裁定B69が素通りする
  - `GET /search`・`/neighborhood/{id}`・`/path?from=&to=` も1本ずつ

エンティティIDは手書きしない選択肢が無い(検索語や既知の実在IDを起点に
するしかない)が、**「見つかった」ことに依存する部分は自分で検索して
選ぶ**——固定のIDは`org/4000012090001`(法令のjurisdiction先。
docs/measurements-phase1.md記載の実在IRI)と`law/429M60000442003`
(同じ資料が同じ法人を指すと記録している法令)の2つだけで、いずれも
このプロジェクトの記録済み資料が実在を示している値であり、controllerが
今回実測した数字(属性件数等)を転記したものではない。
"""
from __future__ import annotations

import argparse
import sys

import httpx

ABOLISHED_MINISTRY = "厚生省"


class VacuousResponse(RuntimeError):
    """200は返ったが、本文に実データが無い。「動いた」ではなく「何も返していない」。"""


def _get(client: httpx.Client, path: str, **params) -> dict:
    r = client.get(path, params=params or None)
    if r.status_code != 200:
        raise VacuousResponse(f"{path} -> HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def check_entity_detail(client: httpx.Client, id_path: str) -> None:
    body = _get(client, f"/entity/{id_path}")
    n_attrs = sum(len(v) for v in body["attributes"].values())
    n_graphs = len(body["graphs"])
    print(f"  GET /entity/{id_path} -> id={body['id']}")
    print(f"    属性値 {n_attrs} 件({len(body['attributes'])} 述語) / 出典グラフ {n_graphs} 件")
    if n_attrs == 0 or n_graphs == 0:
        raise VacuousResponse(
            f"/entity/{id_path} は200だが属性or出典グラフが0件。実データを返していない"
        )


def check_search(client: httpx.Client, q: str) -> None:
    body = _get(client, "/search", q=q, limit=5)
    print(f"  GET /search?q={q} -> {len(body['results'])} 件(truncated={body['truncated']})")
    if not body["results"]:
        raise VacuousResponse(f"/search?q={q} が0件。実データに当たっていない")


def check_neighborhood(client: httpx.Client, id_path: str) -> None:
    body = _get(client, f"/neighborhood/{id_path}", depth=1)
    print(
        f"  GET /neighborhood/{id_path} -> ノード {len(body['nodes'])} 件 / "
        f"エッジ {len(body['edges'])} 件"
    )
    if not body["nodes"]:
        raise VacuousResponse(f"/neighborhood/{id_path} がノード0件。実データに当たっていない")


def check_path(client: httpx.Client, from_id: str, to_id: str) -> None:
    body = _get(client, "/path", **{"from": from_id, "to": to_id})
    print(
        f"  GET /path?from={from_id}&to={to_id} -> found={body['found']} "
        f"visited={body['visited']} nodes={len(body['nodes'])}"
    )
    if not body["found"]:
        raise VacuousResponse(
            f"/path?from={from_id}&to={to_id} が found=false。"
            " 既知のjurisdiction関係が繋がっていない(実データに当たっていない疑い)"
        )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://localhost:8055")
    ap.add_argument("--entity-id", default="org/4000012090001")
    ap.add_argument("--law-id", default="law/429M60000442003")
    args = ap.parse_args(argv)

    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        print(f"=== 対象: {args.base_url} ===")

        print("\n-- 1. GET /entity/{id}(実データ) --")
        check_entity_detail(client, args.entity_id)

        print("\n-- 2. GET /entity/org/abolished/<厚生省>(パーセントエンコードが必要なID。裁定B69・B73) --")
        check_entity_detail(client, f"org/abolished/{ABOLISHED_MINISTRY}")

        print("\n-- 3. GET /search --")
        check_search(client, "省")

        print("\n-- 4. GET /neighborhood/{id} --")
        check_neighborhood(client, args.entity_id)

        print("\n-- 5. GET /path?from=&to= --")
        check_path(client, args.law_id, args.entity_id)

    print("\n全5経路、実データで確認できた。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except VacuousResponse as exc:
        print(f"\n!! 空虚な応答: {exc}", file=sys.stderr)
        sys.exit(1)
