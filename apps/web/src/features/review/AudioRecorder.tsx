import { useEffect, useRef, useState } from "react";

/**
 * Gravar a ordenha dentro do próprio app.
 *
 * Até aqui o funcionário gravava no app do celular e depois escolhia o
 * arquivo — e no iPhone o campo de arquivo nem abre gravador. O gravador do
 * navegador resolve os dois: aperta, fala, para, ouve o que gravou e envia.
 *
 * Só existe em conexão segura (https, ou a própria máquina): fora disso o
 * navegador nem oferece o microfone, e a tela fica só com o campo de arquivo,
 * como antes. O formato é o do navegador — MP4 no Safari, WebM no Chrome, Ogg
 * no Firefox —, e o servidor aceita os três.
 */

/** O mesmo limite padrão do worker (AUDIO_MAX_SECONDS): além disso, ele corta. */
export const MAX_RECORDING_SECONDS = 300;

/** Do mais aceito para o menos: MP4 toca no navegador de qualquer revisor. */
const PREFERRED_TYPES = [
  "audio/mp4",
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
];

/** O que a tela usa do gravador do navegador; nos testes, um dublê. */
export interface RecorderLike {
  readonly mimeType: string;
  readonly state: string;
  ondataavailable: ((event: { data: Blob }) => void) | null;
  onstop: (() => void) | null;
  onerror: ((event: unknown) => void) | null;
  start(): void;
  stop(): void;
}

export interface RecorderApi {
  getUserMedia(constraints: MediaStreamConstraints): Promise<MediaStream>;
  create(stream: MediaStream, mimeType: string | undefined): RecorderLike;
  isTypeSupported(type: string): boolean;
  /**
   * Mantém a tela acesa enquanto grava. No celular a tela apaga sozinha em
   * meio minuto, e com ela a gravação para. `null` quando não há como.
   */
  keepAwake?(): Promise<{ release(): Promise<void> } | null>;
}

/** O gravador deste navegador, ou `null` se não houver (ou se não for https). */
export function browserRecorder(): RecorderApi | null {
  if (typeof window === "undefined" || !window.isSecureContext) return null;
  if (typeof window.MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) {
    return null;
  }
  return {
    getUserMedia: (constraints) => navigator.mediaDevices.getUserMedia(constraints),
    // 64 kbit/s: voz clara, e cinco minutos cabem em ~2,4 MB.
    create: (stream, mimeType) =>
      new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 64_000 }) as unknown as RecorderLike,
    isTypeSupported: (type) => MediaRecorder.isTypeSupported(type),
    keepAwake: async () => {
      const wakeLock = (navigator as Navigator & {
        wakeLock?: { request(type: "screen"): Promise<{ release(): Promise<void> }> };
      }).wakeLock;
      return wakeLock ? wakeLock.request("screen").catch(() => null) : null;
    },
  };
}

type Phase =
  | { kind: "idle" }
  | { kind: "asking" }
  | { kind: "recording" }
  | { kind: "recorded"; url: string | null; cut: boolean }
  | { kind: "error"; message: string };

interface Props {
  /** A gravação pronta para enviar — ou `null` quando ela é descartada. */
  onRecorded: (file: File | null) => void;
  /** Sem isto, o gravador do navegador. `null`: não há gravador. */
  api?: RecorderApi | null;
  maxSeconds?: number;
  now?: () => number;
}

function clock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

function extension(mime: string): string {
  if (mime.includes("mp4")) return "m4a";
  if (mime.includes("ogg")) return "ogg";
  return "webm";
}

/** "ordenha-2026-09-21-1714.webm": quem revisa reconhece pela hora. */
function fileName(mime: string, when: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  const day = `${when.getFullYear()}-${pad(when.getMonth() + 1)}-${pad(when.getDate())}`;
  return `ordenha-${day}-${pad(when.getHours())}${pad(when.getMinutes())}.${extension(mime)}`;
}

function microphoneMessage(error: unknown): string {
  const name = error instanceof DOMException || error instanceof Error ? error.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "O navegador não deixou usar o microfone. Libere o microfone para este site nas configurações do navegador, ou grave no app do celular e escolha o arquivo abaixo.";
  }
  if (name === "NotFoundError") {
    return "Nenhum microfone foi encontrado neste aparelho. Grave em outro aparelho e escolha o arquivo abaixo.";
  }
  return "Não foi possível começar a gravar. Tente de novo, ou grave no app do celular e escolha o arquivo abaixo.";
}

function release(stream: MediaStream | null): void {
  // Solta o microfone: sem isto o aviso de "gravando" do celular não some.
  stream?.getTracks().forEach((track) => track.stop());
}

