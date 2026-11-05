import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { Outbox, type OutboxItem, type Senders } from "./outbox";

/**
 * A fila deste celular, para as telas que lançam (Produção, Revisão) e para o
 * aviso no topo. Também é quem envia: ao voltar o sinal, a cada meio minuto
 * enquanto houver algo guardado, e quando a pessoa pede.
 */

export interface OutboxState {
  outbox: Outbox;
  userId: string;
  pending: OutboxItem[];
  online: boolean;
  flushNow: () => void;
  /** Aviso curto depois de enviar o que estava guardado. */
  notice: string | null;
}

const Context = createContext<OutboxState | null>(null);

/** `null` fora do app (testes de uma tela só): sem fila, como antes. */
export function useOutbox(): OutboxState | null {
  return useContext(Context);
}

/** Enquanto houver algo guardado, tenta de novo a cada meio minuto. */
export const RETRY_MS = 30_000;

interface Props {
  outbox: Outbox;
  userId: string;
  farmId?: string;
  token: string;
  renew: () => Promise<string | null>;
  send: Senders;
  children: ReactNode;
}

function onlineNow(): boolean {
  return typeof navigator === "undefined" || navigator.onLine !== false;
}

export function OutboxProvider({ outbox, userId, farmId, token, renew, send, children }: Props): JSX.Element {
  const [pending, setPending] = useState<OutboxItem[]>([]);
  const [online, setOnline] = useState(onlineNow);
  const [notice, setNotice] = useState<string | null>(null);

  // O envio usa sempre o token da hora, não o do momento em que foi montado.
  const latest = useRef({ token, renew, send });
  latest.current = { token, renew, send };

  const refresh = useCallback(async () => {
    setPending((await outbox.list(userId)).filter((item) => !farmId || !item.farmId || item.farmId === farmId));
  }, [outbox, userId, farmId]);

  const flushNow = useCallback(() => {
    void outbox.flush({ userId, ...latest.current }).then(refresh);
  }, [outbox, userId, refresh]);

  useEffect(() => {
    let sent = 0;
    let timer: number | undefined;
    const unsubscribe = outbox.subscribe((event) => {
      if (event.type !== "changed" && (event.item.userId !== userId || (farmId && event.item.farmId && event.item.farmId !== farmId))) return;
      if (event.type === "changed") void refresh();
      if (event.type === "sent") {
        sent += 1;
        window.clearTimeout(timer);
        // Um aviso só para o lote inteiro, não um por vaca.
        timer = window.setTimeout(() => {
          setNotice(
            sent === 1
              ? "O que estava guardado no celular foi enviado."
              : `${sent} envios guardados no celular foram enviados.`,
          );
          sent = 0;
          window.setTimeout(() => setNotice(null), 6_000);
        }, 400);
      }
    });
    return () => {
      unsubscribe();
      window.clearTimeout(timer);
    };
  }, [outbox, refresh, userId, farmId]);

  // Ao abrir: manda o que ficou de antes (de outra visita, sem sinal).
  useEffect(() => {
    void refresh();
    flushNow();
  }, [refresh, flushNow]);

  useEffect(() => {
    const up = (): void => {
      setOnline(true);
      flushNow();
    };
    const down = (): void => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, [flushNow]);

  const waiting = pending.some((item) => !item.error);
  useEffect(() => {
    if (!waiting) return;
    const interval = window.setInterval(flushNow, RETRY_MS);
    return () => window.clearInterval(interval);
  }, [waiting, flushNow]);

  return (
    <Context.Provider value={{ outbox, userId, pending, online, flushNow, notice }}>
      {children}
    </Context.Provider>
  );
}
