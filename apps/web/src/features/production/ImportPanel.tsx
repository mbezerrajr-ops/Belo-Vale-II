import { useEffect, useState } from "react";

import { commitImport, listImports, previewImport } from "../../api/client";
import {
  ApiError,
  type ImportMode,
  type ImportPreview,
  type ImportRecord,
  type ImportRowStatus,
} from "../../api/types";
import { brDate, liters, localToday } from "../../ui/dates";

/**
 * Importação da coleta por arquivo (CSV, XLSX ou PDF).
 *
 * Sempre em dois passos: a prévia mostra o que cada linha vai virar, e só a
 * confirmação grava. O servidor recalcula tudo na confirmação — o que foi
 * visto aqui é o que ele grava, sem aceitar nada pronto do navegador.
 *
 * Só o brinco associa uma linha a um animal. Substituir leituras já lançadas
 * é de revisor, com motivo; a vaca que não está no arquivo mantém a leitura.
 */

type PreviewFn = (token: string, file: File, measuredOn: string) => Promise<ImportPreview>;
type CommitFn = (
  token: string,
  file: File,
  measuredOn: string,
  mode: ImportMode,
  reason: string | null,
) => Promise<ImportRecord>;
type ListFn = (token: string) => Promise<ImportRecord[]>;

interface Props {
  token: string;
  /** Revisor e administrador podem substituir leituras já lançadas. */
  canReplace: boolean;
  today?: string;
  onPreview?: PreviewFn;
  onCommit?: CommitFn;
  onList?: ListFn;
  /** Chamado depois de uma importação que gravou algo. */
  onImported?: () => void;
}

const STATUS_LABEL: Record<ImportRowStatus, string> = {
  new: "Nova",
  same: "Já lançada (igual)",
  different: "Diferente do lançado",
  not_found: "Brinco não encontrado",
  no_brinco: "Sem brinco",
  invalid: "Fora do plausível",
  exited: "Animal com baixa",
  duplicate: "Repetida no arquivo",
};

/** Tom de cada situação: o que entra, o que é neutro, o que pede atenção. */
const STATUS_TONE: Record<ImportRowStatus, "good" | "neutral" | "warn" | "bad"> = {
  new: "good",
  same: "neutral",
  different: "warn",
  not_found: "bad",
  no_brinco: "bad",
  invalid: "bad",
  exited: "bad",
  duplicate: "bad",
};

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  if (error instanceof TypeError) return "Sem conexão. Tente de novo quando o sinal voltar.";
  return "Não foi possível completar a importação.";
}

function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

