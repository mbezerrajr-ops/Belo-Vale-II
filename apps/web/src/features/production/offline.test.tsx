/**
 * Lançar sem sinal, no curral.
 *
 * O valor digitado sem sinal vai para a fila do celular: sobrevive a sair da
 * tela e a recarregar, aparece na linha da vaca como guardado, e vira
 * lançado quando o envio atrasado passa.
 */

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProductionPage } from "./ProductionPage";
import { ApiError, type ProductionSheet, type Reading } from "../../api/types";
import { Outbox, memoryStore, type Senders } from "../../offline/outbox";
import { OutboxProvider } from "../../offline/OutboxContext";

const TOKEN = "token-de-teste";
const DAY = "2026-09-18";
const USER = "u-joao";

function sheet(): ProductionSheet {
  return {
    measured_on: DAY,
    lote: "LOTE 1",
    lotes: ["LOTE 1"],
    items: [
      {
        animal_id: "a-027",
        brinco: "027",
        name: "BORBOREMA",
        situacao: "Em lactação",
        producao: null,
        measurement_id: null,
        provenance: null,
      },
    ],
  };
}

function reading(producao = 21.5): Reading {
  return {
    id: "m-1",
    animal_id: "a-027",
    measured_on: DAY,
    producao,
    provenance: "manual_entry",
    entered_by: "joao@belovale",
    supersedes: null,
    created_at: "2026-09-18T09:00:00Z",
  };
}

const offline = (): Promise<Reading> => Promise.reject(new TypeError("Failed to fetch"));

function page(outbox: Outbox, send: Senders, onLoadSheet = vi.fn().mockResolvedValue(sheet())) {
  return render(
    <OutboxProvider outbox={outbox} userId={USER} token={TOKEN} renew={async () => null} send={send}>
      <ProductionPage
        token={TOKEN}
        canCorrect={false}
        today={DAY}
        onLoadSheet={onLoadSheet}
        onEnter={send.enterReading}
      />
    </OutboxProvider>,
  );
}

afterEach(() => {
  sessionStorage.clear();
});