export function AudioRecorder({
  onRecorded,
  api,
  maxSeconds = MAX_RECORDING_SECONDS,
  now = Date.now,
}: Props): JSX.Element | null {
  const [recorderApi] = useState<RecorderApi | null>(() =>
    api === undefined ? browserRecorder() : api,
  );
  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const [elapsed, setElapsed] = useState(0);
  const recorder = useRef<RecorderLike | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const chunks = useRef<Blob[]>([]);
  const startedAt = useRef(0);
  const cut = useRef(false);
  const url = useRef<string | null>(null);
  const alive = useRef(true);
  const awake = useRef<{ release(): Promise<void> } | null>(null);

  function letSleep(): void {
    void awake.current?.release().catch(() => undefined);
    awake.current = null;
  }

  function forgetTake(): void {
    if (url.current) URL.revokeObjectURL?.(url.current);
    url.current = null;
  }

  function stop(): void {
    if (recorder.current && recorder.current.state !== "inactive") recorder.current.stop();
  }

  function finish(mime: string): void {
    release(stream.current);
    letSleep();
    stream.current = null;
    recorder.current = null;
    if (!alive.current) return;
    const blob = new Blob(chunks.current, { type: mime });
    if (blob.size === 0) {
      setPhase({ kind: "error", message: "Nada foi gravado. Tente de novo." });
      return;
    }
    const type = mime.split(";")[0] || "audio/webm";
    const file = new File([blob], fileName(mime, new Date(startedAt.current)), { type });
    forgetTake();
    url.current = URL.createObjectURL?.(blob) ?? null;
    setPhase({ kind: "recorded", url: url.current, cut: cut.current });
    onRecorded(file);
  }

  async function start(): Promise<void> {
    if (recorderApi === null) return;
    setPhase({ kind: "asking" });
    onRecorded(null); // gravar de novo descarta a anterior
    forgetTake();
    let media: MediaStream;
    try {
      media = await recorderApi.getUserMedia({ audio: true });
    } catch (error) {
      if (alive.current) setPhase({ kind: "error", message: microphoneMessage(error) });
      return;
    }
    if (!alive.current) {
      release(media);
      return;
    }
    const preferred = PREFERRED_TYPES.find((type) => recorderApi.isTypeSupported(type));
    let created: RecorderLike;
    try {
      created = recorderApi.create(media, preferred);
    } catch (error) {
      release(media);
      setPhase({ kind: "error", message: microphoneMessage(error) });
      return;
    }
    chunks.current = [];
    cut.current = false;
    created.ondataavailable = (event) => {
      if (event.data && event.data.size > 0) chunks.current.push(event.data);
    };
    created.onstop = () => finish(created.mimeType || preferred || "audio/webm");
    created.onerror = () => {
      release(media);
      letSleep();
      if (alive.current) {
        setPhase({ kind: "error", message: "A gravação parou por um erro do navegador. Tente de novo." });
      }
    };
    recorder.current = created;
    stream.current = media;
    created.start();
    // Tela apagada no meio da gravação a interromperia.
    void recorderApi.keepAwake?.().then((lock) => {
      if (lock && (!alive.current || recorder.current !== created)) void lock.release();
      else awake.current = lock;
    });
    startedAt.current = now();
    setElapsed(0);
    setPhase({ kind: "recording" });
  }

  // O cronômetro — e o corte no limite, para o worker não cortar sozinho.
  useEffect(() => {
    if (phase.kind !== "recording") return;
    const timer = window.setInterval(() => {
      const seconds = (now() - startedAt.current) / 1000;
      setElapsed(seconds);
      if (seconds >= maxSeconds) {
        cut.current = true;
        stop();
      }
    }, 250);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [phase.kind, maxSeconds]);

  // Saiu da tela no meio da gravação: para e solta o microfone.
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      if (recorder.current && recorder.current.state !== "inactive") recorder.current.stop();
      release(stream.current);
      letSleep();
      forgetTake();
    };
  }, []);

  if (recorderApi === null) return null;

  return (
    <div className="recorder">
      {phase.kind === "recording" ? (
        <div className="recorder-live">
          <span className="recorder-dot" aria-hidden="true" />
          <span className="recorder-time">
            Gravando {clock(elapsed)} <small>de {clock(maxSeconds)}</small>
          </span>
          <button type="button" className="recorder-stop" onClick={stop}>
            Parar
          </button>
        </div>
      ) : phase.kind === "recorded" ? (
        <div className="recorder-take">
          {phase.url && <audio controls src={phase.url} aria-label="Ouvir o que foi gravado" />}
          <button type="button" className="btn-ghost" onClick={() => void start()}>
            Gravar de novo
          </button>
          {phase.cut && (
            <p className="hint">
              A gravação parou em {clock(maxSeconds)}, o limite. Envie esta e grave o resto em outra.
            </p>
          )}
        </div>
      ) : (
        <button
          type="button"
          className="recorder-start"
          disabled={phase.kind === "asking"}
          onClick={() => void start()}
        >
          <span className="recorder-dot" aria-hidden="true" />
          {phase.kind === "asking" ? "Abrindo o microfone…" : "Gravar agora"}
        </button>
      )}
      {phase.kind === "error" && <p role="alert">{phase.message}</p>}
    </div>
  );
}
