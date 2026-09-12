// ヘッダ帯: パンくず / 型バッジ / 大きな名前 / 型の要点1行 / 操作ボタン。
//
// **左右の余白を捨てて全幅の帯にする**(`Band`。裁定): 1440pxの画面で
// 60remの細い列に押し込めていた旧画面の問題を直す。
import { useState, type JSX } from "react";
import type { EntityDetailResponse, EntityRef } from "../../api/client";
import { Band, TypeBadge } from "../../components/ui";
import { typeLabel } from "../../labels";
import { navigate, routeToHash } from "../../router";
import { displayLabel, kindOneLiner, type EntityKind } from "./entity-model";

function scrollToGraph(): void {
  const el = document.getElementById("graph");
  if (el && typeof el.scrollIntoView === "function") {
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  }
}

export function EntityHeader({
  entity,
  idPath,
  kind,
  ministryRef,
}: {
  entity: EntityDetailResponse;
  idPath: string;
  kind: EntityKind;
  ministryRef: EntityRef | undefined;
}): JSX.Element {
  const [copied, setCopied] = useState(false);

  function copyUrl(): void {
    const clipboard = typeof navigator !== "undefined" ? navigator.clipboard : undefined;
    if (!clipboard?.writeText) return;
    clipboard.writeText(location.href).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      },
      () => {
        // クリップボードへの書き込みが拒否/失敗しても、画面を壊さない
        // (静かに何もしない。ボタンの表示は変わらない)。
      },
    );
  }

  return (
    <Band ruled>
      <nav aria-label="現在位置" className="jg-row jg-row--tight jg-xs jg-muted entity-breadcrumb">
        <a
          href={routeToHash({ name: "top" })}
          onClick={(e) => {
            e.preventDefault();
            navigate({ name: "top" });
          }}
        >
          全体を見る
        </a>
        <span aria-hidden="true">›</span>
        {ministryRef ? (
          <>
            <a
              href={routeToHash({ name: "entity", idPath: ministryRef.id_path })}
              onClick={(e) => {
                e.preventDefault();
                navigate({ name: "entity", idPath: ministryRef.id_path });
              }}
            >
              {displayLabel(ministryRef)}
            </a>
            <span aria-hidden="true">›</span>
          </>
        ) : null}
        <span>{typeLabel(entity.type)}</span>
      </nav>

      <div className="jg-stack jg-stack--3 entity-header__body">
        <TypeBadge type={entity.type} />
        <h1 className="jg-h1">
          {displayLabel({ id: entity.id, id_path: entity.id_path, label: entity.label, type: entity.type })}
        </h1>
        <p className="jg-lead">{kindOneLiner(kind)}</p>
        <div className="jg-row jg-row--tight">
          <button type="button" className="jg-btn" onClick={scrollToGraph}>
            つながりをグラフで見る
          </button>
          <button
            type="button"
            className="jg-btn"
            onClick={() => navigate({ name: "path", from: idPath })}
          >
            経路の始点にする
          </button>
          <button type="button" className="jg-btn" onClick={() => navigate({ name: "chat" })}>
            この画面について聞く
          </button>
          <button type="button" className="jg-btn jg-btn--quiet" onClick={copyUrl}>
            {copied ? "コピーしました" : "URLをコピー"}
          </button>
        </div>
      </div>
    </Band>
  );
}
