import { useEffect, useRef, useState, type CSSProperties } from "react";

import {
  correctReading,
  enterReading,
  getProductionSheet,
  voidReading,
} from "../../api/client";
import {
  ApiError,
  type ProductionSheet,
  type Reading,
  type ReadingConflict,
  type SheetItem,
} from "../../api/types";
import { brDate, liters, farmToday } from "../../ui/dates";
import { ImportPanel } from "./ImportPanel";
import { PageHeader } from "../../ui/PageHeader";

/**
 * Lançamento de produção, vaca a vaca.
 *
 * Feito para o curral: um campo por vaca, na ordem do caderno. Cada valor é
 * salvo sozinho ao sair do campo — não existe botão "salvar tudo" que uma
 * queda de sinal possa perder. Enter pula para a próxima vaca.
 *
 * Um valor já lançado nunca é sobrescrito daqui. O operador vê quem lançou e
 * pede a correção; o revisor corrige informando o motivo.
 */

/** Teto de plausibilidade, igual ao do servidor. */
const MAX_LITERS = 80;

type SheetFn = (
  token: string,
  measuredOn: string,
  lote: string | null,
) => Promise<ProductionSheet>;
type EnterFn = (
  token: string,
  animalId: string,
  measuredOn: string,
  producao: number,
) => Promise<Reading>;
type CorrectFn = (
  token: string,
  measurementId: string,
  producao: number,
  reason: string,
) => Promise<Reading>;
type VoidFn = (token: string, measurementId: string, reason: string) => Promise<void>;

interface Props {
  token: string;
  /** Revisor e administrador corrigem e anulam; operador só lança. */
  canCorrect: boolean;
  today?: string;
  onLoadSheet?: SheetFn;
  onEnter?: EnterFn;
  onCorrect?: CorrectFn;
  onVoid?: VoidFn;
}

type RowStatus =
  | "idle"
  | "saving"
  | "saved"
  | "invalid"
  | "offline"
  | "error"
  | "locked"
  | "correcting"
  | "voiding";

interface RowState {
  value: string;
  saved: number | null;
  measurementId: string | null;
  status: RowStatus;
  message: string | null;
  reason: string;
}

function show(value: number | null): string {
  return value === null ? "" : liters(value);
}

/** `"21,5"` → 21.5; vazio → null; ilegível ou fora do plausível → NaN. */
function parse(text: string): number | null {
  const cleaned = text.trim().replace(",", ".");
  if (cleaned === "") return null;
  const value = Number(cleaned);
  if (!Number.isFinite(value) || value < 0 || value > MAX_LITERS) return Number.NaN;
  return Math.round(value * 100) / 100;
}

function initialRows(items: SheetItem[]): Record<string, RowState> {
  return Object.fromEntries(
    items.map((item) => [
      item.animal_id,
      {
        value: show(item.producao),
        saved: item.producao,
        measurementId: item.measurement_id,
        status: item.producao === null ? "idle" : "saved",
        message: null,
        reason: "",
      } satisfies RowState,
    ]),
  );
}

function detailOf(error: unknown): unknown {
  return error instanceof ApiError ? (error.body as { detail?: unknown }).detail : undefined;
}

function isConflict(detail: unknown): detail is ReadingConflict {
  return (
    typeof detail === "object" &&
    detail !== null &&
    "existing" in detail &&
    typeof (detail as ReadingConflict).existing === "object"
  );
}

function label(item: SheetItem): string {
  return item.name ?? item.brinco ?? "animal sem identificação";
}

