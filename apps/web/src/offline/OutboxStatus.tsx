import { useRef, useState } from "react";

import { Icons } from "../ui/Brand";
import { closeAndReturn, usePanelFocus } from "../ui/usePanelFocus";
import { brDate } from "../ui/dates";
import type { OutboxItem } from "./outbox";
import { useOutbox } from "./OutboxContext";

function liters(value: number): string {
  return value.toLocaleString("pt-BR", { maximumFractionDigits: 1 });
}

function describe(item: OutboxItem): string {
  if (item.kind === "reading") {
    return `${item.label} · ${liters(item.producao)} L · ${brDate(item.measuredOn)}`;
  }
  const when = new Date(item.createdAt).toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
  return `${item.arquivo === "foto" ? "Foto da folha" : "Gravação da ordenha"} · ${when}`;
}

/** Faixa sob o topo: sem sinal, e o aviso do que acabou de ser enviado. */
export function OfflineBanner(): JSX.Element | null {
  const queue = useOutbox();
  if (queue === null) return null;
  if (!queue.online) {
    return (
      <p className="offline-banner" role="status">
        <Icons.semSinal />
        Sem sinal. Produção, fotos e áudios enviados ficam guardados neste aparelho. Ao recuperar a conexão, mantenha o aplicativo aberto ou abra novamente para enviar.
      </p>
    );
  }
  if (queue.notice) {
    return (
      <p className="offline-banner is-sent" role="status">
        {queue.notice}
      </p>
    );
  }
  return null;
}

/** Contador no topo e a lista do que espera envio. */
export function OutboxButton(): JSX.Element | null {
  const queue = useOutbox();
  const [open, setOpen] = useState(false);
  const panel = useRef<HTMLDivElement>(null);
  const chip = useRef<HTMLButtonElement>(null);
  usePanelFocus(open, panel, chip, () => setOpen(false), "panel");

  if (queue === null || queue.pending.length === 0) return null;
  const refused = queue.pending.filter((item) => item.error).length;
  const count = queue.pending.length;

  return (
    <>
      <button
        type="button"
        ref={chip}
        className={refused > 0 ? "outbox-chip has-refused" : "outbox-chip"}
        aria-expanded={open}
        aria-controls="guardados"
        onClick={() => setOpen((current) => !current)}
      >
        <Icons.guardado />
        <span>
          {count} {count === 1 ? "guardado" : "guardados"}
        </span>
      </button>
      {open && (
        <>
          <div
            className="more-backdrop"
            aria-hidden="true"
            onClick={() => closeAndReturn(() => setOpen(false), chip)}
          />
          <div
            className="outbox-panel"
            id="guardados"
            role="dialog"
            aria-label="Guardados neste aparelho"
            tabIndex={-1}
            ref={panel}
          >
            <h3>Guardados neste aparelho</h3>
            <p className="hint">
              {queue.online
                ? "Aguardando envio. Mantenha o aplicativo aberto ou toque em Enviar agora."
                : "Sem sinal. Ao recuperar a conexão, abra o aplicativo para enviar o que ficou guardado."}
            </p>
            <p className="hint">Guardado aqui ainda não significa recebido pelo servidor. Após o envio, fotos e áudios precisam de leitura e conferência.</p>
            <ul>
              {queue.pending.map((item) => (
                <li key={item.id} className={item.error ? "is-refused" : undefined}>
                  <span>{describe(item)}</span>
                  {item.error ? (
                    <>
                      <small>Não enviado: {item.error}</small>
                      <button type="button" className="secondary" onClick={() => {
                        void queue.outbox.retry(item.id, queue.userId).then(queue.flushNow);
                      }}>Tentar enviar novamente</button>
                      <button
                        type="button"
                        className="secondary danger"
                        onClick={() => {
                          if (window.confirm(`Descartar "${describe(item)}"? Não dá para desfazer.`)) {
                            void queue.outbox.discard(item.id);
                          }
                        }}
                      >
                        Descartar
                      </button>
                    </>
                  ) : (
                    <small>{queue.online ? "Aguardando envio" : "Aguardando conexão"}</small>
                  )}
                </li>
              ))}
            </ul>
            <div className="row-fix-actions">
              <button type="button" onClick={queue.flushNow} disabled={count === refused}>
                <Icons.atualizar /> Enviar agora
              </button>
              <button type="button" className="secondary" onClick={() => closeAndReturn(() => setOpen(false), chip)}>
                Fechar
              </button>
            </div>
          </div>
        </>
      )}
    </>
  );
}
