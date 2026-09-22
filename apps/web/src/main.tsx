import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";

import "./app.css";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("root element not found");
}

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// Guarda o app para abrir sem sinal no curral. Só no build de produção: em
// desenvolvimento, uma página guardada esconderia a mudança que se acabou de
// fazer.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/sw.js", { updateViaCache: "none" }).catch(() => {
      // Sem service worker o app funciona igual; só não abre sem sinal.
    });
  });
}
