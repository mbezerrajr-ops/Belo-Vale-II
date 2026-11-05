import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { IDBFactory, IDBObjectStore } from "fake-indexeddb";
import { indexedDbStore, Outbox, type Senders } from "./outbox";

beforeEach(() => vi.stubGlobal("indexedDB", new IDBFactory()));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("persistência real da fila", () => {
  it("reabrir o banco conserva produção e a foto", async () => {
    const first = new Outbox(indexedDbStore());
    await first.addReading({ userId: "ana", farmId: "fazenda-a", animalId: "vaca-a", measuredOn: "2026-11-05", label: "027", producao: 21.5, observacao: "Conferir" });
    await first.addUpload({ userId: "ana", farmId: "fazenda-a", arquivo: "foto", fileName: "folha.jpg", blob: new Blob(["foto original"], { type: "image/jpeg" }) });
    const reopened = new Outbox(indexedDbStore());
    const items = await reopened.list("ana");
    expect(items).toHaveLength(2);
    expect(items).toEqual(expect.arrayContaining([
      expect.objectContaining({ farmId: "fazenda-a", producao: 21.5, observacao: "Conferir" }),
      expect.objectContaining({ farmId: "fazenda-a", fileName: "folha.jpg" }),
    ]));
    expect(await reopened.list("bia")).toEqual([]);
  });

  it("uma transação abortada não confirma nem perde o valor anterior", async () => {
    const outbox = new Outbox(indexedDbStore());
    const input = { userId: "ana", farmId: "a", animalId: "vaca", measuredOn: "2026-11-05", label: "027", producao: 20 };
    await outbox.addReading(input);
    const events = vi.fn(); outbox.subscribe(events);
    const put = IDBObjectStore.prototype.put;
    vi.spyOn(IDBObjectStore.prototype, "put").mockImplementation(function (this: IDBObjectStore, ...args) {
      const request = put.apply(this, args);
      request.addEventListener("success", () => this.transaction.abort());
      return request;
    });
    await expect(outbox.addReading({ ...input, producao: 30 })).rejects.toBeDefined();
    expect(events).not.toHaveBeenCalled();
    expect(await outbox.list("ana")).toEqual([expect.objectContaining({ producao: 20 })]);
  });

  it("cada envio leva a fazenda original, mesmo com duas fazendas na fila", async () => {
    const outbox = new Outbox(indexedDbStore());
    for (const farmId of ["a", "b"]) await outbox.addReading({ userId: "ana", farmId, animalId: `vaca-${farmId}`, measuredOn: "2026-11-05", label: "027", producao: 20 });
    const send: Senders = { enterReading: vi.fn().mockResolvedValue({ id: "m" }), uploadImport: vi.fn() };
    await outbox.flush({ userId: "ana", token: "sessão", send });
    expect(send.enterReading).toHaveBeenCalledWith("sessão", "vaca-a", "2026-11-05", 20, "a");
    expect(send.enterReading).toHaveBeenCalledWith("sessão", "vaca-b", "2026-11-05", 20, "b");
    expect(await outbox.list("ana")).toEqual([]);
  });
});
