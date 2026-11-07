/**
 * Foto e gravação sem sinal: o arquivo inteiro fica no aparelho e sobe
 * sozinho quando der. Antes, a gravação da ordenha se perdia ao sair da tela.
 */

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SendPhoto } from "./SendPhoto";
import { Outbox, memoryStore, type Senders } from "../../offline/outbox";
import { OutboxProvider } from "../../offline/OutboxContext";

const TOKEN = "token-de-teste";
const FARM = "f-1";
const USER = "u-joao";

function page(outbox: Outbox, send: Senders) {
  return render(
    <OutboxProvider outbox={outbox} userId={USER} token={TOKEN} renew={async () => null} send={send}>
      <SendPhoto token={TOKEN} farmId={FARM} onUpload={send.uploadImport} />
    </OutboxProvider>,
  );
}

async function sendPhoto(): Promise<File> {
  fireEvent.click(await screen.findByRole("button", { name: /ler foto da folha/i }));
  const file = new File(["folha do curral"], "folha.jpg", { type: "image/jpeg" });
  fireEvent.change(screen.getByLabelText(/foto da folha/i), { target: { files: [file] } });
  fireEvent.change(screen.getByLabelText(/lote/i), { target: { value: "LOTE 2" } });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /^enviar (áudio )?para leitura$/i }));
  });
  return file;
}

describe("Foto sem sinal", () => {
  it("fica guardada no aparelho, com o lote, e o formulário fecha", async () => {
    const outbox = new Outbox(memoryStore());
    const uploadImport = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    page(outbox, { enterReading: vi.fn(), uploadImport });

    const file = await sendPhoto();

    expect(await screen.findByRole("status")).toHaveTextContent(/a foto ficou guardada neste aparelho/i);
    expect(screen.queryByRole("button", { name: /^enviar (áudio )?para leitura$/i })).not.toBeInTheDocument();
    const [item] = await outbox.list(USER);
    expect(item).toMatchObject({ kind: "upload", arquivo: "foto", farmId: FARM, declaredLot: "LOTE 2", fileName: "folha.jpg" });
    expect(item.kind === "upload" && item.blob.size).toBe(file.size);
  });

  it("sobe sozinha quando o sinal volta", async () => {
    const outbox = new Outbox(memoryStore());
    const uploadImport = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    page(outbox, { enterReading: vi.fn(), uploadImport });
    await sendPhoto();

    uploadImport.mockResolvedValue({ id: "i-9", status: "queued" });
    await act(async () => {
      window.dispatchEvent(new Event("online"));
    });

    await waitFor(async () => expect(await outbox.list(USER)).toEqual([]));
    expect(uploadImport).toHaveBeenLastCalledWith(
      expect.objectContaining({ farmId: FARM, declaredLot: "LOTE 2" }),
      TOKEN,
    );
  });

  it("arquivo recusado pelo servidor não vai para a fila: a pessoa precisa saber já", async () => {
    const outbox = new Outbox(memoryStore());
    const { ApiError } = await import("../../api/types");
    const uploadImport = vi.fn().mockRejectedValue(new ApiError(413, { code: "upload_too_large" }));
    page(outbox, { enterReading: vi.fn(), uploadImport });

    await sendPhoto();

    expect(await screen.findByRole("alert")).toHaveTextContent(/pesada demais/i);
    expect(await outbox.list(USER)).toEqual([]);
  });
});