export function ImportPanel({
  token,
  canReplace,
  today = localToday(),
  onPreview = previewImport,
  onCommit = commitImport,
  onList = listImports,
  onImported,
}: Props): JSX.Element {
  const [day, setDay] = useState(today);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [mode, setMode] = useState<ImportMode>("new_only");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<ImportRecord | null>(null);
  const [history, setHistory] = useState<ImportRecord[]>([]);

  async function reloadHistory(): Promise<void> {
    try {
      setHistory(await onList(token));
    } catch {
      // O histórico é complementar: sem ele, a importação continua possível.
    }
  }

  useEffect(() => {
    void reloadHistory();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  function reset(): void {
    setPreview(null);
    setMode("new_only");
    setReason("");
    setError(null);
    setDone(null);
  }

  async function runPreview(): Promise<void> {
    if (file === null) return;
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      setPreview(await onPreview(token, file, day));
    } catch (caught) {
      setPreview(null);
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function runCommit(): Promise<void> {
    if (file === null || preview === null) return;
    setBusy(true);
    setError(null);
    try {
      const result = await onCommit(
        token,
        file,
        day,
        mode,
        mode === "replace" ? reason.trim() : null,
      );
      setDone(result);
      setPreview(null);
      if (!result.already_imported) onImported?.();
      await reloadHistory();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  const counts = preview?.counts;
  const toCreate = counts?.new ?? 0;
  const different = counts?.different ?? 0;
  const toReplace = mode === "replace" ? different : 0;
  const nothing = preview !== null && toCreate === 0 && (different === 0 || !canReplace);
  const reasonOk = mode !== "replace" || reason.trim().length >= 3;

  return (
    <section className="import-panel">
      <h3>Importar arquivo da coleta</h3>
      <p className="muted">
        Planilha (CSV ou XLSX) ou PDF com texto, com o brinco na primeira coluna e os
        litros de cada vaca. Nada é gravado antes de você ver a prévia.
      </p>

      <div className="import-controls">
        <div>
          <label htmlFor="import-day">Data da coleta</label>
          <input
            id="import-day"
            type="date"
            value={day}
            max={today}
            onChange={(event) => {
              if (!event.target.value) return;
              setDay(event.target.value);
              reset();
            }}
          />
        </div>
        <div>
          <label htmlFor="import-file">Arquivo (CSV, XLSX ou PDF)</label>
          <input
            id="import-file"
            type="file"
            accept=".csv,.txt,.xlsx,.pdf"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              reset();
            }}
          />
        </div>
        <button type="button" onClick={() => void runPreview()} disabled={busy || file === null}>
          {busy && preview === null ? "Lendo…" : "Ver prévia"}
        </button>
      </div>

      {error && <p role="alert">{error}</p>}

      {done && (
        <div className="notice import-done" role="status">
          {done.already_imported ? (
            <>
              Este arquivo já tinha sido importado para {brDate(done.measured_on)} por{" "}
              {done.imported_by}. Nada mudou.
            </>
          ) : (
            <>
              Importação concluída: {plural(done.summary.created, "leitura nova", "leituras novas")}
              {done.summary.replaced > 0 &&
                `, ${plural(done.summary.replaced, "substituída", "substituídas")}`}
              .
            </>
          )}
        </div>
      )}

      {preview !== null && counts && (
        <div className="import-preview">
          <p className="import-summary">
            <strong>{preview.filename}</strong> · {brDate(preview.measured_on)} ·{" "}
            {plural(preview.rows.length, "linha lida", "linhas lidas")}
          </p>

          <ul className="import-counts" aria-label="Resumo">
            {(Object.keys(STATUS_LABEL) as ImportRowStatus[])
              .filter((status) => counts[status] > 0)
              .map((status) => (
                <li key={status} className={`tone-${STATUS_TONE[status]}`}>
                  <strong>{counts[status]}</strong> {STATUS_LABEL[status].toLowerCase()}
                </li>
              ))}
          </ul>

          <div className="scroll-x">
            <table className="import-table" aria-label="Prévia da importação">
              <thead>
                <tr>
                  <th>Linha</th>
                  <th>Brinco</th>
                  <th>Animal</th>
                  <th className="num">Litros</th>
                  <th>Situação</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((item, index) => (
                  <tr key={`${item.location}-${index}`} className={`tone-${STATUS_TONE[item.status]}`}>
                    <td className="muted">{item.location}</td>
                    <td>
                      <span className="tag">{item.brinco_lido}</span>
                    </td>
                    <td>
                      {item.animal_nome ?? item.nome_arquivo ?? "—"}
                      {item.notes.map((note) => (
                        <small key={note} className="import-note">
                          {note}
                        </small>
                      ))}
                    </td>
                    <td className="num">
                      {liters(item.producao)}
                      {item.status === "different" && item.existing_producao !== null && (
                        <small className="import-note">lançado: {liters(item.existing_producao)}</small>
                      )}
                    </td>
                    <td>
                      <span className={`pill tone-${STATUS_TONE[item.status]}`}>
                        {STATUS_LABEL[item.status]}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {preview.problems.length > 0 && (
            <details className="import-problems">
              <summary>Linhas não lidas ({preview.problems.length})</summary>
              <ul>
                {preview.problems.map((problem, index) => (
                  <li key={`${problem.location}-${index}`}>
                    <strong>{problem.location}</strong>: {problem.reason}
                    {problem.text && <code>{problem.text}</code>}
                  </li>
                ))}
              </ul>
              <p className="hint">Confira no arquivo original e lance à mão, se for o caso.</p>
            </details>
          )}

          {different > 0 && !canReplace && (
            <p className="hint">
              {plural(different, "leitura diferente", "leituras diferentes")} do que já está
              lançado {different === 1 ? "fica" : "ficam"} de fora. Para substituí-las, peça a
              um revisor.
            </p>
          )}

          {different > 0 && canReplace && (
            <fieldset className="import-mode">
              <legend>O que fazer com as leituras diferentes</legend>
              <label>
                <input
                  type="radio"
                  name="import-mode"
                  checked={mode === "new_only"}
                  onChange={() => setMode("new_only")}
                />
                Manter as já lançadas (importar só as novas)
              </label>
              <label>
                <input
                  type="radio"
                  name="import-mode"
                  checked={mode === "replace"}
                  onChange={() => setMode("replace")}
                />
                Substituir as diferentes pelo valor do arquivo
              </label>
              {mode === "replace" && (
                <>
                  <label htmlFor="import-reason">Motivo da substituição</label>
                  <input
                    id="import-reason"
                    value={reason}
                    onChange={(event) => setReason(event.target.value)}
                    placeholder="Ex.: dados da coleta normalizados"
                    autoComplete="off"
                  />
                  <p className="hint">
                    As leituras antigas ficam guardadas como substituídas, com este motivo.
                  </p>
                </>
              )}
            </fieldset>
          )}

          {mode === "replace" && preview.kept.length > 0 && (
            <details className="import-kept" open>
              <summary>
                {plural(preview.kept.length, "vaca", "vacas")} com leitura nesta data não{" "}
                {preview.kept.length === 1 ? "está" : "estão"} no arquivo e mantêm a leitura
                atual
              </summary>
              <ul>
                {preview.kept.map((kept) => (
                  <li key={kept.animal_id}>
                    <span className="tag">{kept.brinco ?? "sem brinco"}</span> {kept.nome ?? "—"}
                    {kept.producao !== null && ` · ${liters(kept.producao)} L`}
                  </li>
                ))}
              </ul>
            </details>
          )}

          {nothing ? (
            <p className="chart-empty">
              Nada a importar: as leituras válidas deste arquivo já estão lançadas.
            </p>
          ) : (
            <button
              type="button"
              onClick={() => void runCommit()}
              disabled={busy || !reasonOk}
            >
              {toReplace > 0
                ? `Importar ${toCreate} e substituir ${toReplace}`
                : `Importar ${plural(toCreate, "leitura", "leituras")}`}
            </button>
          )}
        </div>
      )}

      {history.length > 0 && (
        <div className="import-history">
          <h4>Últimas importações</h4>
          <ul>
            {history.map((item) => (
              <li key={item.id}>
                <strong>{item.filename}</strong>
                <span>
                  coleta de {brDate(item.measured_on)} · {item.imported_by} ·{" "}
                  {plural(item.summary.created, "nova", "novas")}
                  {item.summary.replaced > 0 &&
                    ` · ${plural(item.summary.replaced, "substituída", "substituídas")}`}
                </span>
                {item.reason && <small>Motivo: {item.reason}</small>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
