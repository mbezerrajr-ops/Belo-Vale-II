import {
  Suspense,
  lazy,
  memo,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FocusEvent,
  type KeyboardEvent,
} from "react";

import {
  correctReading,
  enterReading,
  getProductionSheet,
  voidReading,
  getActiveFarmId,
} from "../../api/client";
import {
  ApiError,
  type ProductionSheet,
  type Reading,
  type ReadingConflict,
  type ReadingInput,
  type SheetItem,
} from "../../api/types";
import { brDate, liters, farmToday } from "../../ui/dates";
// A importação é de escritório: só baixa quando alguém escolhe "Importar".
const ImportPanel = lazy(() => import("./ImportPanel").then((m) => ({ default: m.ImportPanel })));
const ExportPanel = lazy(() => import("./ExportPanel").then((m) => ({ default: m.ExportPanel })));
import { Icons } from "../../ui/Brand";
import { PrintHeader } from "../../ui/PrintHeader";
import { PrintPortal } from "../../ui/PrintPortal";
import { PageHeader } from "../../ui/PageHeader";
import { isTransient, withTimeout, type QueuedReading } from "../../offline/outbox";
import { useOutbox } from "../../offline/OutboxContext";
import { loadStoredUser } from "../../auth/session";
import { useActiveFarm } from "../workspace/context";

/**
 * Lançamento de produção, vaca a vaca.
 *
 * Feito para o curral: um campo por vaca com os litros do dia, na ordem do
 * caderno, e a observação da pesagem quando houver ("→ Seca"). Cada valor é
 * salvo sozinho ao sair da vaca — não existe botão "salvar tudo" que uma
 * queda de sinal possa perder. Enter pula para a próxima vaca.
 *
 * Na tela, só o total: manhã e tarde aparecem na folha impressa, quando a
 * leitura as tem (a importação da planilha da fazenda traz as duas).
 *
 * Um valor já lançado nunca é sobrescrito daqui. Anotar a observação depois é
 * livre; mudar os litros é correção, de revisor, com motivo.
 */

/** Teto de plausibilidade, igual ao do servidor. */
const MAX_LITERS = 80;

/** Sinal fraco pode deixar o pedido pendurado: depois disto, vai para a fila. */
export const SAVE_TIMEOUT_MS = 15_000;

const QUEUED =
  "Sem sinal — guardado neste celular. Vai sozinho quando o sinal voltar.";

/**
 * A última folha vista de cada usuário/fazenda/lote/dia fica no aparelho,
 * inclusive após fechar a aba. Não é compartilhada com outra identidade.
 */
function sheetKey(day: string, lote: string | null): string {
  const userId = loadStoredUser()?.id ?? "";
  return `belo-vale.folha:${userId}|${getActiveFarmId() ?? ""}|${day}|${lote ?? ""}`;
}

function rememberSheet(day: string, lote: string | null, sheet: ProductionSheet): void {
  try {
    localStorage.setItem(sheetKey(day, lote), JSON.stringify({ at: Date.now(), sheet }));
  } catch {
    // Sem espaço: só não haverá a folha guardada.
  }
}

function rememberedSheet(day: string, lote: string | null): { at: number; sheet: ProductionSheet } | null {
  try {
    const raw = localStorage.getItem(sheetKey(day, lote));
    return raw ? (JSON.parse(raw) as { at: number; sheet: ProductionSheet }) : null;
  } catch {
    return null;
  }
}

