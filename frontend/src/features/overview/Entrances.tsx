// トップページ再設計・第6節「入口」。
//
// 「つながりを辿る」への導線。代表的な3つのエンティティ(厚生労働省・
// こども家庭庁・三菱重工業)をカードで出し、加えて「データとAPI」
// (`#/data`)と「聞く」(`#/chat`)への導線を出す。
//
// **`id_path`は手で組み立てず、既知の3件だけを定数として持つ。** この
// 3件はブリーフで指定された代表例であり、`/overview`の応答には無い
// (`/overview`は府省の一覧しか持たず、こども家庭庁以外の個別法人は
// 出てこない)——エンティティ自体の存在は`entity/{id_path}`が404で
// 判定するので、リンク先が無ければエンティティ画面が正直にそう言う。
import type { JSX } from "react";
import { navigate, routeToHash } from "../../router";

interface EntranceCard {
  readonly idPath: string;
  readonly name: string;
  readonly hint: string;
}

const CARDS: readonly EntranceCard[] = [
  { idPath: "org/6000012070001", name: "厚生労働省", hint: "予算額が最大の府省。年金・医療・介護・雇用の事業がここに集まっています。" },
  { idPath: "org/7000012010039", name: "こども家庭庁", hint: "2023年度に新設された府省。子育て・児童福祉の事業を所管します。" },
  { idPath: "org/8010401050387", name: "三菱重工業", hint: "防衛関連の事業の支払先として現れる法人の1つです。" },
];

export function Entrances(): JSX.Element {
  return (
    <div className="jg-stack jg-stack--5">
      <div className="jg-grid jg-grid--3">
        {CARDS.map((card) => (
          <button
            type="button"
            key={card.idPath}
            className="jg-card jg-entrance-card"
            onClick={() => navigate({ name: "entity", idPath: card.idPath })}
          >
            <span className="jg-entrance-card__name jg-h3">{card.name}</span>
            <span className="jg-sm jg-ink2">{card.hint}</span>
            <span className="jg-sm jg-entrance-card__cta">つながりを見る →</span>
          </button>
        ))}
      </div>
      <div className="jg-row">
        <a
          className="jg-btn"
          href={routeToHash({ name: "data" })}
          onClick={(e) => {
            e.preventDefault();
            navigate({ name: "data" });
          }}
        >
          データとAPI
        </a>
        <a
          className="jg-btn jg-btn--primary"
          href={routeToHash({ name: "chat" })}
          onClick={(e) => {
            e.preventDefault();
            navigate({ name: "chat" });
          }}
        >
          聞く(チャット)
        </a>
      </div>
    </div>
  );
}
