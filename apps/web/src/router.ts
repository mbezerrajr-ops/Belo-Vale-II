import { useCallback, useEffect, useState } from "react";

/**
 * Endereço de cada tela, sem biblioteca: é pouca coisa, e cada dependência a
 * mais é código de terceiro rodando com o token de quem entrou.
 *
 * Sem endereço, a área vivia só na memória: recarregar voltava ao Painel, o
 * gesto de voltar do Android fechava o app aberto pela tela inicial, e não
 * havia como mandar a ficha de uma vaca para outra pessoa.
 */

export type AreaRoute =
  | "painel"
  | "producao"
  | "revisao"
  | "animais"
  | "insumos"
  | "medicoes"
  | "relatorios"
  | "contas"
  | "minha-conta";

export interface Route {
  /** `null`: o endereço não diz (raiz ou desconhecido) — vale a área inicial. */
  area: AreaRoute | null;
  /** Ficha aberta dentro de Animais. */
  animalId: string | null;
}

const AREAS: readonly AreaRoute[] = [
  "painel",
  "producao",
  "revisao",
  "animais",
  "insumos",
  "medicoes",
  "relatorios",
  "contas",
  "minha-conta",
];

/** Só identificadores com cara de UUID: o endereço vem de fora do app. */
const ANIMAL_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function parseRoute(pathname: string): Route {
  const parts = pathname.split("/").filter(Boolean);
  const area = AREAS.find((name) => name === parts[0]) ?? null;
  if (area === null) return { area: null, animalId: null };
  if (area === "animais" && parts.length === 2 && ANIMAL_ID.test(parts[1])) {
    return { area, animalId: parts[1].toLowerCase() };
  }
  // "/producao/qualquer-coisa" é a área, sem o resto.
  return { area, animalId: null };
}

export function formatRoute(route: Route): string {
  if (route.area === null) return "/";
  if (route.area === "animais" && route.animalId) return `/animais/${route.animalId}`;
  return `/${route.area}`;
}

export interface Navigation {
  route: Route;
  /** Vai para a tela e deixa a anterior no histórico (o "voltar" volta). */
  navigate: (route: Route) => void;
  /** Corrige o endereço sem criar entrada nova (área proibida, raiz). */
  replace: (route: Route) => void;
}

function current(): Route {
  return parseRoute(window.location.pathname);
}

export function useRoute(): Navigation {
  const [route, setRoute] = useState<Route>(current);

  useEffect(() => {
    const onPop = (): void => setRoute(current());
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = useCallback((next: Route): void => {
    const path = formatRoute(next);
    if (path !== window.location.pathname) {
      // "inApp": esta entrada foi aberta de dentro do app, então voltar
      // (pelo botão da tela) cai numa tela do próprio app.
      window.history.pushState({ inApp: true }, "", path);
      // Tela nova começa do topo; voltar deixa o navegador devolver a
      // rolagem de onde a pessoa estava.
      window.scrollTo(0, 0);
    }
    setRoute(parseRoute(path));
  }, []);

  const replace = useCallback((next: Route): void => {
    const path = formatRoute(next);
    if (path !== window.location.pathname) window.history.replaceState(null, "", path);
    setRoute(parseRoute(path));
  }, []);

  return { route, navigate, replace };
}