type SheetFn = (
  token: string,
  measuredOn: string,
  lote: string | null,
) => Promise<ProductionSheet>;
type EnterFn = (
  token: string,
  animalId: string,
  measuredOn: string,
  input: ReadingInput,
) => Promise<Reading>;
type CorrectFn = (
  token: string,
  measurementId: string,
  input: ReadingInput,
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
  | "queued"
  | "error"
  | "locked"
  | "correcting"
  | "voiding";

/** O que está gravado para a vaca no dia. */
interface Saved {
  producao: number | null;
  manha: number | null;
  tarde: number | null;
  observacao: string | null;
}

interface RowState {
  /** Os litros, como digitados. */
  value: string;
  obs: string;
  /** O campo de observação aberto (ou já com texto). */
  noteOpen: boolean;
  saved: Saved | null;
  measurementId: string | null;
  status: RowStatus;
  message: string | null;
  reason: string;
}

function show(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : liters(value);
}

/** `"21,5"` → 21.5; vazio → null; ilegível ou fora do plausível → NaN. */
function parse(text: string): number | null {
  const cleaned = text.trim().replace(",", ".");
  if (cleaned === "") return null;
  const value = Number(cleaned);
  if (!Number.isFinite(value) || value < 0 || value > MAX_LITERS) return Number.NaN;
  return Math.round(value * 100) / 100;
}

function savedOf(source: {
  producao: number | null;
  manha?: number | null;
  tarde?: number | null;
  observacao?: string | null;
}): Saved {
  return {
    producao: source.producao,
    manha: source.manha ?? null,
    tarde: source.tarde ?? null,
    observacao: source.observacao ?? null,
  };
}

/** Os campos da linha a partir do que está gravado. */
function fieldsOf(saved: Saved | null): Pick<RowState, "value" | "obs" | "noteOpen"> {
  return {
    value: show(saved?.producao),
    obs: saved?.observacao ?? "",
    noteOpen: Boolean(saved?.observacao),
  };
}

function initialRows(items: SheetItem[]): Record<string, RowState> {
  return Object.fromEntries(
    items.map((item) => {
      const saved = item.producao === null ? null : savedOf(item);
      return [
        item.animal_id,
        {
          ...fieldsOf(saved),
          saved,
          measurementId: item.measurement_id,
          status: saved === null ? "idle" : "saved",
          message: null,
          reason: "",
        } satisfies RowState,
      ];
    }),
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

/** A anotação digitada, sem espaços sobrando; vazia vira `null`. */
function noteOf(row: RowState): string | null {
  const obs = row.obs.trim().replace(/\s+/g, " ");
  return obs === "" ? null : obs;
}

function inputOf(producao: number, obs: string | null): ReadingInput {
  return obs === null ? { producao } : { producao, observacao: obs };
}

interface RowActions {
  patch: (animalId: string, changes: Partial<RowState>) => void;
  commit: (animalId: string) => void;
  submitCorrection: (animalId: string) => void;
  submitVoid: (animalId: string) => void;
  cancelAdjust: (animalId: string) => void;
  registerInput: (position: number, element: HTMLInputElement | null) => void;
  focusNext: (position: number, current: HTMLInputElement) => void;
}

/**
 * Uma vaca da folha. Só redesenha quando a linha dela muda: antes, cada
 * tecla redesenhava as 60 vacas do lote, e no celular simples do curral isso
 * pesava no digitar.
 */
const ProductionRow = memo(function ProductionRow({
  item,
  index,
  row,
  canCorrect,
  actions,
}: {
  item: SheetItem;
  index: number;
  row: RowState;
  canCorrect: boolean;
  actions: RowActions;
}): JSX.Element {
  const adjusting = row.status === "correcting" || row.status === "voiding";
  const who = label(item);
  // Sair de um campo para outro da mesma vaca não salva; sair da vaca salva.
  const leave = (event: FocusEvent<HTMLElement>): void => {
    const next = event.relatedTarget as Node | null;
    if (next && event.currentTarget.closest("li")?.contains(next)) return;
    actions.commit(item.animal_id);
  };
  const onEnter = (position: number) => (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    actions.focusNext(position, event.currentTarget);
  };
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
          {!row.noteOpen && (
            <button
              type="button"
              className="row-void row-note"
              aria-label={`Anotar observação de ${who}`}
              onClick={() => actions.patch(item.animal_id, { noteOpen: true })}
            >
              Obs.
            </button>
          )}
          {/* Anular fica junto do nome: numa linha própria, cada
              vaca ocupava o dobro da altura. */}
          {canCorrect && row.status === "saved" && row.measurementId && (
            <button
              type="button"
              className="row-void"
              aria-label={`Anular o lançamento de ${who}`}
              onClick={() =>
                actions.patch(item.animal_id, { status: "voiding", message: null, reason: "" })
              }
            >
              Anular
            </button>
          )}
        </small>
      </span>
      <span className="prod-input">
        <input
          ref={(element) => actions.registerInput(index, element)}
          aria-label={`Litros de ${who}`}
          inputMode="decimal"
          enterKeyHint="next"
          autoComplete="off"
          value={row.value}
          disabled={row.status === "saving"}
          onChange={(event) => actions.patch(item.animal_id, { value: event.target.value })}
          onBlur={leave}
          onKeyDown={onEnter(index)}
        />
        <span className="unit">L</span>
      </span>
      <span className="prod-state" aria-live="polite">
        {row.status === "saving" && "salvando…"}
        {row.status === "queued" && (
          <span className="queued" aria-label="guardado no celular" title="Guardado no celular">
            <Icons.guardado />
          </span>
        )}
        {row.status === "saved" && (
          <span className="ok" aria-label="salvo">
            ✓
          </span>
        )}
      </span>

      {row.noteOpen && (
        <input
          className="row-note-input"
          aria-label={`Observação de ${who}`}
          placeholder="Ex.: → Seca, → 3º Lote"
          maxLength={200}
          autoComplete="off"
          value={row.obs}
          disabled={row.status === "saving"}
          onChange={(event) => actions.patch(item.animal_id, { obs: event.target.value })}
          onBlur={leave}
          onKeyDown={onEnter(index)}
        />
      )}

      {row.message && <p className="row-msg">{row.message}</p>}

      {row.status === "offline" && (
        <button
          type="button"
          className="row-retry"
          onClick={() => actions.commit(item.animal_id)}
        >
          Tentar de novo
        </button>
      )}

      {adjusting && (
        <div className="row-fix">
          <label htmlFor={`reason-${item.animal_id}`}>
            {row.status === "correcting"
              ? `Motivo da correção (${show(row.saved?.producao)} → ${row.value} L)`
              : "Motivo para anular este lançamento"}
          </label>
          <input
            id={`reason-${item.animal_id}`}
            value={row.reason}
            onChange={(event) => actions.patch(item.animal_id, { reason: event.target.value })}
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
                row.status === "correcting"
                  ? actions.submitCorrection(item.animal_id)
                  : actions.submitVoid(item.animal_id)
              }
            >
              {row.status === "correcting" ? "Salvar correção" : "Anular lançamento"}
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => actions.cancelAdjust(item.animal_id)}
            >
              Cancelar
            </button>
          </div>
        </div>
      )}
    </li>
  );
});

