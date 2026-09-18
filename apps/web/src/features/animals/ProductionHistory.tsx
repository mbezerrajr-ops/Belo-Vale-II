import { useEffect, useState } from "react";

import { correctReading, getAnimalProduction, voidReading } from "../../api/client";
import type { ProductionHistoryEntry, Provenance, Reading } from "../../api/types";
import { Sparkline } from "../../ui/charts";
import { brDate, liters } from "../../ui/dates";

/**
 * Produção da vaca, na ficha.
 *
 * Mostra as leituras em vigor com origem e responsável, e guarda à parte as
 * versões anteriores — substituídas e anuladas — em vez de escondê-las: o
 * histórico conta o que aconteceu, não só o valor de hoje.
 *
 * O revisor corrige ou anula daqui mesmo, sem precisar saber em que folha e
 * lote aquela leitura foi lançada.
 */

/** Teto de plausibilidade, igual ao do servidor. */
const MAX_LITERS = 80;

type LoadFn = (token: string, animalId: string) => Promise<ProductionHistoryEntry[]>;
type CorrectFn = (
  token: string,
  measurementId: string,
  producao: number,
  reason: string,
) => Promise<Reading>;
type VoidFn = (token: string, measurementId: string, reason: string) => Promise<void>;

interface Props {
  token: string;
  animalId: string;
  canEdit: boolean;
  onLoad?: LoadFn;
  onCorrect?: CorrectFn;
  onVoid?: VoidFn;
}

const ORIGIN: Record<Provenance, string> = {
  manual_entry: "Digitada",
  file_import: "Importada",
  legacy_baseline: "Sistema antigo",
  ocr_review: "Ficha por foto",
  proposal_review: "Leitura revisada",
};

const OLD_STATUS: Record<string, string> = {
  superseded: "substituída",
  voided: "anulada",
};

function origin(entry: ProductionHistoryEntry): string {
  let text = ORIGIN[entry.provenance] ?? entry.provenance;
  if (entry.source) text += ` (${entry.source})`;
  if (entry.supersedes) {
    text += entry.provenance === "file_import" ? " · substituiu a anterior" : " · corrigida";
  }
  return text;
}

function oneDecimal(value: number): string {
  return value.toLocaleString("pt-BR", { maximumFractionDigits: 1 });
}

function parse(text: string): number | null {
  const value = Number(text.trim().replace(",", "."));
  if (text.trim() === "" || !Number.isFinite(value) || value < 0 || value > MAX_LITERS) {
    return null;
  }
  return Math.round(value * 100) / 100;
}

function errorMessage(error: unknown): string {
  const detail = (error as { body?: { detail?: unknown } })?.body?.detail;
  return typeof detail === "string" ? detail : "Não foi possível completar a ação.";
}

interface Editing {
  id: string;
  mode: "correct" | "void";
  value: string;
  reason: string;
}

