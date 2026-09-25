import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, type Reading } from "../api/types";
import { Outbox, memoryStore, type OutboxEvent, type Senders } from "./outbox";

const USER = "u-1";

function reading(overrides: Partial<Reading> = {}): Reading {
  return {
    id: "m-1",
    animal_id: "a-1",
    measured_on: "2026-09-22",
    producao: 18,
    provenance: "manual_entry",
    entered_by: "joao@belovale",
    supersedes: null,
    created_at: "2026-09-22T10:00:00Z",
    ...overrides,
  };
}

function senders(overrides: Partial<Senders> = {}): Senders {
  return {
    enterReading: vi.fn().mockResolvedValue(reading()),
    uploadImport: vi.fn().mockResolvedValue({ id: "i-1", status: "queued" }),
    ...overrides,
  };
}

async function withReading(outbox: Outbox, userId = USER, animalId = "a-1", producao = 18): Promise<void> {
  await outbox.addReading({ userId, animalId, label: "BORBOREMA", measuredOn: "2026-09-22", producao });
}

describe("fila do celular", () => {
  it("envia o que estava guardado e tira da fila", async () => {
    const outbox = new Outbox(memoryStore());
    const events: OutboxEvent[] = [];
    outbox.subscribe((event) => events.push(event));
    await withReading(outbox);
    const send = senders();

    await outbox.flush({ userId: USER, token: "t", send });

    expect(send.enterReading).toHaveBeenCalledWith("t", "a-1", "2026-09-22", 18);
    expect(await outbox.list(USER)).toEqual([]);
    expect(events.some((event) => event.type === "sent")).toBe(true);
  });

  it("sem sinal, guarda e para de tentar os próximos", async () => {
    const outbox = new Outbox(memoryStore());
    await withReading(outbox, USER, "a-1");
    await withReading(outbox, USER, "a-2");
    const enterReading = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));

    await outbox.flush({ userId: USER, token: "t", send: senders({ enterReading }) });

    expect(enterReading).toHaveBeenCalledTimes(1);
    expect(await outbox.list(USER)).toHaveLength(2);
  });

  it("servidor fora do ar também espera, sem marcar como recusado", async () => {
    const outbox = new Outbox(memoryStore());
    await withReading(outbox);

    await outbox.flush({
      userId: USER,
      token: "t",
      send: senders({ enterReading: vi.fn().mockRejectedValue(new ApiError(502, { code: "server_error" })) }),
    });

    const [item] = await outbox.list(USER);
    expect(item.error).toBeUndefined();
  });

  it("valor diferente já lançado fica na lista com o motivo, e não é reenviado", async () => {
    const outbox = new Outbox(memoryStore());
    await withReading(outbox);
    const conflict = new ApiError(409, {
      code: "conflict",
      detail: { message: "outro valor", existing: reading({ producao: 30.5, entered_by: "maria@belovale" }) },
    });
    const enterReading = vi.fn().mockRejectedValue(conflict);

    await outbox.flush({ userId: USER, token: "t", send: senders({ enterReading }) });
    await outbox.flush({ userId: USER, token: "t", send: senders({ enterReading }) });

    const [item] = await outbox.list(USER);
    expect(item.error).toBe("Já havia 30,5 L lançado por maria@belovale.");
    expect(enterReading).toHaveBeenCalledTimes(1);
  });

  it("token vencido depois de horas sem sinal: renova e envia", async () => {
    const outbox = new Outbox(memoryStore());
    await withReading(outbox);
    const enterReading = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(401, { code: "unauthorized" }))
      .mockResolvedValue(reading());
    const renew = vi.fn().mockResolvedValue("t-novo");

    await outbox.flush({ userId: USER, token: "t-velho", renew, send: senders({ enterReading }) });

    expect(enterReading).toHaveBeenLastCalledWith("t-novo", "a-1", "2026-09-22", 18);
    expect(await outbox.list(USER)).toEqual([]);
  });

  it("sessão encerrada: não renova, não descarta, espera o próximo login", async () => {
    const outbox = new Outbox(memoryStore());
    await withReading(outbox);

    await outbox.flush({
      userId: USER,
      token: "t",
      renew: vi.fn().mockResolvedValue(null),
      send: senders({ enterReading: vi.fn().mockRejectedValue(new ApiError(401, { code: "unauthorized" })) }),
    });

    const [item] = await outbox.list(USER);
    expect(item.error).toBeUndefined();
  });

  it("cada lançamento vai só com a conta de quem lançou", async () => {
    const outbox = new Outbox(memoryStore());
    await withReading(outbox, "u-joao");
    const send = senders();

    await outbox.flush({ userId: "u-maria", token: "t-maria", send });

    expect(send.enterReading).not.toHaveBeenCalled();
    expect(await outbox.list("u-joao")).toHaveLength(1);
    expect(await outbox.list("u-maria")).toEqual([]);
  });

  it("digitar de novo a mesma vaca e dia substitui o valor guardado", async () => {
    const outbox = new Outbox(memoryStore());
    await withReading(outbox, USER, "a-1", 18);
    await withReading(outbox, USER, "a-1", 19.5);

    const items = await outbox.list(USER);
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ producao: 19.5 });
  });

  it("lançado direto: sai da fila só a produção daquela vaca, dia e conta", async () => {
    const outbox = new Outbox(memoryStore());
    await withReading(outbox, USER, "a-1");
    await withReading(outbox, USER, "a-2");
    await withReading(outbox, "u-outra", "a-1");
    await outbox.addReading({ userId: USER, animalId: "a-1", label: "BORBOREMA", measuredOn: "2026-09-21", producao: 17 });

    await outbox.dropReading(USER, "a-1", "2026-09-22");

    const sobram = (await outbox.list(USER)).map((item) => item.kind === "reading" && `${item.animalId} ${item.measuredOn}`);
    expect(sobram.sort()).toEqual(["a-1 2026-09-21", "a-2 2026-09-22"]);
    expect(await outbox.list("u-outra")).toHaveLength(1);
  });

  it("a gravação guardada sobe inteira; se já tinha chegado, sai da fila", async () => {
    const outbox = new Outbox(memoryStore());
    const blob = new Blob(["áudio da ordenha"], { type: "audio/webm" });
    await outbox.addUpload({ userId: USER, arquivo: "gravação", farmId: "f-1", blob, fileName: "ordenha.webm" });
    const uploadImport = vi.fn().mockRejectedValue(new ApiError(409, { code: "duplicate_image" }));

    await outbox.flush({ userId: USER, token: "t", send: senders({ uploadImport }) });

    const sent = uploadImport.mock.calls[0][0].file as File;
    expect(sent.name).toBe("ordenha.webm");
    expect(sent.size).toBe(blob.size);
    expect(await outbox.list(USER)).toEqual([]);
  });

  describe("envio pendurado (sinal fraco, sem erro nem resposta)", () => {
    afterEach(() => {
      vi.useRealTimers();
    });

    const nunca = () => new Promise<never>(() => {});

    it("a produção desiste no prazo, fica guardada e vai no disparo seguinte", async () => {
      vi.useFakeTimers();
      const outbox = new Outbox(memoryStore());
      await withReading(outbox);
      const enterReading = vi.fn().mockImplementationOnce(nunca).mockResolvedValue(reading());
      const send = senders({ enterReading });

      let terminou = false;
      void outbox.flush({ userId: USER, token: "t", send }).then(() => {
        terminou = true;
      });
      await vi.advanceTimersByTimeAsync(5 * 60_000);

      expect(terminou).toBe(true);
      const [guardado] = await outbox.list(USER);
      expect(guardado.error).toBeUndefined();

      await outbox.flush({ userId: USER, token: "t", send });
      expect(enterReading).toHaveBeenCalledTimes(2);
      expect(await outbox.list(USER)).toEqual([]);
    });

    it("a foto ou gravação desiste no prazo e fica guardada", async () => {
      vi.useFakeTimers();
      const outbox = new Outbox(memoryStore());
      const blob = new Blob(["foto da folha"], { type: "image/jpeg" });
      await outbox.addUpload({ userId: USER, arquivo: "foto", farmId: "f-1", blob, fileName: "folha.jpg" });
      const uploadImport = vi.fn().mockImplementationOnce(nunca);

      let terminou = false;
      void outbox.flush({ userId: USER, token: "t", send: senders({ uploadImport }) }).then(() => {
        terminou = true;
      });
      await vi.advanceTimersByTimeAsync(5 * 60_000);

      expect(terminou).toBe(true);
      const [guardado] = await outbox.list(USER);
      expect(guardado.error).toBeUndefined();
    });
  });

  it("dois disparos juntos não enviam o mesmo item duas vezes", async () => {
    const outbox = new Outbox(memoryStore());
    await withReading(outbox);
    const send = senders();

    await Promise.all([
      outbox.flush({ userId: USER, token: "t", send }),
      outbox.flush({ userId: USER, token: "t", send }),
    ]);

    expect(send.enterReading).toHaveBeenCalledTimes(1);
  });
});
