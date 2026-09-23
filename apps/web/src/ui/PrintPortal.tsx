import type { ReactNode } from "react";
import { createPortal } from "react-dom";

/**
 * Põe o que vai para o papel direto no `<body>`, fora do app.
 *
 * Na impressão o app inteiro sai com `display: none` (app.css). Antes ele só
 * ficava invisível, mas continuava ocupando a altura da tela, e o navegador
 * imprimia essa altura como páginas em branco depois da folha.
 */
export function PrintPortal({ children }: { children: ReactNode }): JSX.Element {
  return createPortal(children, document.body);
}
