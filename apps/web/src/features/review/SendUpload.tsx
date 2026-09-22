import { useEffect, useRef, useState, type FormEvent } from "react";

import { getImportReading, reprocessImport, uploadImport } from "../../api/client";
import {
  ApiError,
  type ImportReading,
  type ReadingFailure,
  type UploadResult,
} from "../../api/types";
import { AudioRecorder, browserRecorder, type RecorderApi } from "./AudioRecorder";
import { uploadErrorMessage } from "./uploadErrors";

/**
 * Enviar a foto da folha ou a gravação da ordenha pela própria Revisão, que é
 * onde o resultado aparece.
 *
 * A leitura é assíncrona de propósito: o envio responde na hora e o modelo lê
 * (ou ouve) depois, em segundo plano. A tela nunca fica travada esperando —
 * mas também não fica calada: ela pergunta ao servidor como está a leitura
 * até o fim, e diz o resultado. Antes, o aviso "as propostas aparecem aqui
 * quando terminar" ficava para sempre, mesmo quando a leitura tinha falhado,
 * e o funcionário saía do curral achando que estava tudo certo.
 *
 * Foto e gravação fazem o mesmo caminho, então é um formulário só; o que
 * muda são os textos, o que o campo de arquivo abre no celular (câmera ou
 * gravador) e, no áudio, o gravador dentro do próprio app.
 */

export type UploadFn = (
  input: { farmId: string; file: File; declaredLot?: string },
  token: string,
) => Promise<UploadResult>;
export type ReprocessFn = (importId: string, token: string) => Promise<UploadResult>;
export type WatchFn = (importId: string, token: string) => Promise<ImportReading>;

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
  /** Gravar dentro do app, quando o navegador deixa. */
  gravador: boolean;
  trabalhando: string;
  repetido: string;
  aindaTrabalhando: string;
  deNovo: string;
  /** "da folha", "da gravação": completa "N propostas ...". */
  daqui: string;
  vazio: string;
  foraDoAr: string;
  ilegivel: string;
  falhou: string;
  /** Mostrada só quando não há gravador no app (ou para a foto, sempre). */
  dica?: string;
}

export interface SendUploadProps {
  token: string;
  /** Resolvida no servidor por quem renderiza; ninguém digita isto. */
  farmId: string;
  onUpload?: UploadFn;
  onReprocess?: ReprocessFn;
  onWatch?: WatchFn;
  /** Avisa a caixa para reler a lista quando a leitura terminar. */
  onSent?: () => void;
  /** Dublê do gravador do navegador nos testes; `null`: sem gravador. */
  recorder?: RecorderApi | null;
  /** Pergunta antes de jogar fora uma gravação que não foi enviada. */
  confirmDiscard?: (message: string) => boolean;
}

/** Espera entre as perguntas ao servidor: rápido no começo, depois com calma. */
export const WATCH_STEPS_MS = [1500, 2000, 3000, 5000, 8000];
/** Depois disto, a tela para de perguntar e manda usar "Atualizar". */
export const WATCH_LIMIT_MS = 10 * 60 * 1000;

type State =
  | { status: "idle" }
  | { status: "sending" }
  | { status: "working"; importId: string }
  | { status: "done"; proposals: number }
  | { status: "failed"; importId: string; failure: ReadingFailure }
  | { status: "slow" }
  | { status: "duplicate"; importId: string; notice?: string }
  | { status: "error"; message: string };

const DISCARD = "Descartar a gravação? Ela ainda não foi enviada.";

function plural(n: number, um: string, varios: string): string {
  return `${n} ${n === 1 ? um : varios}`;
}

