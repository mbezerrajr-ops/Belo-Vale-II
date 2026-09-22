/**
 * Enviar a gravação da ordenha pela própria Revisão.
 *
 * Mesmo caminho da foto: o envio responde na hora e o modelo ouve depois, em
 * segundo plano. O que muda para quem usa: o campo abre o gravador (e não a
 * câmera), não pede lote — na fala o lote é dito vaca a vaca —, e avisa que no
 * iPhone é preciso gravar no app Gravador e escolher o arquivo.
 */

import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../../api/types";
import { SendAudio } from "./SendAudio";

const TOKEN = "token-de-teste";
const FARM = "f-1";

function setup(props = {}) {
  const onUpload = vi.fn().mockResolvedValue({ id: "i-1", status: "queued" });
  const onReprocess = vi.fn().mockResolvedValue({ id: "i-1", status: "queued" });
  const onSent = vi.fn();
  render(
    <SendAudio
      token={TOKEN}
      farmId={FARM}
      onUpload={onUpload}
      onReprocess={onReprocess}
      onSent={onSent}
      {...props}
    />,
  );
  return { onUpload, onReprocess, onSent };
}

function abrirEEscolher(): void {
  fireEvent.click(screen.getByRole("button", { name: /enviar [áa]udio/i }));
  const campo = screen.getByLabelText(/grava[çc][ãa]o da ordenha/i) as HTMLInputElement;
  const arquivo = new File(["m4a"], "ordenha.m4a", { type: "audio/mp4" });
  fireEvent.change(campo, { target: { files: [arquivo] } });
}

describe("Enviar a gravação pela Revisão", () => {
  it("manda a gravação e avisa que está ouvindo", async () => {
    const { onUpload, onSent } = setup();

    abrirEEscolher();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^enviar$/i }));
    });

    expect(onUpload).toHaveBeenCalledWith(
      expect.objectContaining({ farmId: FARM, file: expect.any(File) }),
      TOKEN,
    );
    expect(await screen.findByText(/ouvindo a grava[çc][ãa]o/i)).toBeInTheDocument();
    expect(onSent).toHaveBeenCalled();
  });

  it("o campo abre o gravador, não a câmera", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: /enviar [áa]udio/i }));

    const campo = screen.getByLabelText(/grava[çc][ãa]o da ordenha/i);
    expect(campo).toHaveAttribute("accept", "audio/*");
    expect(campo).toHaveAttribute("capture");
  });

  it("não pede lote: na fala ele é dito vaca a vaca", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: /enviar [áa]udio/i }));

    expect(screen.queryByLabelText(/lote/i)).not.toBeInTheDocument();
  });

  it("avisa como fazer no iPhone", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: /enviar [áa]udio/i }));

    expect(screen.getByText(/no iphone, grave no app gravador/i)).toBeInTheDocument();
  });

  it("a mesma gravação enviada duas vezes oferece ouvir de novo, sem duplicar", async () => {
    const onUpload = vi
      .fn()
      .mockRejectedValue(new ApiError(409, { code: "duplicate_image", existing_import_id: "i-antigo" }));
    const { onReprocess } = setup({ onUpload });

    abrirEEscolher();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^enviar$/i }));
    });

    expect(await screen.findByText(/esta grava[çc][ãa]o j[áa] foi enviada/i)).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /ouvir de novo/i }));
    });
    expect(onReprocess).toHaveBeenCalledWith("i-antigo", TOKEN);
  });

  it("gravação longa demais para o envio diz o que fazer", async () => {
    const onUpload = vi.fn().mockRejectedValue(new ApiError(413, { code: "upload_too_large" }));
    setup({ onUpload });

    abrirEEscolher();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^enviar$/i }));
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(/grave em peda[çc]os menores/i);
  });
});
