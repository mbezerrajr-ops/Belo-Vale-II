import { useState, type FormEvent } from "react";

import { reprocessImport, uploadImport } from "../../api/client";
import { ApiError, type UploadResult } from "../../api/types";

interface UploadFormProps {
  token: string;
  /** Resolvida no servidor por quem renderiza; o usuário nunca digita isto. */
  farmId: string;
  onUploaded?: (result: UploadResult) => void;
}

type UploadState =
  | { status: "idle" }
  | { status: "uploading" }
  | { status: "queued"; result: UploadResult }
  | { status: "duplicate"; notice?: string }
  | { status: "reprocessing" }
  | { status: "error"; message: string };

export function UploadForm({ token, farmId, onUploaded }: UploadFormProps): JSX.Element {
  const [file, setFile] = useState<File | null>(null);
  const [declaredLot, setDeclaredLot] = useState("");
  const [declaredPeriod, setDeclaredPeriod] = useState("");
  const [state, setState] = useState<UploadState>({ status: "idle" });
  const [duplicateOfImportId, setDuplicateOfImportId] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    if (file === null) {
      return;
    }

    setState({ status: "uploading" });
    try {
      const result = await uploadImport(
        { farmId, file, declaredLot: declaredLot || undefined, declaredPeriod: declaredPeriod || undefined },
        token,
      );
      setState({ status: "queued", result });
      onUploaded?.(result);
    } catch (error) {
      if (error instanceof ApiError && error.code === "duplicate_image") {
        setDuplicateOfImportId(String(error.body.existing_import_id ?? ""));
        setState({ status: "duplicate" });
        return;
      }
      setState({ status: "error", message: "Não foi possível enviar a foto. Tente novamente." });
    }
  };

  const handleReprocess = async (): Promise<void> => {
    if (duplicateOfImportId === null) {
      return;
    }
    setState({ status: "reprocessing" });
    try {
      const result = await reprocessImport(duplicateOfImportId, token);
      setState({ status: "queued", result });
      onUploaded?.(result);
    } catch (error) {
      // A leitura da primeira foto ainda está rodando: a API recusa, com
      // razão, reprocessar no meio. O aviso e o botão continuam na tela.
      if (error instanceof ApiError && error.code === "import_already_processing") {
        setState({
          status: "duplicate",
          notice: "A leitura desta foto ainda está em andamento. Aguarde alguns segundos e tente de novo.",
        });
        return;
      }
      setState({ status: "error", message: "Não foi possível reprocessar a importação existente." });
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <h3>Enviar ficha</h3>
      <label htmlFor="upload-lot">Lote declarado</label>
      <input
        id="upload-lot"
        value={declaredLot}
        onChange={(event) => setDeclaredLot(event.target.value)}
        autoComplete="off"
      />
      <label htmlFor="upload-period">Data declarada</label>
      <input
        id="upload-period"
        value={declaredPeriod}
        onChange={(event) => setDeclaredPeriod(event.target.value)}
        placeholder="dd/mm/aaaa"
        inputMode="numeric"
        autoComplete="off"
      />
      <label htmlFor="upload-file">Foto da ficha</label>
      <input
        id="upload-file"
        type="file"
        accept="image/jpeg,image/png,image/heic"
        onChange={(event) => setFile(event.target.files?.[0] ?? null)}
      />
      {/* Sem `required`: alguns ambientes (jsdom incluído) tratam um input de
          arquivo preenchido como inválido, bloqueando o submit nativo. A
          guarda em handleSubmit faz esse papel. */}
      <p className="hint">
        {file ? `Selecionada: ${file.name}` : "JPEG, PNG ou HEIC, até 15 MB."}
      </p>
      <button type="submit" disabled={state.status === "uploading"}>
        {state.status === "uploading" ? "Enviando…" : "Enviar foto"}
      </button>

      {state.status === "queued" ? (
        <p role="status">Importação enviada: {state.result.status}</p>
      ) : null}
      {state.status === "error" ? <p role="alert">{state.message}</p> : null}
      {state.status !== "duplicate" && state.status !== "reprocessing" ? null : (
        <div role="alert" className="replacement-warning">
          <p>Esta foto já foi enviada anteriormente.</p>
          {state.status === "duplicate" && state.notice ? <p>{state.notice}</p> : null}
          <button
            type="button"
            className="btn-ghost"
            onClick={handleReprocess}
            disabled={state.status === "reprocessing"}
          >
            Reprocessar mesmo assim
          </button>
        </div>
      )}
    </form>
  );
}