export function SendUpload({
  variant,
  token,
  farmId,
  onUpload = uploadImport,
  onReprocess = reprocessImport,
  onWatch = getImportReading,
  onSent,
  recorder,
  confirmDiscard = (message) => window.confirm(message),
}: SendUploadProps & { variant: Variant }): JSX.Element {
  const [open, setOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  // A gravação feita aqui só existe nesta tela até ser enviada.
  const [recorded, setRecorded] = useState(false);
  const [inputKey, setInputKey] = useState(0);
  const [lote, setLote] = useState("");
  const [state, setState] = useState<State>({ status: "idle" });
  const [hasRecorder, setHasRecorder] = useState(false);

  // O token é renovado enquanto a leitura roda: cada pergunta usa o atual.
  const currentToken = useRef(token);
  currentToken.current = token;
  const watching = state.status === "working" ? state.importId : null;

  useEffect(() => {
    if (watching === null) return;
    let cancelled = false;
    let timer: number | undefined;
    let step = 0;
    const started = Date.now();

    const next = (): void => {
      if (Date.now() - started >= WATCH_LIMIT_MS) {
        setState({ status: "slow" });
        return;
      }
      timer = window.setTimeout(ask, WATCH_STEPS_MS[Math.min(step, WATCH_STEPS_MS.length - 1)]);
      step += 1;
    };

    const ask = async (): Promise<void> => {
      try {
        const reading = await onWatch(watching, currentToken.current);
        if (cancelled) return;
        if (reading.status === "extracted") {
          setState({ status: "done", proposals: reading.proposals ?? 0 });
          onSent?.();
          return;
        }
        if (reading.status === "failed") {
          setState({ status: "failed", importId: watching, failure: reading.failure ?? "internal" });
          return;
        }
      } catch (error) {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 404) {
          setState({ status: "error", message: variant.falhou });
          return;
        }
        // Sem sinal por um instante: pergunta de novo no próximo passo.
      }
      next();
    };

    next();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [watching]);

  // Gravação feita e ainda não enviada: sair da página perderia o áudio.
  const unsent = recorded && file !== null;
  useEffect(() => {
    if (!unsent) return;
    const warn = (event: BeforeUnloadEvent): void => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [unsent]);

  function sent(importId: string): void {
    // Fecha o formulário: o aviso fica visível e o botão volta a ficar livre
    // para o próximo arquivo.
    setState({ status: "working", importId });
    setFile(null);
    setRecorded(false);
    setOpen(false);
  }

  async function send(event: FormEvent<HTMLFormElement>): Promise<void> {
    event.preventDefault();
    if (file === null) return;
    setState({ status: "sending" });
    try {
      const result = await onUpload(
        { farmId, file, declaredLot: variant.comLote && lote ? lote : undefined },
        token,
      );
      sent(result.id);
    } catch (error) {
      // O mesmo arquivo já está guardado: em vez de criar outra cópia, o
      // caminho certo é mandar ler de novo aquele.
      if (error instanceof ApiError && error.code === "duplicate_image") {
        setState({ status: "duplicate", importId: String(error.body.existing_import_id ?? "") });
        return;
      }
      // A gravação continua aqui: dá para tentar de novo quando o sinal voltar.
      setState({ status: "error", message: uploadErrorMessage(error, variant.arquivo) });
    }
  }

  async function readAgain(importId: string): Promise<void> {
    setState({ status: "sending" });
    try {
      await onReprocess(importId, token);
      sent(importId);
    } catch (error) {
      if (error instanceof ApiError && error.code === "import_already_processing") {
        setState({ status: "duplicate", importId, notice: variant.aindaTrabalhando });
        return;
      }
      if (error instanceof ApiError && error.code === "reprocess_needs_reviewer") {
        setState({
          status: "duplicate",
          importId,
          notice: `Ela já foi lida, e as propostas ${variant.daqui} estão na caixa. Só um revisor manda ler de novo.`,
        });
        return;
      }
      setState({ status: "error", message: "Não foi possível mandar ler de novo." });
    }
  }

  function cancel(): void {
    if (unsent && !confirmDiscard(DISCARD)) return;
    setFile(null);
    setRecorded(false);
    setOpen(false);
  }

  const outcome = <Outcome state={state} variant={variant} onTryAgain={(id) => void readAgain(id)} />;

  if (!open) {
    return (
      <div className={`send-photo send-${variant.id}`}>
        <button type="button" onClick={() => setOpen(true)}>
          {variant.abrir}
        </button>
        {outcome}
      </div>
    );
  }

  return (
    <form className={`send-photo send-${variant.id}`} onSubmit={(event) => void send(event)}>
      <h3>{variant.titulo}</h3>
      {variant.gravador && (
        <RecorderSlot
          recorder={recorder}
          onAvailable={setHasRecorder}
          onRecorded={(gravado) => {
            setFile(gravado);
            setRecorded(gravado !== null);
            // O campo de arquivo não pode mostrar um nome que não vale mais.
            if (gravado !== null) setInputKey((key) => key + 1);
          }}
        />
      )}
      <label htmlFor={variant.id}>{variant.rotulo}</label>
      <input
        key={inputKey}
        id={variant.id}
        type="file"
        accept={variant.accept}
        // No celular, abre direto a câmera (foto) ou o gravador (áudio).
        capture={variant.capture}
        onChange={(event) => {
          setFile(event.target.files?.[0] ?? null);
          setRecorded(false);
        }}
      />
      {variant.gravador && hasRecorder ? (
        <p className="hint">Ou escolha uma gravação feita em outro app.</p>
      ) : (
        variant.dica && <p className="hint">{variant.dica}</p>
      )}
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
        <button type="button" className="link-btn" onClick={cancel}>
          Cancelar
        </button>
      </div>

      {outcome}
    </form>
  );
}

/** O gravador só aparece quando o navegador deixa; avisa quem o contém. */
function RecorderSlot({
  recorder,
  onAvailable,
  onRecorded,
}: {
  recorder: RecorderApi | null | undefined;
  onAvailable: (available: boolean) => void;
  onRecorded: (file: File | null) => void;
}): JSX.Element | null {
  const [api] = useState(() => (recorder === undefined ? browserRecorder() : recorder));
  useEffect(() => onAvailable(api !== null), [api, onAvailable]);
  return api === null ? null : <AudioRecorder api={api} onRecorded={onRecorded} />;
}

function Outcome({
  state,
  variant,
  onTryAgain,
}: {
  state: State;
  variant: Variant;
  onTryAgain: (importId: string) => void;
}): JSX.Element | null {
  switch (state.status) {
    case "working":
      return (
        <p className="hint reading-live" aria-live="polite">
          <span className="reading-pulse" aria-hidden="true" />
          {variant.trabalhando}
        </p>
      );
    case "done":
      return state.proposals > 0 ? (
        <p role="status">
          Pronto: {plural(state.proposals, "proposta", "propostas")} {variant.daqui} esperando
          revisão, logo abaixo.
        </p>
      ) : (
        <p className="warning">{variant.vazio}</p>
      );
    case "failed":
      if (state.failure === "unreadable") return <p role="alert">{variant.ilegivel}</p>;
      return (
        <div className="warning reading-failed">
          <p>{state.failure === "reader_unavailable" ? variant.foraDoAr : variant.falhou}</p>
          <button type="button" className="btn-ghost" onClick={() => onTryAgain(state.importId)}>
            {variant.deNovo}
          </button>
        </div>
      );
    case "slow":
      return (
        <p className="warning">
          A leitura está demorando mais que o normal. Quando terminar, as propostas aparecem aqui —
          use Atualizar.
        </p>
      );
    case "duplicate":
      return (
        <div className="hint">
          <p>{variant.repetido}</p>
          {state.notice && <p>{state.notice}</p>}
          <button type="button" onClick={() => onTryAgain(state.importId)}>
            {variant.deNovo}
          </button>
        </div>
      );
    case "error":
      return <p role="alert">{state.message}</p>;
    default:
      return null;
  }
}