export function ProductionPage({
  token,
  canCorrect,
  today = farmToday(),
  onLoadSheet = getProductionSheet,
  onEnter = enterReading,
  onCorrect = correctReading,
  onVoid = voidReading,
}: Props): JSX.Element {
  const [day, setDay] = useState(today);
  const [lote, setLote] = useState<string | null>(null);
  const [sheet, setSheet] = useState<ProductionSheet | null>(null);
  const [rows, setRows] = useState<Record<string, RowState>>({});
  const [loadError, setLoadError] = useState<string | null>(null);
  const [how, setHow] = useState<"digitar" | "importar">("digitar");
  // Muda depois de uma importação, para a folha reler o que foi gravado.
  const [reloadKey, setReloadKey] = useState(0);
  // A folha para imprimir só existe enquanto se imprime: fora disso, os
  // nomes das vacas apareceriam duas vezes na página.
  const [printing, setPrinting] = useState(false);

  useEffect(() => {
    if (!printing) return;
    const done = (): void => setPrinting(false);
    window.addEventListener("afterprint", done);
    window.print();
    return () => window.removeEventListener("afterprint", done);
  }, [printing]);
  const inputs = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    let cancelled = false;
    setLoadError(null);
    onLoadSheet(token, day, lote)
      .then((loaded) => {
        if (cancelled) return;
        // A primeira chamada não sabe quais lotes existem: pega o primeiro.
        if (lote === null && loaded.lotes.length > 0) {
          setLote(loaded.lotes[0]);
          return;
        }
        setSheet(loaded);
        setRows(initialRows(loaded.items));
      })
      .catch(() => {
        if (!cancelled) {
          setLoadError("Não foi possível carregar a folha. Verifique a conexão.");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token, day, lote, onLoadSheet, reloadKey]);

  function patch(animalId: string, changes: Partial<RowState>): void {
    setRows((current) => ({
      ...current,
      [animalId]: { ...current[animalId], ...changes },
    }));
  }

  async function save(animalId: string, producao: number): Promise<void> {
    patch(animalId, { status: "saving", message: null });
    try {
      const result = await onEnter(token, animalId, day, producao);
      patch(animalId, {
        status: "saved",
        saved: result.producao,
        measurementId: result.id,
        value: show(result.producao),
      });
    } catch (error) {
      if (error instanceof TypeError) {
        // Sem sinal: o valor fica no campo até dar para enviar.
        patch(animalId, { status: "offline", message: "Sem conexão. O valor não foi salvo." });
        return;
      }
      const detail = detailOf(error);
      if (isConflict(detail)) {
        const who = detail.existing.entered_by ? ` por ${detail.existing.entered_by}` : "";
        patch(animalId, {
          status: "locked",
          saved: detail.existing.producao,
          measurementId: detail.existing.id,
          value: show(detail.existing.producao),
          message:
            `Já lançado: ${show(detail.existing.producao)} L${who}. ` +
            (canCorrect
              ? "Altere o valor de novo para corrigir."
              : "Para mudar, peça a um revisor."),
        });
        return;
      }
      patch(animalId, {
        status: "error",
        message: typeof detail === "string" ? detail : "Não foi possível salvar.",
      });
    }
  }

  function commit(animalId: string): void {
    const row = rows[animalId];
    if (!row || row.status === "saving") return;
    const parsed = parse(row.value);

    if (parsed === null) {
      // Apagar o campo não apaga um lançamento: isso é anular, com motivo.
      if (row.saved !== null) patch(animalId, { value: show(row.saved) });
      return;
    }
    if (Number.isNaN(parsed)) {
      patch(animalId, {
        status: "invalid",
        message: `Confira o valor: de 0 a ${MAX_LITERS} litros.`,
      });
      return;
    }
    if (row.saved !== null) {
      if (parsed === row.saved) {
        patch(animalId, { status: "saved", message: null, value: show(row.saved) });
        return;
      }
      if (canCorrect && row.measurementId !== null) {
        patch(animalId, { status: "correcting", message: null, reason: "" });
        return;
      }
      patch(animalId, {
        status: "locked",
        value: show(row.saved),
        message: `Já lançado: ${show(row.saved)} L. Para mudar, peça a um revisor.`,
      });
      return;
    }
    void save(animalId, parsed);
  }

  async function submitCorrection(animalId: string): Promise<void> {
    const row = rows[animalId];
    const parsed = parse(row.value);
    if (row.measurementId === null || parsed === null || Number.isNaN(parsed)) return;
    if (row.reason.trim().length < 3) {
      patch(animalId, { message: "Explique o motivo em poucas palavras." });
      return;
    }
    patch(animalId, { status: "saving", message: null });
    try {
      const result = await onCorrect(token, row.measurementId, parsed, row.reason.trim());
      patch(animalId, {
        status: "saved",
        saved: result.producao,
        measurementId: result.id,
        value: show(result.producao),
        reason: "",
      });
    } catch (error) {
      const detail = detailOf(error);
      patch(animalId, {
        status: "correcting",
        message: typeof detail === "string" ? detail : "Não foi possível corrigir.",
      });
    }
  }

  async function submitVoid(animalId: string): Promise<void> {
    const row = rows[animalId];
    if (row.measurementId === null) return;
    if (row.reason.trim().length < 3) {
      patch(animalId, { message: "Explique o motivo em poucas palavras." });
      return;
    }
    patch(animalId, { status: "saving", message: null });
    try {
      await onVoid(token, row.measurementId, row.reason.trim());
      patch(animalId, {
        status: "idle",
        saved: null,
        measurementId: null,
        value: "",
        reason: "",
      });
    } catch (error) {
      const detail = detailOf(error);
      patch(animalId, {
        status: "voiding",
        message: typeof detail === "string" ? detail : "Não foi possível anular.",
      });
    }
  }

  function cancelAdjust(animalId: string): void {
    const row = rows[animalId];
    patch(animalId, {
      status: row.saved === null ? "idle" : "saved",
      value: show(row.saved),
      message: null,
      reason: "",
    });
  }

  const items = sheet?.items ?? [];
  const savedRows = items.filter((item) => rows[item.animal_id]?.saved != null);
  const total = savedRows.reduce((sum, item) => sum + (rows[item.animal_id].saved ?? 0), 0);
  const progress = items.length === 0 ? 0 : savedRows.length / items.length;

  return (
    <section className="production">
      <PageHeader title="Produção do dia">
        Cada valor é salvo ao sair do campo; Enter passa para a próxima vaca.
      </PageHeader>

      <div className="segmented" role="group" aria-label="Como lançar">
        <button
          type="button"
          aria-pressed={how === "digitar"}
          onClick={() => setHow("digitar")}
        >
          Digitar
        </button>
        <button
          type="button"
          aria-pressed={how === "importar"}
          onClick={() => setHow("importar")}
        >
          Importar arquivo
        </button>
      </div>

      {how === "importar" && (
        <ImportPanel
          token={token}
          canReplace={canCorrect}
          today={today}
          onImported={() => setReloadKey((key) => key + 1)}
        />
      )}

      {how === "digitar" && (
      <>
      <div className="prod-controls">
        <label htmlFor="prod-day">Data da coleta</label>
        <input
          id="prod-day"
          type="date"
          value={day}
          max={today}
          onChange={(event) => event.target.value && setDay(event.target.value)}
        />
        {sheet !== null && sheet.lotes.length > 0 && (
          <div className="search-shortcuts" role="group" aria-label="Lote de ordenha">
            {sheet.lotes.map((name) => (
              <button
                key={name}
                type="button"
                aria-pressed={name === lote}
                onClick={() => setLote(name)}
              >
                {name}
              </button>
            ))}
          </div>
        )}
      </div>

      {loadError && <p role="alert">{loadError}</p>}

      {sheet === null && !loadError && (
        <div className="skeleton" style={{ height: 180 }} aria-label="Carregando" />
      )}

      {sheet !== null && sheet.lotes.length === 0 && (
        <p className="chart-empty">
          Nenhum lote de ordenha com animais. Coloque as vacas em lote pela ficha do
          animal.
        </p>
      )}

      {sheet !== null && items.length > 0 && (
        <>
          <div className="prod-summary" aria-live="polite">
            <div>
              <strong>{liters(total)} L</strong>
              <span>
                {savedRows.length} de {items.length} lançadas · {lote} ·{" "}
                {brDate(day)}
              </span>
            </div>
            <button
              type="button"
              className="secondary prod-print"
              onClick={() => setPrinting(true)}
            >
              Imprimir folha em branco
            </button>
            <div
              className="prod-progress"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={items.length}
              aria-valuenow={savedRows.length}
              aria-label="Vacas lançadas"
            >
              <i style={{ width: `${progress * 100}%` }} />
            </div>
          </div>

          <ul className="prod-list">
            {items.map((item, index) => {
              const row = rows[item.animal_id];
              if (!row) return null;
              const adjusting = row.status === "correcting" || row.status === "voiding";
              return (
                <li
                  key={item.animal_id}
                  className={`prod-row is-${row.status}`}
                  style={{ "--i": index } as CSSProperties}
                >
                  <span className={item.brinco ? "tag" : "tag none"}>
                    {item.brinco ?? "sem brinco"}
                  </span>
                  <span className="name">
                    {item.name ?? "sem nome"}
                    <small>
                      {item.situacao}
                      {/* Anular fica junto do nome: numa linha própria, cada
                          vaca ocupava o dobro da altura. */}
                      {canCorrect && row.status === "saved" && row.measurementId && (
                        <button
                          type="button"
                          className="row-void"
                          aria-label={`Anular o lançamento de ${label(item)}`}
                          onClick={() =>
                            patch(item.animal_id, { status: "voiding", message: null, reason: "" })
                          }
                        >
                          Anular
                        </button>
                      )}
                    </small>
                  </span>
                  <span className="prod-input">
                    <input
                      ref={(element) => {
                        inputs.current[index] = element;
                      }}
                      aria-label={`Litros de ${label(item)}`}
                      inputMode="decimal"
                      enterKeyHint="next"
                      autoComplete="off"
                      value={row.value}
                      disabled={row.status === "saving"}
                      onChange={(event) =>
                        patch(item.animal_id, { value: event.target.value })
                      }
                      onBlur={() => commit(item.animal_id)}
                      onKeyDown={(event) => {
                        if (event.key !== "Enter") return;
                        event.preventDefault();
                        // Sair do campo salva; aqui só se decide para onde ir.
                        const next = inputs.current[index + 1];
                        if (next) next.focus();
                        else event.currentTarget.blur();
                      }}
                    />
                    <span className="unit">L</span>
                  </span>
                  <span className="prod-state" aria-live="polite">
                    {row.status === "saving" && "salvando…"}
                    {row.status === "saved" && (
                      <span className="ok" aria-label="salvo">
                        ✓
                      </span>
                    )}
                  </span>

                  {row.message && <p className="row-msg">{row.message}</p>}

                  {row.status === "offline" && (
                    <button
                      type="button"
                      className="row-retry"
                      onClick={() => commit(item.animal_id)}
                    >
                      Tentar de novo
                    </button>
                  )}

                  {adjusting && (
                    <div className="row-fix">
                      <label htmlFor={`reason-${item.animal_id}`}>
                        {row.status === "correcting"
                          ? `Motivo da correção (${show(row.saved)} → ${row.value} L)`
                          : "Motivo para anular este lançamento"}
                      </label>
                      <input
                        id={`reason-${item.animal_id}`}
                        value={row.reason}
                        onChange={(event) =>
                          patch(item.animal_id, { reason: event.target.value })
                        }
                        placeholder={
                          row.status === "correcting"
                            ? "Ex.: anotado errado no caderno"
                            : "Ex.: lançado na vaca errada"
                        }
                        autoComplete="off"
                      />
                      <div className="row-fix-actions">
                        <button
                          type="button"
                          className={row.status === "voiding" ? "danger" : undefined}
                          onClick={() =>
                            void (row.status === "correcting"
                              ? submitCorrection(item.animal_id)
                              : submitVoid(item.animal_id))
                          }
                        >
                          {row.status === "correcting" ? "Salvar correção" : "Anular lançamento"}
                        </button>
                        <button
                          type="button"
                          className="secondary"
                          onClick={() => cancelAdjust(item.animal_id)}
                        >
                          Cancelar
                        </button>
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </>
      )}

      {sheet !== null && sheet.lote !== null && items.length === 0 && (
        <p className="chart-empty">Nenhuma vaca neste lote hoje.</p>
      )}
      </>
      )}

      {/* Só aparece no papel: a folha para preencher à mão no curral. */}
      {printing && sheet !== null && items.length > 0 && (
        <div className="print-area" aria-hidden="true">
          <h1>Folha de coleta de leite</h1>
          <p>
            {lote} · {brDate(day)} · {items.length} vacas
          </p>
          <table>
            <thead>
              <tr>
                <th>Brinco</th>
                <th>Nome</th>
                <th className="write-in">Litros</th>
                <th className="write-in">Obs.</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.animal_id}>
                  <td>{item.brinco ?? "sem brinco"}</td>
                  <td>{item.name ?? "sem nome"}</td>
                  <td className="write-in" />
                  <td className="write-in" />
                </tr>
              ))}
            </tbody>
          </table>
          <p className="print-foot">Anotado por: ______________________</p>
        </div>
      )}
    </section>
  );
}