export function ProductionHistory({
  token,
  animalId,
  canEdit,
  onLoad = getAnimalProduction,
  onCorrect = correctReading,
  onVoid = voidReading,
}: Props): JSX.Element {
  const [entries, setEntries] = useState<ProductionHistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [busy, setBusy] = useState(false);

  async function reload(): Promise<void> {
    try {
      setEntries(await onLoad(token, animalId));
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  useEffect(() => {
    setEntries(null);
    setEditing(null);
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, animalId]);

  async function submit(): Promise<void> {
    if (editing === null) return;
    const reason = editing.reason.trim();
    if (reason.length < 3) {
      setError("Explique o motivo em poucas palavras.");
      return;
    }
    let action: () => Promise<unknown>;
    if (editing.mode === "correct") {
      const value = parse(editing.value);
      if (value === null) {
        setError(`Confira o valor: de 0 a ${MAX_LITERS} litros.`);
        return;
      }
      action = () => onCorrect(token, editing.id, value, reason);
    } else {
      action = () => onVoid(token, editing.id, reason);
    }
    setBusy(true);
    setError(null);
    try {
      await action();
      setEditing(null);
      await reload();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  if (entries === null) {
    return (
      <section className="production-history">
        <h3>Produção</h3>
        {error ? <p role="alert">{error}</p> : <div className="skeleton" style={{ height: 96 }} />}
      </section>
    );
  }

  const active = entries.filter((entry) => entry.status === "active");
  const older = entries.filter((entry) => entry.status !== "active");
  const values = active.map((entry) => entry.producao ?? 0);
  const average = values.length ? values.reduce((sum, v) => sum + v, 0) / values.length : 0;
  const chronological = [...active].reverse();
  const editingEntry = editing ? entries.find((entry) => entry.id === editing.id) : undefined;

  return (
    <section className="production-history">
      <h3>Produção</h3>

      {active.length === 0 ? (
        <p className="chart-empty">Nenhuma leitura de produção registrada para este animal.</p>
      ) : (
        <>
          <p className="muted">
            {active.length} {active.length === 1 ? "coleta" : "coletas"} · média de{" "}
            {oneDecimal(average)} L · última em {brDate(active[0].measured_on)}
          </p>
          {chronological.length > 1 && (
            <Sparkline
              points={chronological.map((entry) => ({
                label: brDate(entry.measured_on).slice(0, 5),
                value: entry.producao ?? 0,
              }))}
              format={(value) => `${liters(value)} L`}
            />
          )}

          <div className="scroll-x">
            <table className="history-table" aria-label="Leituras de produção">
              <thead>
                <tr>
                  <th>Data</th>
                  <th className="num">Litros</th>
                  <th>Origem</th>
                  <th>Por</th>
                  {canEdit && <th aria-label="Ações" />}
                </tr>
              </thead>
              <tbody>
                {active.map((entry) => (
                  <tr key={entry.id}>
                    <td>{brDate(entry.measured_on)}</td>
                    <td className="num">{entry.producao === null ? "—" : liters(entry.producao)}</td>
                    <td>
                      {origin(entry)}
                      {entry.reason && <small className="import-note">Motivo: {entry.reason}</small>}
                    </td>
                    <td>{entry.responsible ?? "—"}</td>
                    {canEdit && (
                      <td className="row-actions">
                        <button
                          type="button"
                          className="link-btn"
                          onClick={() => {
                            setError(null);
                            setEditing({
                              id: entry.id,
                              mode: "correct",
                              value: entry.producao === null ? "" : liters(entry.producao),
                              reason: "",
                            });
                          }}
                        >
                          Corrigir
                        </button>
                        <button
                          type="button"
                          className="link-btn"
                          onClick={() => {
                            setError(null);
                            setEditing({ id: entry.id, mode: "void", value: "", reason: "" });
                          }}
                        >
                          Anular
                        </button>
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {editing !== null && editingEntry && (
        <form
          className="row-fix"
          onSubmit={(event) => {
            event.preventDefault();
            void submit();
          }}
        >
          <strong>
            {editing.mode === "correct" ? "Corrigir" : "Anular"} a leitura de{" "}
            {brDate(editingEntry.measured_on)} ({liters(editingEntry.producao ?? 0)} L)
          </strong>
          {editing.mode === "correct" && (
            <>
              <label htmlFor="history-value">Novo valor (L)</label>
              <input
                id="history-value"
                inputMode="decimal"
                value={editing.value}
                onChange={(event) => setEditing({ ...editing, value: event.target.value })}
                autoComplete="off"
              />
            </>
          )}
          <label htmlFor="history-reason">Motivo</label>
          <input
            id="history-reason"
            value={editing.reason}
            onChange={(event) => setEditing({ ...editing, reason: event.target.value })}
            placeholder={
              editing.mode === "correct" ? "Ex.: anotado errado no caderno" : "Ex.: lançado na vaca errada"
            }
            autoComplete="off"
          />
          <div className="row-fix-actions">
            <button type="submit" disabled={busy}>
              {editing.mode === "correct" ? "Salvar correção" : "Anular leitura"}
            </button>
            <button type="button" className="secondary" onClick={() => setEditing(null)}>
              Cancelar
            </button>
          </div>
        </form>
      )}

      {error && entries !== null && <p role="alert">{error}</p>}

      {older.length > 0 && (
        <details className="history-older">
          <summary>Versões anteriores ({older.length})</summary>
          <ul>
            {older.map((entry) => (
              <li key={entry.id}>
                <span>{brDate(entry.measured_on)}</span>
                <span>{entry.producao === null ? "—" : liters(entry.producao)}</span>
                <span>L</span>
                <span className="pill">{OLD_STATUS[entry.status] ?? entry.status}</span>
                <span className="muted">
                  {origin(entry)} · por {entry.responsible ?? "—"}
                </span>
                {entry.reason && <small>Motivo: {entry.reason}</small>}
              </li>
            ))}
          </ul>
          <p className="hint">Nada é apagado: estas leituras ficam como registro do que mudou.</p>
        </details>
      )}
    </section>
  );
}
