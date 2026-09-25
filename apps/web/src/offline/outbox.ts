import { ApiError, type Reading, type ReadingInput, type UploadResult } from "../api/types";

/**
 * O que foi lançado sem sinal fica guardado no celular até dar para enviar.
 *
 * No curral o sinal vai e volta. Antes, uma produção digitada sem sinal
 * ficava só no campo (recarregar a perdia), e uma gravação da ordenha que
 * não subia se perdia ao sair da tela.
 *
 * Três regras:
 *
 * - **Reenviar é seguro.** O servidor responde 200 à mesma produção lançada
 *   de novo e "já enviada" ao mesmo arquivo: se o primeiro envio chegou e só
 *   a resposta se perdeu, nada se duplica.
 * - **Cada item é de quem lançou.** Vai só com a conta dessa pessoa: num
 *   celular emprestado, o lançamento de um não é gravado em nome de outro.
 * - **Nada some em silêncio.** O que o servidor recusa (valor diferente já
 *   lançado, arquivo que não é foto) fica na lista com o motivo, até a pessoa
 *   descartar.
 *
 * O token nunca é guardado aqui: quem envia usa o da sessão aberta.
 */

interface Base {
  id: string;
  userId: string;
  createdAt: string;
  /** Recusado pelo servidor: não é reenviado sozinho. */
  error?: string;
}

export interface QueuedReading extends Base {
  kind: "reading";
  animalId: string;
  /** Nome ou brinco, para a lista dizer de que vaca é. */
  label: string;
  measuredOn: string;
  /** Total do dia: a soma de manhã e tarde, quando lançadas separadas. */
  producao: number;
  manha?: number | null;
  tarde?: number | null;
  observacao?: string | null;
}

export interface QueuedUpload extends Base {
  kind: "upload";
  arquivo: "foto" | "gravação";
  farmId: string;
  blob: Blob;
  fileName: string;
  declaredLot?: string;
}

export type OutboxItem = QueuedReading | QueuedUpload;

export type OutboxEvent =
  | { type: "changed" }
  | { type: "sent"; item: QueuedReading; result: Reading }
  | { type: "sent"; item: QueuedUpload; result: UploadResult | null }
  | { type: "refused"; item: OutboxItem };

/** Onde a fila fica. No navegador, IndexedDB; nos testes, memória. */
export interface OutboxStore {
  all(): Promise<OutboxItem[]>;
  put(item: OutboxItem): Promise<void>;
  remove(id: string): Promise<void>;
}

export function memoryStore(): OutboxStore {
  const items = new Map<string, OutboxItem>();
  return {
    all: async () => [...items.values()],
    put: async (item) => {
      items.set(item.id, item);
    },
    remove: async (id) => {
      items.delete(id);
    },
  };
}

const DB_NAME = "belo-vale-outbox";
const STORE = "items";

function request<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export function indexedDbStore(): OutboxStore {
  let db: Promise<IDBDatabase> | null = null;
  const open = (): Promise<IDBDatabase> => {
    db ??= new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => {
        req.result.createObjectStore(STORE, { keyPath: "id" });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
    return db;
  };
  const tx = async (mode: IDBTransactionMode): Promise<IDBObjectStore> =>
    (await open()).transaction(STORE, mode).objectStore(STORE);
  return {
    all: async () => request((await tx("readonly")).getAll() as IDBRequest<OutboxItem[]>),
    put: async (item) => {
      await request((await tx("readwrite")).put(item));
    },
    remove: async (id) => {
      await request((await tx("readwrite")).delete(id));
    },
  };
}

export interface Senders {
  enterReading: (
    token: string,
    animalId: string,
    measuredOn: string,
    input: number | ReadingInput,
  ) => Promise<Reading>;
  uploadImport: (
    input: { farmId: string; file: File; declaredLot?: string },
    token: string,
  ) => Promise<UploadResult>;
}

export interface FlushOptions {
  userId: string;
  token: string;
  /** Token vencido depois de horas sem sinal: renova uma vez e tenta de novo. */
  renew?: () => Promise<string | null>;
  send: Senders;
}

/** Sem sinal, prazo estourado, servidor fora do ar: tentar de novo depois. */
export function isTransient(error: unknown): boolean {
  if (error instanceof TypeError) return true;
  if (error instanceof DOMException && (error.name === "AbortError" || error.name === "TimeoutError")) {
    return true;
  }
  if (error instanceof ApiError) return error.status >= 500 || error.status === 408 || error.status === 429;
  return false;
}

/**
 * Prazo para um envio com sinal fraco, que pode ficar pendurado sem erro.
 * Estourado, o pedido original segue sozinho; se ele chegar e o da fila
 * também, o servidor reconhece a repetição.
 */
export function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new DOMException("demorou demais", "TimeoutError")), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error: unknown) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

