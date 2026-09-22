import { useEffect, type RefObject } from "react";

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])';

/**
 * Painel que abre sobre a tela (Mais, Mais ações, Guardados): ao abrir, o
 * foco entra nele; Esc fecha e devolve o foco ao botão que abriu.
 *
 * Sem isto, quem usa teclado ou leitor de tela abria o painel e continuava
 * no botão, sem saber que havia algo novo na tela — e fechar deixava o foco
 * no nada, recomeçando do topo da página.
 */
export function usePanelFocus(
  open: boolean,
  panel: RefObject<HTMLElement>,
  trigger: RefObject<HTMLElement>,
  close: () => void,
  /** "panel": foca o próprio painel (diálogo com ação destrutiva dentro). */
  initial: "first" | "panel" = "first",
): void {
  useEffect(() => {
    if (!open) return;
    const first =
      initial === "panel"
        ? panel.current
        : (panel.current?.querySelector<HTMLElement>(FOCUSABLE) ?? panel.current);
    first?.focus({ preventScroll: true });
    const onKey = (event: KeyboardEvent): void => {
      if (event.key !== "Escape") return;
      close();
      trigger.current?.focus({ preventScroll: true });
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // `close` muda a cada desenho; o que importa é abrir e fechar.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);
}

/** Fechar pelo fundo escurecido também devolve o foco a quem abriu. */
export function closeAndReturn(close: () => void, trigger: RefObject<HTMLElement>): void {
  close();
  trigger.current?.focus({ preventScroll: true });
}