/** A data que mais aparece como pesagem anterior: o título da coluna. */
function previousDate(items: SheetItem[]): string | null {
  const counts = new Map<string, number>();
  for (const item of items) {
    const day = item.anterior?.measured_on;
    if (day) counts.set(day, (counts.get(day) ?? 0) + 1);
  }
  let best: string | null = null;
  for (const [day, count] of counts) {
    if (best === null || count > (counts.get(best) ?? 0)) best = day;
  }
  return best;
}

function shortDay(iso: string): string {
  return brDate(iso).slice(0, 5);
}

/** Um número da faixa de resumo da folha. */
function Figure({ label, value, hint }: { label: string; value: string; hint?: string }): JSX.Element {
  return (
    <div className="ps-figure">
      <dt>{label}</dt>
      <dd>
        {value}
        {hint && <small>{hint}</small>}
      </dd>
    </div>
  );
}

/**
 * A folha para o papel, com a cara do sistema: marca, lote e data no alto,
 * um resumo do lote e as assinaturas no pé.
 *
 * Com lançamentos no dia, é o registro da pesagem. Manhã e tarde só entram
 * quando alguma vaca as tem: leituras antigas guardam só o total, e duas
 * colunas vazias só ocupariam lugar. Sem lançamentos, é a folha para
 * preencher no curral, com a pesagem anterior ao lado de cada vaca — quem
 * anota "3" para a vaca que deu 30 no mês passado vê na hora.
 */