describe("Produção sem sinal", () => {
  it("sem sinal, guarda no celular em vez de pedir para tentar de novo", async () => {
    const outbox = new Outbox(memoryStore());
    const send: Senders = { enterReading: vi.fn(offline), uploadImport: vi.fn() };
    page(outbox, send);

    const field = await screen.findByLabelText("Litros de BORBOREMA");
    fireEvent.change(field, { target: { value: "21,5" } });
    fireEvent.blur(field);

    expect(await screen.findByText(/guardado neste celular/i)).toBeInTheDocument();
    expect(screen.getByLabelText("guardado no celular")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /tentar de novo/i })).not.toBeInTheDocument();
    expect(await outbox.list(USER)).toEqual([
      expect.objectContaining({ animalId: "a-027", measuredOn: DAY, producao: 21.5, label: "BORBOREMA" }),
    ]);
    expect(screen.getByText(/1 guardada no celular/i)).toBeInTheDocument();
  });

  it("recarregar a tela não perde o valor guardado", async () => {
    const outbox = new Outbox(memoryStore());
    await outbox.addReading({ userId: USER, animalId: "a-027", label: "BORBOREMA", measuredOn: DAY, producao: 19 });
    page(outbox, { enterReading: vi.fn(offline), uploadImport: vi.fn() });

    const field = await screen.findByLabelText("Litros de BORBOREMA");
    await waitFor(() => expect(field).toHaveValue("19"));
    expect(screen.getByLabelText("guardado no celular")).toBeInTheDocument();
  });

  it("quando o sinal volta, o guardado vira lançado", async () => {
    const outbox = new Outbox(memoryStore());
    const enterReading = vi.fn(offline);
    page(outbox, { enterReading, uploadImport: vi.fn() });

    const field = await screen.findByLabelText("Litros de BORBOREMA");
    fireEvent.change(field, { target: { value: "21,5" } });
    fireEvent.blur(field);
    await screen.findByLabelText("guardado no celular");

    enterReading.mockResolvedValue(reading(21.5));
    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });

    await waitFor(() => expect(screen.getByLabelText("salvo")).toBeInTheDocument());
    expect(await outbox.list(USER)).toEqual([]);
    expect(screen.getByText(/1 de 1 lançadas/i)).toBeInTheDocument();
  });

  it("sem sinal ao abrir, usa a folha vista por último", async () => {
    const outbox = new Outbox(memoryStore());
    const send: Senders = { enterReading: vi.fn(offline), uploadImport: vi.fn() };
    const first = page(outbox, send);
    await screen.findByLabelText("Litros de BORBOREMA");
    first.unmount();

    page(outbox, send, vi.fn(offline));

    expect(await screen.findByLabelText("Litros de BORBOREMA")).toBeInTheDocument();
    expect(screen.getByText(/folha guardada/i)).toBeInTheDocument();
  });

  it("a observação também fica guardada no celular", async () => {
    const outbox = new Outbox(memoryStore());
    page(outbox, { enterReading: vi.fn(offline), uploadImport: vi.fn() });

    fireEvent.click(await screen.findByRole("button", { name: "Anotar observação de BORBOREMA" }));
    fireEvent.change(screen.getByLabelText("Litros de BORBOREMA"), { target: { value: "7" } });
    const note = screen.getByLabelText("Observação de BORBOREMA");
    fireEvent.change(note, { target: { value: "→ Seca" } });
    fireEvent.blur(note);

    await screen.findByLabelText("guardado no celular");
    expect(await outbox.list(USER)).toEqual([
      expect.objectContaining({ animalId: "a-027", producao: 7, observacao: "→ Seca" }),
    ]);
  });

  it("lançado direto depois de guardado: o valor antigo sai da fila e não volta como erro", async () => {
    const outbox = new Outbox(memoryStore());
    await outbox.addReading({ userId: USER, animalId: "a-027", label: "BORBOREMA", measuredOn: DAY, producao: 19 });
    let online = false;
    // O servidor, depois do lançamento direto, já tem 23 L: os 19 da fila
    // seriam "valor diferente já lançado".
    const enterReading = vi.fn(async (_t: string, _a: string, _d: string, input: unknown) => {
      if (!online) throw new TypeError("Failed to fetch");
      if (input === 19) {
        throw new ApiError(409, { code: "conflict", detail: { message: "outro valor", existing: reading(23) } });
      }
      return reading(23);
    });
    const send: Senders = { enterReading, uploadImport: vi.fn() };
    page(outbox, send);
    await screen.findByLabelText("guardado no celular");

    online = true;
    const field = screen.getByLabelText("Litros de BORBOREMA");
    fireEvent.change(field, { target: { value: "23" } });
    fireEvent.blur(field);
    await screen.findByLabelText("salvo");

    enterReading.mockClear();
    await act(async () => {
      await outbox.flush({ userId: USER, token: TOKEN, send });
    });

    expect(enterReading).not.toHaveBeenCalled();
    expect(await outbox.list(USER)).toEqual([]);
    expect(screen.getByLabelText("salvo")).toBeInTheDocument();
    expect(screen.queryByText(/não enviado/i)).not.toBeInTheDocument();
  });

  it("valor que o servidor recusa aparece na linha, com o motivo", async () => {
    const outbox = new Outbox(memoryStore());
    await outbox.addReading({ userId: USER, animalId: "a-027", label: "BORBOREMA", measuredOn: DAY, producao: 19 });
    const all = await outbox.list(USER);
    await memoryPut(outbox, { ...all[0], error: "Já havia 30 L lançado por maria@belovale." });

    page(outbox, { enterReading: vi.fn(offline), uploadImport: vi.fn() });

    expect(await screen.findByText(/não enviado: já havia 30 l/i)).toBeInTheDocument();
  });
});

/** Marca um item como recusado, pelo mesmo caminho que o envio faria. */
async function memoryPut(outbox: Outbox, item: Awaited<ReturnType<Outbox["list"]>>[number]): Promise<void> {
  await (outbox as unknown as { store: { put: (i: typeof item) => Promise<void> } }).store.put(item);
}
