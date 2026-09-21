import { useState, type FormEvent } from "react";

import { reprocessImport, uploadImport } from "../../api/client";
import { ApiError, type UploadResult } from "../../api/types";
import { uploadErrorMessage } from "./uploadErrors";

/**
 * Enviar a foto da folha ou a gravação da ordenha pela própria Revisão, que é
 * onde o resultado aparece.
 *
 * A leitura é assíncrona de propósito: o envio responde na hora e o modelo lê
 * (ou ouve) depois, em segundo plano. Por isso a tela nunca fica travada
 * esperando — ela diz que está trabalhando, e as propostas aparecem quando
 * ficarem prontas.
 *
 * Foto e gravação fazem o mesmo caminho, então é um formulário só; o que
 * muda são os textos e o que o campo de arquivo abre no celular (câmera ou
 * gravador).
 */

export type UploadFn = (
  input: { farmId: string; file: File; declaredLot?: string },
  token: string,
) => Promise<UploadResult>;
export type ReprocessFn = (importId: string, token: string) => Promise<UploadResult>;

export interface Variant {
  arquivo: "foto" | "gravação";
  id: string;
  abrir: string;
  titulo: string;
  rotulo: string;
  accept: string;
  capture: "environment" | "user";
  /** O lote só faz sentido na folha: na fala ele é dito vaca a vaca. */
  comLote: boolean;
  trabalhando: string;
  repetido: string;
  aindaTrabalhando: string;
  deNovo: string;
  dica?: string;
}

export interface SendUploadProps {
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
  | { status: "working" }
  | { status: "duplicate"; importId: string; notice?: string }
  | { status: "error"; message: string };

export function SendUpload({
  variant,
  token,
  farmId,
  onUpload = uploadImport,
  onReprocess = reprocessImport,
  onSent,
}: SendUploadProps & { variant: Variant }): JSX.Element {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [lote, setLote] = useState("");
  const [state, setState] = useState<State>({ status: "idle" });

  async function send(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (file === null) return;
    setState({ status: "sending" });
    try {
      await onUpload(
        { farmId, file, declaredLot: variant.comLote && lote ? lote : undefined },
        token,
      );
      // Fecha o formulário: o aviso fica visível e o botão volta a ficar
      // livre para o próximo arquivo.
      setState({ status: "working" });
      setFile(null);
      setOpen(false);
      onSent?.();
    } catch (error) {
      // O mesmo arquivo já está guardado: em vez de criar outra cópia, o
      // caminho certo é mandar ler de novo aquele.
      if (error instanceof ApiError && error.code === "duplicate_image") {
        setState({ status: "duplicate", importId: String(error.body.existing_import_id ?? "") });
        return;
      }
      setState({ status: "error", message: uploadErrorMessage(error, variant.arquivo) });
    }
  }

  async function readAgain(importId: string): Promise<void> {
    setState({ status: "sending" });
    try {
      await onReprocess(importId, token);
      setState({ status: "working" });
      setFile(null);
      setOpen(false);
      onSent?.();
    } catch (error) {
      if (error instanceof ApiError && error.code === "import_already_processing") {
        setState({ status: "duplicate", importId, notice: variant.aindaTrabalhando });
        return;
      }
      setState({ status: "error", message: "Não foi possível mandar ler de novo." });
    }
  }

  if (!open) {
    return (
      <div className={`send-photo send-${variant.id}`}>
        <button type="button" onClick={() => setOpen(true)}>
          {variant.abrir}
        </button>
        {state.status === "working" && <p className="hint">{variant.trabalhando}</p>}
      </div>
    );
  }

  return (
    <form className={`send-photo send-${variant.id}`} onSubmit={(event) => void send(event)}>
      <h3>{variant.titulo}</h3>
      <label htmlFor={variant.id}>{variant.rotulo}</label>
      <input
        id={variant.id}
        type="file"
        accept={variant.accept}
        // No celular, abre direto a câmera (foto) ou o gravador (áudio).
        capture={variant.capture}
        onChange={(event) => setFile(event.target.files?.[0] ?? null)}
      />
      {variant.dica && <p className="hint">{variant.dica}</p>}
      {variant.comLote && (
        <>
          <label htmlFor={`${variant.id}-lote`}>Lote (opcional)</label>
          <input
            id={`${variant.id}-lote`}
            value={lote}
            onChange={(event) => setLote(event.target.value)}
            placeholder="Ex.: LOTE 3"
            autoComplete="off"
          />
        </>
      )}

      <div className="send-photo-actions">
        <button type="submit" disabled={file === null || state.status === "sending"}>
          Enviar
        </button>
        <button type="button" className="link-btn" onClick={() => setOpen(false)}>
          Cancelar
        </button>
      </div>

      {state.status === "working" && <p className="hint">{variant.trabalhando}</p>}
      {state.status === "duplicate" && (
        <div className="hint">
          <p>{variant.repetido}</p>
          {state.notice && <p>{state.notice}</p>}
          <button type="button" onClick={() => void readAgain(state.importId)}>
            {variant.deNovo}
          </button>
        </div>
      )}
      {state.status === "error" && <p role="alert">{state.message}</p>}
    </form>
  );
}
