import "./style.css";
import { onRouteChange } from "./router";
import { renderEntity } from "./views/entity";
import type { EntityViewController } from "./views/entity";
import { renderPath } from "./views/path";
import { renderSearch } from "./views/search";

const app = document.querySelector<HTMLElement>("#app");
if (!app) {
  throw new Error("#app が見つからない(frontend/index.htmlの構造が変わった可能性)");
}

// エンティティ画面はSigma(WebGL)を持つので、離脱時に明示的に破棄する
// (持たない画面はinnerHTMLの入れ替えだけで十分)。
let currentEntityController: EntityViewController | undefined;

onRouteChange((route) => {
  currentEntityController?.destroy();
  currentEntityController = undefined;

  switch (route.name) {
    case "search":
      renderSearch(app, route.q);
      break;
    case "entity":
      currentEntityController = renderEntity(app, route.idPath);
      break;
    case "path":
      renderPath(app, route.from, route.to);
      break;
  }
});