/**
 * Os mesmos prazos do envio direto (Produção e Enviar foto/áudio). Sem eles,
 * um envio pendurado segurava a fila inteira: todo disparo seguinte esperava
 * o mesmo envio, até recarregar a página.
 */
const READING_TIMEOUT_MS = 15_000;
const UPLOAD_TIMEOUT_MS = 90_000;

function refusal(item: OutboxItem, error: unknown): string {
  if (error instanceof ApiError) {
    const detail = (error.body as { detail?: unknown }).detail;
    if (item.kind === "reading" && error.status === 409 && typeof detail === "object" && detail) {
      const existing = (detail as { existing?: Reading }).existing;
      if (existing) {
        const who = existing.entered_by ? ` por ${existing.entered_by}` : "";
        return `Já havia ${String(existing.producao ?? "—").replace(".", ",")} L lançado${who}.`;
      }
    }
    if (item.kind === "upload" && (error.status === 413 || error.code === "upload_too_large")) {
      return "Arquivo grande demais para enviar.";
    }
    if (item.kind === "upload" && error.code === "invalid_image") {
      return item.arquivo === "foto" ? "O arquivo não é uma foto." : "O arquivo não é uma gravação.";
    }
    if (typeof detail === "string") return detail;
  }
  return "O sistema recusou este envio.";
}

export class Outbox {
  private listeners = new Set<(event: OutboxEvent) => void>();
  private flushing: Promise<void> | null = null;

  constructor(private readonly store: OutboxStore) {}

