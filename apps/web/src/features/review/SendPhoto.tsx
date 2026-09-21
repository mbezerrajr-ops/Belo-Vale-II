import { useState, type FormEvent } from "react";

import { reprocessImport, uploadImport } from "../../api/client";
import { uploadErrorMessage } from "./uploadErrors";
import { ApiError, type UploadResult } from "../../api/types";

/**
 * Enviar a foto da folha pela própria Revisão, que é onde o resultado
 * aparece.
 *
 * A leitura é assíncrona de propósito: o envio responde na hora e o modelo lê
 * depois, em segundo plano. Por isso a tela nunca fica travada esperando — ela
 * diz que está lendo, e as propostas aparecem quando ficarem prontas.
 */

type UploadFn = (
  input: { farmId: string; file: File; declaredLot?: string },
  token: string,
) => Promise<UploadResult>;
type ReprocessFn = (importId: string, token: string) => Promise<UploadResult>;

interface Props {
  token: string;
  /** Resolvida no servidor por quem renderiza; ninguém digita isto. */
  farmId: string;
  onUpload?: UploadFn;
  onReprocess?: ReprocessFn;
  /** Avisa a caixa para reler a lista quando a leitura terminar. */
  onSent?: () => void;
}

type State =
  | { status: "idle" }
  | { status: "sending" }
  | { status: "reading" }
  | { status: "duplicate"; importId: string; notice?: string }
  | { status: "error"; message: string };

export function SendPhoto({
  token,
  farmId,
  onUpload = uploadImport,
  onReprocess = reprocessImport,
  onSent,
}: Props): JSX.Element {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [lote, setLote] = useState("");
  const [state, setState] = useState<State>({ status: "idle" });

  async function send(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (file === null) return;
    setState({ status: "sending" });
    try {
      await onUpload({ farmId, file, declaredLot: lote || undefined }, token);
      // Fecha o formulário: o aviso de leitura fica visível e o botão volta a
      // ficar livre para a próxima folha.
      setState({ status: "reading" });
      setFile(null);
      setOpen(false);
      onSent?.();
    } catch (error) {
      // A mesma foto já está guardada: em vez de criar outra cópia, o
      // caminho certo é mandar ler de novo aquela.
      if (error instanceof ApiError && error.code === "duplicate_image") {
        setState({ status: "duplicate", importId: String(error.body.existing_import_id ?? "") });
        return;
      }
      setState({ status: "error", message: uploadErrorMessage(error, "foto") });
    }
  }

  async function readAgain(importId: string): Promise<void> {
    setState({ status: "sending" });
    try {
      await onReprocess(importId, token);
      setState({ status: "reading" });
      setFile(null);
      setOpen(false);
      onSent?.();
    } catch (error) {
      if (error instanceof ApiError && error.code === "import_already_processing") {
        setState({
          status: "duplicate",
          importId,
          notice: "Esta foto ainda está sendo lida. Espere alguns segundos e tente de novo.",
        });
        return;
      }
      setState({ status: "error", message: "Não foi possível mandar ler de novo." });
    }
  }

  if (!open) {
    return (
      <div className="send-photo">
        <button type="button" onClick={() => setOpen(true)}>
          Enviar foto
        </button>
        {state.status === "reading" && (
          <p className="hint">Lendo a folha. As propostas aparecem aqui quando terminar.</p>
        )}
      </div>
    );
  }

  return (
    <form className="send-photo" onSubmit={(event) => void send(event)}>
      <h3>Enviar foto da folha</h3>
      <label htmlFor="foto-folha">Foto da folha</label>
      <input
        id="foto-folha"
        type="file"
        accept="image/*"
        // No celular, abre a câmera direto.
        capture="environment"
        onChange={(event) => setFile(event.target.files?.[0] ?? null)}
      />
      <label htmlFor="foto-lote">Lote (opcional)</label>
      <input
        id="foto-lote"
        value={lote}
        onChange={(event) => setLote(event.target.value)}
        placeholder="Ex.: LOTE 3"
        autoComplete="off"
      />

      <div className="send-photo-actions">
        <button type="submit" disabled={file === null || state.status === "sending"}>
          Enviar
        </button>
        <button type="button" className="link-btn" onClick={() => setOpen(false)}>
          Cancelar
        </button>
      </div>

      {state.status === "reading" && (
        <p className="hint">Lendo a folha. As propostas aparecem aqui quando terminar.</p>
      )}
      {state.status === "duplicate" && (
        <div className="hint">
          <p>Esta foto já foi enviada antes.</p>
          {state.notice && <p>{state.notice}</p>}
          <button type="button" onClick={() => void readAgain(state.importId)}>
            Ler de novo
          </button>
        </div>
      )}
      {state.status === "error" && <p role="alert">{state.message}</p>}
    </form>
  );
}
