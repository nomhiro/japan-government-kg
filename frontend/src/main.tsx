import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles/tokens.css";
import "./style.css";
import { App } from "./app/App";

const app = document.querySelector<HTMLElement>("#app");
if (!app) {
  throw new Error("#app が見つからない(frontend/index.htmlの構造が変わった可能性)");
}

createRoot(app).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