  subscribe(listener: (event: OutboxEvent) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private emit(event: OutboxEvent): void {
    this.listeners.forEach((listener) => listener(event));
  }

  async list(userId: string): Promise<OutboxItem[]> {
    const items = await this.store.all();
    return items
      .filter((item) => item.userId === userId)
      .sort((a, b) => a.createdAt.localeCompare(b.createdAt));
  }

  async addReading(item: Omit<QueuedReading, "id" | "kind" | "createdAt">): Promise<QueuedReading> {
    // Uma produção por vaca e dia: a nova digitação substitui a guardada.
    await this.removeReadings(item.userId, item.animalId, item.measuredOn);
    const queued: QueuedReading = { ...item, kind: "reading", id: newId(), createdAt: new Date().toISOString() };
    keepStorage();
    await this.store.put(queued);
    this.emit({ type: "changed" });
    return queued;
  }

  async addUpload(item: Omit<QueuedUpload, "id" | "kind" | "createdAt">): Promise<QueuedUpload> {
    const queued: QueuedUpload = { ...item, kind: "upload", id: newId(), createdAt: new Date().toISOString() };
    keepStorage();
    await this.store.put(queued);
    this.emit({ type: "changed" });
    return queued;
  }

  async discard(id: string): Promise<void> {
    await this.store.remove(id);
    this.emit({ type: "changed" });
  }

  /**
   * A produção daquela vaca e dia foi lançada direto: a guardada perdeu a
   * vez. Enviada depois, ela seria "valor diferente já lançado" e marcaria
   * como erro uma linha que está certa.
   */
  async dropReading(userId: string, animalId: string, measuredOn: string): Promise<void> {
    if (await this.removeReadings(userId, animalId, measuredOn)) this.emit({ type: "changed" });
  }

  private async removeReadings(userId: string, animalId: string, measuredOn: string): Promise<boolean> {
    let removed = false;
    for (const other of await this.store.all()) {
      if (
        other.kind === "reading" &&
        other.userId === userId &&
        other.animalId === animalId &&
        other.measuredOn === measuredOn
      ) {
        await this.store.remove(other.id);
        removed = true;
      }
    }
    return removed;
  }

  /** Envia o que der, em ordem. Para no primeiro sinal de rede ruim. */
  flush(options: FlushOptions): Promise<void> {
    // Um envio por vez: dois disparos juntos (volta do sinal e o relógio)
    // não mandam o mesmo item duas vezes.
    this.flushing ??= this.run(options).finally(() => {
      this.flushing = null;
    });
    return this.flushing;
  }

  private async run({ userId, token, renew, send }: FlushOptions): Promise<void> {
    let current = token;
    let renewed = false;
    for (const item of await this.list(userId)) {
      if (item.error) continue;
      try {
        await this.sendOne(item, current, send);
      } catch (error) {
        if (error instanceof ApiError && error.status === 401 && renew && !renewed) {
          renewed = true;
          const fresh = await renew().catch(() => null);
          if (fresh === null) return;
          current = fresh;
          try {
            await this.sendOne(item, current, send);
            continue;
          } catch (retryError) {
            error = retryError;
          }
        }
        if (isTransient(error) || (error instanceof ApiError && error.status === 401)) return;
        await this.store.put({ ...item, error: refusal(item, error) });
        this.emit({ type: "refused", item });
        this.emit({ type: "changed" });
      }
    }
  }

  private async sendOne(item: OutboxItem, token: string, send: Senders): Promise<void> {
    if (item.kind === "reading") {
      const result = await withTimeout(
        send.enterReading(token, item.animalId, item.measuredOn, queuedInput(item)),
        READING_TIMEOUT_MS,
      );
      await this.store.remove(item.id);
      this.emit({ type: "sent", item, result });
      this.emit({ type: "changed" });
      return;
    }
    const file = new File([item.blob], item.fileName, { type: item.blob.type });
    try {
      const result = await withTimeout(
        send.uploadImport({ farmId: item.farmId, file, declaredLot: item.declaredLot }, token),
        UPLOAD_TIMEOUT_MS,
      );
      await this.store.remove(item.id);
      this.emit({ type: "sent", item, result });
    } catch (error) {
      // O mesmo arquivo já está lá: o primeiro envio chegou.
      if (!(error instanceof ApiError && error.code === "duplicate_image")) throw error;
      await this.store.remove(item.id);
      this.emit({ type: "sent", item, result: null });
    }
    this.emit({ type: "changed" });
  }
}

/** O que reenviar. Itens guardados antes das ordenhas separadas têm só o total. */
function queuedInput(item: QueuedReading): number | ReadingInput {
  const parts: ReadingInput = {};
  if (item.manha != null) parts.manha = item.manha;
  if (item.tarde != null) parts.tarde = item.tarde;
  if (item.observacao) parts.observacao = item.observacao;
  if (Object.keys(parts).length === 0) return item.producao;
  if (parts.manha === undefined && parts.tarde === undefined) parts.producao = item.producao;
  return parts;
}

function newId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

/**
 * Pede ao navegador para não apagar a fila. O Safari do iPhone pode descartar
 * o que um site guardou quando ele fica dias sem uso; um lançamento guardado
 * sem sinal não pode sumir assim. Se o navegador negar, a fila funciona igual.
 */
function keepStorage(): void {
  void (navigator.storage?.persist?.() ?? Promise.resolve(false)).catch(() => false);
}

let shared: Outbox | null = null;

/** A fila deste celular. Sem IndexedDB (aba privada antiga), fica na memória. */
export function deviceOutbox(): Outbox {
  shared ??= new Outbox(typeof indexedDB === "undefined" ? memoryStore() : indexedDbStore());
  return shared;
}

/** Só para testes: começa cada teste com a fila vazia. */
export function resetDeviceOutbox(store: OutboxStore = memoryStore()): Outbox {
  shared = new Outbox(store);
  return shared;
}
