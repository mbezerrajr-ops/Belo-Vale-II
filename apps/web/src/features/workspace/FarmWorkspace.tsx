import { useEffect, useState, type ReactNode } from "react";
import { listFarms, setActiveFarmId } from "../../api/client";
import { ApiError, type Farm, type CurrentUser } from "../../api/types";
import { apiMessage } from "../../auth/AccountEntry";
import { setFarmTimezone } from "../../ui/dates";

interface Props {
  token: string;
  user: CurrentUser;
  onLogout: () => void;
  children: (user: CurrentUser, farmKey: string, farm: Farm) => ReactNode;
}

/** Resolve a única fazenda da pessoa, sem acrescentar controles à navegação. */
export function FarmWorkspace({ token, user, onLogout, children }: Props): JSX.Element {
  const [farm, setFarm] = useState<Farm | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const cacheKey = `belo-vale.workspaces:${user.id}`;

  useEffect(() => {
    let cancelled = false;
    setActiveFarmId(null);
    const display = (items: Farm[]): void => {
      if (items.length !== 1) {
        throw new Error(items.length === 0
          ? "Sua conta está sem acesso a uma fazenda. Fale com o administrador."
          : "Sua conta precisa estar vinculada a uma única fazenda. Fale com o administrador.");
      }
      if (cancelled) return;
      setActiveFarmId(items[0].id);
      setFarmTimezone(items[0].timezone ?? "America/Recife");
      setFarm(items[0]);
      setError(null);
    };
    void listFarms(token).then((items) => {
      display(items);
      if (!cancelled) {
        try { localStorage.setItem(cacheKey, JSON.stringify(items)); } catch { /* A fila informa falhas ao guardar lançamentos. */ }
      }
    }).catch((caught) => {
      if (cancelled) return;
      // Somente indisponibilidade da rede/servidor permite retomar a cópia local.
      const networkFailure = caught instanceof TypeError || (caught instanceof ApiError && caught.status >= 500);
      if (networkFailure) {
        try {
          const cached = JSON.parse(localStorage.getItem(cacheKey) ?? "null");
          if (Array.isArray(cached) && cached.length === 1) { display(cached); return; }
        } catch { /* Não há uma fazenda local utilizável. */ }
      }
      setFarm(null);
      setActiveFarmId(null);
      setError(caught instanceof Error && !(caught instanceof ApiError) && !networkFailure ? caught.message : apiMessage(caught));
    }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [token, user.id]);

  if (loading) return <main className="shell"><p role="status">Carregando sua fazenda…</p><button onClick={onLogout}>Cancelar carregamento</button></main>;
  if (!farm) return <main className="shell"><p role="alert">{error}</p><button onClick={onLogout}>Voltar para entrar</button></main>;
  return <>
    <a className="skip-link" href="#conteudo">Pular para o conteúdo</a>
    {children({ ...user, role: farm.role ?? user.role }, `${user.id}:${farm.id}`, farm)}
  </>;
}