function PrintSheet({
  items,
  rows,
  lote,
  day,
}: {
  items: SheetItem[];
  rows: Record<string, RowState>;
  lote: string | null;
  day: string;
}): JSX.Element {
  const activeFarm = useActiveFarm();
  const saved = items.filter((item) => rows[item.animal_id]?.saved);
  const filled = saved.length > 0;
  const reference = previousDate(items);

  let figures: JSX.Element;
  if (filled) {
    const total = saved.reduce((sum, item) => sum + (rows[item.animal_id].saved?.producao ?? 0), 0);
    figures = (
      <>
        <Figure label="Total do lote" value={`${liters(total)} L`} />
        <Figure label="Vacas lançadas" value={`${saved.length} de ${items.length}`} />
        <Figure label="Média por vaca" value={`${liters(Math.round((total / saved.length) * 10) / 10)} L`} />
      </>
    );
  } else {
    const before = items.filter((item) => item.anterior && item.anterior.measured_on === reference);
    const total = before.reduce((sum, item) => sum + (item.anterior?.producao ?? 0), 0);
    figures = (
      <>
        <Figure label="Vacas no lote" value={String(items.length)} />
        {reference && (
          <Figure
            label="Pesagem anterior"
            value={`${liters(total)} L`}
            hint={`${brDate(reference)} · ${before.length} vacas`}
          />
        )}
        <Figure label="Anotar" value="Manhã e tarde" hint="observação: secar, trocar de lote" />
      </>
    );
  }

  const parts =
    filled && saved.some((item) => {
      const reading = rows[item.animal_id].saved;
      return reading?.manha != null || reading?.tarde != null;
    });

  return (
    <div className="print-area ps" aria-hidden="true">
      <PrintHeader
        kind={filled ? "Registro da pesagem de leite" : "Folha de coleta de leite"}
        tag={lote}
        date={brDate(day)}
      />

      <dl className="ps-summary">{figures}</dl>

      <table>
        <thead>
          {filled ? (
            <tr>
              <th className="ps-tag">Brinco</th>
              <th>Nome</th>
              {parts && <th className="num">Manhã</th>}
              {parts && <th className="num">Tarde</th>}
              <th className="num">Total</th>
              <th className="note">Obs.</th>
            </tr>
          ) : (
            <tr>
              <th className="ps-tag">Brinco</th>
              <th>Nome</th>
              <th className="num">{reference ? `Última (${shortDay(reference)})` : "Última"}</th>
              <th className="write-in">Manhã</th>
              <th className="write-in">Tarde</th>
              <th className="write-in">Obs.</th>
            </tr>
          )}
        </thead>
        <tbody>
          {items.map((item) => {
            const brinco = <td className="ps-tag">{item.brinco ?? "sem brinco"}</td>;
            const name = <td>{item.name ?? "sem nome"}</td>;
            if (filled) {
              const reading = rows[item.animal_id]?.saved;
              return (
                <tr key={item.animal_id} className={reading ? undefined : "ps-missing"}>
                  {brinco}
                  {name}
                  {parts && <td className="num">{show(reading?.manha)}</td>}
                  {parts && <td className="num">{show(reading?.tarde)}</td>}
                  <td className="num">
                    <strong>{reading ? show(reading.producao) : "—"}</strong>
                  </td>
                  <td className="note">{reading?.observacao ?? ""}</td>
                </tr>
              );
            }
            const before = item.anterior;
            const other = before && before.measured_on !== reference ? ` (${shortDay(before.measured_on)})` : "";
            return (
              <tr key={item.animal_id}>
                {brinco}
                {name}
                <td className="num">{before ? `${show(before.producao)}${other}` : "—"}</td>
                <td className="write-in" />
                <td className="write-in" />
                <td className="write-in" />
              </tr>
            );
          })}
        </tbody>
      </table>

      <footer className="ps-foot">
        <div className="ps-sign">Anotado por</div>
        <div className="ps-sign">Conferido por</div>
        <p>
          Impresso em {brDate(farmToday())} · {activeFarm?.name ?? "Belo Vale II"} · {lote} · {items.length} vacas
        </p>
      </footer>
    </div>
  );
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
  // Folha guardada em uso, sem sinal: quando foi vista pela última vez.
  const [staleAt, setStaleAt] = useState<number | null>(null);
  const queue = useOutbox();
  const [how, setHow] = useState<"digitar" | "importar" | "exportar">("digitar");
  // Muda depois de uma importação, para a folha reler o que foi gravado.
  const [reloadKey, setReloadKey] = useState(0);
  // A folha para imprimir só existe enquanto se imprime: fora disso, os
  // nomes das vacas apareceriam duas vezes na página. Cada toque em Imprimir
  // é um pedido novo (0 = nenhum): no app instalado no iPhone o navegador
  // pode não avisar o fim da impressão, e com um sim/não o segundo toque não
  // imprimia nada.
  const [printRequest, setPrintRequest] = useState(0);
  const printing = printRequest > 0;

  useEffect(() => {
    if (printRequest === 0) return;
    const done = (): void => setPrintRequest(0);
    window.addEventListener("afterprint", done);
    window.print();
    return () => window.removeEventListener("afterprint", done);
  }, [printRequest]);
  const inputs = useRef<(HTMLInputElement | null)[]>([]);

  useEffect(() => {
    let cancelled = false;
    setLoadError(null);
    const display = (loaded: ProductionSheet): void => {
      // A primeira chamada não sabe quais lotes existem: pega o primeiro.
      if (lote === null && loaded.lotes.length > 0) {
        setLote(loaded.lotes[0]);
        return;
      }
      setSheet(loaded);
      setRows(initialRows(loaded.items));
    };
    onLoadSheet(token, day, lote)
      .then((loaded) => {
        if (cancelled) return;
        if (queue) rememberSheet(day, lote, loaded);
        setStaleAt(null);
        display(loaded);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const saved = queue && isTransient(error) ? rememberedSheet(day, lote) : null;
        if (saved) {
          setStaleAt(saved.at);
          display(saved.sheet);
          return;
        }
        setLoadError("Não foi possível carregar a folha. Verifique a conexão.");
      });
    return () => {
      cancelled = true;
    };
    // `queue` só liga a folha guardada; mudar de fila não relê a folha.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, day, lote, onLoadSheet, reloadKey]);

  // O que está guardado no celular para este dia aparece na linha da vaca,
  // e sai dela quando for enviado (ou recusado).
  useEffect(() => {
    if (!queue || sheet === null) return;
    let cancelled = false;
    const mark = async (): Promise<void> => {
      const items = await queue.outbox.list(queue.userId);
      if (cancelled) return;
      setRows((current) => {
        const next = { ...current };
        for (const item of items) {
          if (item.kind !== "reading" || item.measuredOn !== day) continue;
          const row = next[item.animalId];
          if (!row || row.status === "saving") continue;
          if (item.error) {
            next[item.animalId] = { ...row, status: "error", message: `Não enviado: ${item.error}` };
            continue;
          }
          const fields = queuedFields(item);
          next[item.animalId] = { ...row, ...fields, status: "queued", message: fields.message ?? QUEUED };
        }
        return next;
      });
    };
    void mark();
    const unsubscribe = queue.outbox.subscribe((event) => {
      if (event.type === "sent" && event.item.kind === "reading" && event.item.measuredOn === day) {
        const { animalId } = event.item;
        const result = event.result as Reading;
        const saved = savedOf(result);
        setRows((current) =>
          current[animalId]
            ? {
                ...current,
                [animalId]: {
                  ...current[animalId],
                  ...fieldsOf(saved),
                  status: "saved",
                  saved,
                  measurementId: result.id,
                  message: null,
                },
              }
            : current,
        );
      }
      if (event.type === "refused") void mark();
    });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [queue, sheet, day]);

  function patch(animalId: string, changes: Partial<RowState>): void {
    setRows((current) => ({
      ...current,
      [animalId]: { ...current[animalId], ...changes },
    }));
  }

  async function save(animalId: string, input: ReadingInput): Promise<void> {
    const originFarm = getActiveFarmId();
    patch(animalId, { status: "saving", message: null });
    try {
      const result = await withTimeout(onEnter(token, animalId, day, input), SAVE_TIMEOUT_MS);
      const saved = savedOf(result);
      patch(animalId, {
        ...fieldsOf(saved),
        status: "saved",
        saved,
        measurementId: result.id,
      });
      // O valor já foi salvo: falhar ao limpar a fila não vira erro na linha.
      if (queue) await queue.outbox.dropReading(queue.userId, animalId, day).catch(() => undefined);
    } catch (error) {
      // No app, sem sinal (ou servidor fora do ar) vai para a fila do
      // celular: recarregar ou sair da tela não perde mais o valor. Se o
      // primeiro envio tiver chegado, reenviar o mesmo valor é seguro.
      if (queue && isTransient(error)) {
        const item = items.find((entry) => entry.animal_id === animalId);
        try { await queue.outbox.addReading({
          userId: queue.userId,
          farmId: originFarm ?? undefined,
          animalId,
          label: item ? label(item) : "vaca",
          measuredOn: day,
          producao: input.producao ?? 0,
          observacao: input.observacao ?? null,
        }); } catch {
          patch(animalId, { status: "error", message: "Não foi possível guardar neste celular. Confira o espaço disponível. Mantenha a tela aberta para tentar novamente." });
          return;
        }
        patch(animalId, { status: "queued", message: QUEUED });
        return;
      }
      if (error instanceof TypeError) {
        // Sem sinal: o valor fica no campo até dar para enviar.
        patch(animalId, { status: "offline", message: "Sem conexão. O valor não foi salvo." });
        return;
      }
      const detail = detailOf(error);
      if (isConflict(detail)) {
        const saved = savedOf(detail.existing);
        const who = detail.existing.entered_by ? ` por ${detail.existing.entered_by}` : "";
        patch(animalId, {
          ...fieldsOf(saved),
          status: "locked",
          saved,
          measurementId: detail.existing.id,
          message:
            `Já lançado: ${show(saved.producao)} L${who}. ` +
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
    if (!row || row.status === "saving" || row.status === "correcting" || row.status === "voiding") {
      return;
    }
    const parsed = parse(row.value);
    const obs = noteOf(row);
    if (Number.isNaN(parsed)) {
      patch(animalId, {
        status: "invalid",
        message: `Confira o valor: de 0 a ${MAX_LITERS} litros.`,
      });
      return;
    }

    const saved = row.saved;
    if (saved === null) {
      if (parsed === null) {
        if (obs !== null) {
          patch(animalId, { status: "idle", message: "Anote os litros junto da observação." });
        } else if (row.status === "invalid") {
          patch(animalId, { status: "idle", message: null });
        }
        return;
      }
      void save(animalId, inputOf(parsed, obs));
      return;
    }

    // Apagar o campo não apaga um lançamento: isso é anular, com motivo.
    const value = parsed ?? saved.producao;
    const note = obs ?? saved.observacao;
    const restore = { ...fieldsOf(saved), noteOpen: row.noteOpen || Boolean(saved.observacao) };
    const changed =
      value !== saved.producao || (saved.observacao !== null && note !== saved.observacao);

    if (changed) {
      if (canCorrect && row.measurementId !== null) {
        patch(animalId, { status: "correcting", message: null, reason: "" });
        return;
      }
      patch(animalId, {
        ...restore,
        status: "locked",
        message: `Já lançado: ${show(saved.producao)} L. Para mudar, peça a um revisor.`,
      });
      return;
    }
    // Só a anotação, numa vaca já lançada: completa sem mexer nos litros.
    if (saved.observacao === null && note !== null && saved.producao !== null) {
      void save(animalId, inputOf(saved.producao, note));
      return;
    }
    patch(animalId, { ...restore, status: "saved", message: null });
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
      const result = await onCorrect(
        token,
        row.measurementId,
        { producao: parsed, observacao: noteOf(row) },
        row.reason.trim(),
      );
      const saved = savedOf(result);
      patch(animalId, {
        ...fieldsOf(saved),
        status: "saved",
        saved,
        measurementId: result.id,
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
        ...fieldsOf(null),
        status: "idle",
        saved: null,
        measurementId: null,
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
      ...fieldsOf(row.saved),
      status: row.saved === null ? "idle" : "saved",
      message: null,
      reason: "",
    });
  }

  // As linhas recebem ações estáveis, que chamam sempre as funções da hora:
  // assim a linha memorizada não redesenha só porque a função foi recriada.
  const latest = useRef({ patch, commit, submitCorrection, submitVoid, cancelAdjust });
  latest.current = { patch, commit, submitCorrection, submitVoid, cancelAdjust };
  const actions = useMemo<RowActions>(
    () => ({
      patch: (animalId, changes) => latest.current.patch(animalId, changes),
      commit: (animalId) => latest.current.commit(animalId),
      submitCorrection: (animalId) => void latest.current.submitCorrection(animalId),
      submitVoid: (animalId) => void latest.current.submitVoid(animalId),
      cancelAdjust: (animalId) => latest.current.cancelAdjust(animalId),
      registerInput: (position, element) => {
        inputs.current[position] = element;
      },
      focusNext: (position, currentInput) => {
        const next = inputs.current[position + 1];
        if (next) next.focus();
        else currentInput.blur();
      },
    }),
    [],
  );

  const items = sheet?.items ?? [];
  const savedRows = items.filter((item) => rows[item.animal_id]?.saved != null);
  const total = savedRows.reduce((sum, item) => sum + (rows[item.animal_id].saved?.producao ?? 0), 0);
  const progress = items.length === 0 ? 0 : savedRows.length / items.length;
  const queuedCount = items.filter((item) => rows[item.animal_id]?.status === "queued").length;

  return (
    <section className="production">
      <PageHeader
        title={how === "exportar" ? "Produção do período" : "Produção do dia"}
        actions={
          <div className="segmented prod-modes" role="group" aria-label="Como lançar">
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
              {/* No celular estreito o "arquivo" sai da vista, mas o nome
                  lido continua "Importar arquivo". */}
              Importar<span className="narrow-hide"> arquivo</span>
            </button>
            {/* Exportar leva a produção do rebanho para fora do sistema: só
                revisor e administrador (o servidor confere de novo). */}
            {canCorrect && (
              <button
                type="button"
                aria-pressed={how === "exportar"}
                onClick={() => setHow("exportar")}
              >
                Exportar
              </button>
            )}
          </div>
        }
      >
        {/* A frase fala do modo escolhido: "Enter passa para a próxima vaca"
            não diz nada a quem está importando uma planilha. */}
        {how === "digitar"
          ? "Cada valor é salvo ao sair do campo; Enter passa para a próxima vaca."
          : how === "importar"
            ? "Planilha (CSV ou XLSX) ou PDF com o brinco e os litros — total, ou manhã e tarde — e a observação, se houver. Nada é gravado antes da prévia."
            : "Planilha (XLSX) com a produção do período: uma linha por vaca por dia, com lote, manhã, tarde, total e observação."}
      </PageHeader>

      {how === "exportar" && (
        <Suspense fallback={<div className="skeleton" style={{ height: 120 }} role="status" aria-label="Carregando" />}>
          <ExportPanel token={token} today={today} />
        </Suspense>
      )}

      {how === "importar" && (
        <Suspense fallback={<div className="skeleton" style={{ height: 180 }} role="status" aria-label="Carregando" />}>
          <ImportPanel
            token={token}
            canReplace={canCorrect}
            today={today}
            onImported={() => setReloadKey((key) => key + 1)}
          />
        </Suspense>
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

      {staleAt !== null && (
        <p className="warning">
          Sem sinal: esta é a folha guardada às{" "}
          {new Date(staleAt).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}.
          Pode lançar — fica guardado e vai quando o sinal voltar.
        </p>
      )}

      {sheet === null && !loadError && (
        <div className="skeleton" style={{ height: 180 }} role="status" aria-label="Carregando" />
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
                {savedRows.length} de {items.length} lançadas
                {queuedCount > 0 &&
                  ` · ${queuedCount} ${queuedCount === 1 ? "guardada" : "guardadas"} no celular`} · {lote} ·{" "}
                {brDate(day)}
              </span>
            </div>
            {/* Coisa de véspera, não do lançamento: discreto, ao lado do total. */}
            <button
              type="button"
              className="link-btn prod-print"
              aria-label={savedRows.length > 0 ? "Imprimir folha preenchida" : "Imprimir folha em branco"}
              onClick={() => setPrintRequest((count) => count + 1)}
            >
              <Icons.imprimir /> <span className="wide-only">Imprimir folha</span>
            </button>
            <div
              className="prod-progress"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={items.length}
              aria-valuenow={savedRows.length}
              aria-label="Vacas lançadas"
            >
              <i style={{ clipPath: `inset(0 ${(1 - progress) * 100}% 0 0 round 999px)` }} />
            </div>
          </div>

          <ul className="prod-list">
            {items.map((item, index) => {
              const row = rows[item.animal_id];
              if (!row) return null;
              return (
                <ProductionRow
                  key={item.animal_id}
                  item={item}
                  index={index}
                  row={row}
                  canCorrect={canCorrect}
                  actions={actions}
                />
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

      {/* Só aparece no papel. */}
      {printing && sheet !== null && items.length > 0 && (
        <PrintPortal>
          <PrintSheet items={items} rows={rows} lote={lote} day={day} />
        </PrintPortal>
      )}
    </section>
  );
}

/** Os campos de uma leitura guardada no celular. */
function queuedFields(item: QueuedReading): Partial<RowState> {
  return {
    value: show(item.producao),
    obs: item.observacao ?? "",
    noteOpen: Boolean(item.observacao),
  };
}
