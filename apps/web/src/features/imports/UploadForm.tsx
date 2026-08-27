import { useState, type FormEvent } from "react";

import { reprocessImport, uploadImport } from "../../api/client";
import { ApiError, type UploadResult } from "../../api/types";

interface UploadFormProps {
  token: string;
  onUploaded?: (result: UploadResult) => void;
}

type UploadState =
  | { status: "idle" }
  | { status: "uploading" }
  | { status: "queued"; result: UploadResult }
  | { status: "duplicate" }
  | { status: "reprocessing" }
  | { status: "error"; message: string };

export function UploadForm({ token, onUploaded }: UploadFormProps): JSX.Element {
  const [farmId, setFarmId] = useState("");
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
    } catch {
      setState({ status: "error", message: "Não foi possível reprocessar a importação existente." });
    }
  };

  return (
    <form onSubmit={handleSubmit}>
      <label>
        Fazenda
        <input
          value={farmId}
          onChange={(event) => setFarmId(event.target.value)}
          required
        />
      </label>
      <label>
        Lote declarado
        <input value={declaredLot} onChange={(event) => setDeclaredLot(event.target.value)} />
      </label>
      <label>
        Data declarada
        <input
          value={declaredPeriod}
          onChange={(event) => setDeclaredPeriod(event.target.value)}
          placeholder="dd/mm/aaaa"
        />
      </label>
      <label>
        Foto da ficha
        <input
          type="file"
          accept="image/jpeg,image/png,image/heic"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        {/* Not `required`: some environments (jsdom included) report a
            populated file input as constraint-invalid, blocking native
            submission. The JS guard in handleSubmit enforces this instead. */}
      </label>
      <button type="submit" disabled={state.status === "uploading"}>
        Enviar foto
      </button>

      {state.status === "queued" ? <p role="status">Importação enviada: {state.result.status}</p> : null}
      {state.status === "error" ? <p role="alert">{state.message}</p> : null}
      {state.status !== "duplicate" && state.status !== "reprocessing" ? null : (
        <div role="alert">
          <p>Esta foto já foi enviada anteriormente.</p>
          <button
            type="button"
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
