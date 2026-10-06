import { useState } from "react";

import { exportProduction, type ProductionExport } from "../../api/client";
import { ApiError } from "../../api/types";
import { brDate, farmToday } from "../../ui/dates";

/**
 * Exportação da produção de um período para planilha (XLSX).
 *
 * Uma linha por vaca por dia, só com o que está valendo. É de revisor e
 * administrador — a tela só aparece para eles, e o servidor confere de novo.
 * Período sem nenhuma leitura não baixa arquivo: avisa.
 */

type ExportFn = (token: string, inicio: string, fim: string) => Promise<ProductionExport>;
type SaveFn = (blob: Blob, filename: string) => void;

interface Props {
  token: string;
  today?: string;
  onExport?: ExportFn;
  onSave?: SaveFn;
}

/** O mesmo teto do servidor. */
const MAX_DAYS = 366;

const DAY_MS = 86_400_000;

function shift(iso: string, days: number): string {
  return new Date(Date.parse(`${iso}T00:00:00Z`) + days * DAY_MS).toISOString().slice(0, 10);
}

function daysBetween(start: string, end: string): number {
  return Math.round((Date.parse(`${end}T00:00:00Z`) - Date.parse(`${start}T00:00:00Z`)) / DAY_MS) + 1;
}

function monthStart(iso: string): string {
  return `${iso.slice(0, 8)}01`;
}

function shortcuts(today: string): { label: string; inicio: string; fim: string }[] {
  const lastMonthEnd = shift(monthStart(today), -1);
  return [
    { label: "Este mês", inicio: monthStart(today), fim: today },
    { label: "Mês passado", inicio: monthStart(lastMonthEnd), fim: lastMonthEnd },
    { label: "Últimos 30 dias", inicio: shift(today, -29), fim: today },
  ];
}

/** Entrega o arquivo ao navegador; no iPhone, abre o "salvar/compartilhar". */
function saveFile(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Dá tempo ao navegador de começar a gravar antes de liberar a memória.
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return "Exportar é de revisor ou administrador.";
    const detail = (error.body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  if (error instanceof TypeError) return "Sem conexão. Tente de novo quando o sinal voltar.";
  return "Não foi possível gerar a planilha.";
}

export function ExportPanel({
  token,
  today = farmToday(),
  onExport = exportProduction,
  onSave = saveFile,
}: Props): JSX.Element {
  const [inicio, setInicio] = useState(monthStart(today));
  const [fim, setFim] = useState(today);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ readings: number; filename: string } | null>(null);

  function choose(start: string, end: string): void {
    setInicio(start);
    setFim(end);
    setError(null);
    setResult(null);
  }

  const problem =
    fim < inicio
      ? "A data final vem antes da inicial."
      : daysBetween(inicio, fim) > MAX_DAYS
        ? `O período vai até ${MAX_DAYS} dias. Exporte em partes.`
        : null;

  async function run(): Promise<void> {
    if (problem) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const exported = await onExport(token, inicio, fim);
      if (exported.readings > 0) onSave(exported.blob, exported.filename);
      setResult({ readings: exported.readings, filename: exported.filename });
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="import-panel export-panel">
      <div className="search-shortcuts" role="group" aria-label="Período">
        {shortcuts(today).map((option) => (
          <button
            key={option.label}
            type="button"
            aria-pressed={option.inicio === inicio && option.fim === fim}
            onClick={() => choose(option.inicio, option.fim)}
          >
            {option.label}
          </button>
        ))}
      </div>

      <div className="import-controls">
        <div>
          <label htmlFor="export-start">De</label>
          <input
            id="export-start"
            type="date"
            value={inicio}
            max={today}
            onChange={(event) => event.target.value && choose(event.target.value, fim)}
          />
        </div>
        <div>
          <label htmlFor="export-end">Até</label>
          <input
            id="export-end"
            type="date"
            value={fim}
            max={today}
            onChange={(event) => event.target.value && choose(inicio, event.target.value)}
          />
        </div>
        <button type="button" onClick={() => void run()} disabled={busy || problem !== null}>
          {busy ? "Gerando…" : "Baixar planilha"}
        </button>
      </div>

      {problem && <p role="alert">{problem}</p>}
      {error && <p role="alert">{error}</p>}

      {result && (
        <div className="notice import-done" role="status">
          {result.readings === 0 ? (
            <>
              Nenhuma leitura entre {brDate(inicio)} e {brDate(fim)}. Nada foi baixado.
            </>
          ) : (
            <>
              Planilha baixada: {result.readings} {result.readings === 1 ? "leitura" : "leituras"} de{" "}
              {brDate(inicio)} a {brDate(fim)} ({result.filename}).
            </>
          )}
        </div>
      )}
    </section>
  );
}
