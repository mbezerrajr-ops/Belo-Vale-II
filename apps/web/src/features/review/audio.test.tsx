/**
 * Enviar a gravação da ordenha pela própria Revisão.
 *
 * Mesmo caminho da foto: o envio responde na hora e o modelo ouve depois, em
 * segundo plano. O que muda para quem usa: o campo abre o gravador (e não a
 * câmera), não pede lote — na fala o lote é dito vaca a vaca —, e avisa que no
 * iPhone é preciso gravar no app Gravador e escolher o arquivo.
 */

import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, type ImportReading } from "../../api/types";
import { SendAudio } from "./SendAudio";
import { WATCH_LIMIT_MS } from "./SendUpload";

const TOKEN = "token-de-teste";
const FARM = "f-1";

function leitura(parcial: Partial<ImportReading> = {}): ImportReading {
  return { id: "i-1", kind: "audio", status: "pending", proposals: null, failure: null, ...parcial };
}

function setup(props = {}) {
  const onUpload = vi.fn().mockResolvedValue({ id: "i-1", status: "queued" });
  const onReprocess = vi.fn().mockResolvedValue({ id: "i-1", status: "queued" });
  const onWatch = vi.fn().mockResolvedValue(leitura());
  const onSent = vi.fn();
  const view = render(
    <SendAudio
      token={TOKEN}
      farmId={FARM}
      onUpload={onUpload}
      onReprocess={onReprocess}
      onWatch={onWatch}
      onSent={onSent}
      recorder={null}
      {...props}
    />,
  );
  return { onUpload, onReprocess, onWatch, onSent, view };
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
    // A caixa só é relida quando a leitura terminar: antes disso não há nada novo.
    expect(onSent).not.toHaveBeenCalled();
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

/** Espera o tempo passar e as respostas chegarem, com o relógio falso. */
async function passar(ms: number): Promise<void> {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

async function enviarGravacao(): Promise<void> {
  abrirEEscolher();
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /^enviar$/i }));
  });
}

describe("Acompanhar a leitura até o fim", () => {
  // Antes, "as propostas aparecem aqui quando terminar" ficava na tela para
  // sempre — mesmo com a leitura falhada. O funcionário saía do curral achando
  // que estava tudo certo.
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("quando termina, diz quantas propostas saíram e relê a caixa", async () => {
    const onWatch = vi
      .fn()
      .mockResolvedValueOnce(leitura({ status: "processing" }))
      .mockResolvedValue(leitura({ status: "extracted", proposals: 4 }));
    const { onSent } = setup({ onWatch });

    await enviarGravacao();
    await passar(1600);
    expect(screen.getByText(/ouvindo a grava[çc][ãa]o/i)).toBeInTheDocument();
    await passar(2100);

    expect(screen.getByRole("status")).toHaveTextContent(/pronto: 4 propostas da grava[çc][ãa]o/i);
    expect(onSent).toHaveBeenCalledTimes(1);
    expect(onWatch).toHaveBeenCalledWith("i-1", TOKEN);
  });

  it("gravação sem vaca nenhuma pede para gravar de novo", async () => {
    setup({ onWatch: vi.fn().mockResolvedValue(leitura({ status: "extracted", proposals: 0 })) });

    await enviarGravacao();
    await passar(1600);

    expect(screen.getByText(/nenhuma vaca foi entendida/i)).toBeInTheDocument();
  });

  it("transcritor fora do ar: a gravação ficou guardada, e dá para tentar de novo", async () => {
    const onWatch = vi
      .fn()
      .mockResolvedValueOnce(leitura({ status: "failed", failure: "reader_unavailable" }))
      .mockResolvedValue(leitura({ status: "pending" }));
    const { onReprocess } = setup({ onWatch });

    await enviarGravacao();
    await passar(1600);
    expect(screen.getByText(/fora do ar/i)).toHaveTextContent(/ficou guardada/i);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /ouvir de novo/i }));
    });

    expect(onReprocess).toHaveBeenCalledWith("i-1", TOKEN);
    expect(screen.getByText(/ouvindo a grava[çc][ãa]o/i)).toBeInTheDocument();
  });

  it("gravação sem fala pede para gravar de novo, sem oferecer ouvir a mesma", async () => {
    setup({ onWatch: vi.fn().mockResolvedValue(leitura({ status: "failed", failure: "unreadable" })) });

    await enviarGravacao();
    await passar(1600);

    expect(screen.getByRole("alert")).toHaveTextContent(/grave de novo/i);
    expect(screen.queryByRole("button", { name: /ouvir de novo/i })).not.toBeInTheDocument();
  });

  it("sem sinal por um instante, continua perguntando", async () => {
    const onWatch = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValue(leitura({ status: "extracted", proposals: 1 }));
    setup({ onWatch });

    await enviarGravacao();
    await passar(1600);
    await passar(2100);

    expect(screen.getByRole("status")).toHaveTextContent(/1 proposta da grava[çc][ãa]o/i);
  });

  it("o token renovado vale para a próxima pergunta", async () => {
    const { onWatch, view } = setup();

    await enviarGravacao();
    await passar(1600);
    view.rerender(
      <SendAudio
        token="token-renovado"
        farmId={FARM}
        onUpload={vi.fn()}
        onWatch={onWatch}
        recorder={null}
      />,
    );
    await passar(2100);

    expect(onWatch).toHaveBeenLastCalledWith("i-1", "token-renovado");
  });

  it("depois de dez minutos, para de perguntar e manda usar Atualizar", async () => {
    const { onWatch } = setup();

    await enviarGravacao();
    await passar(WATCH_LIMIT_MS + 10_000);
    const chamadas = onWatch.mock.calls.length;
    await passar(60_000);

    expect(screen.getByText(/demorando mais que o normal/i)).toBeInTheDocument();
    expect(onWatch.mock.calls.length).toBe(chamadas);
  });

  it("ao sair da tela, para de perguntar", async () => {
    const { onWatch, view } = setup();

    await enviarGravacao();
    await passar(1600);
    const chamadas = onWatch.mock.calls.length;
    view.unmount();
    await passar(30_000);

    expect(onWatch.mock.calls.length).toBe(chamadas);
  });
});

describe("Gravação mais longa que o limite", () => {
  // O worker ouve só os primeiros 5 minutos. O gravador do app para sozinho;
  // um arquivo escolhido do celular não, e o resto era cortado sem aviso.
  it("avisa na hora de escolher, e deixa enviar mesmo assim", async () => {
    const measureDuration = vi.fn().mockResolvedValue(7 * 60 + 12);
    setup({ measureDuration });

    abrirEEscolher();
    await act(async () => {}); // a medida da duração chega

    expect(measureDuration).toHaveBeenCalledWith(expect.any(File));
    expect(screen.getByText(/tem 7:12; s[óo] os primeiros 5:00 ser[ãa]o ouvidos/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^enviar$/i })).toBeEnabled();
  });

  it("dentro do limite, não avisa nada", async () => {
    setup({ measureDuration: vi.fn().mockResolvedValue(4 * 60) });

    abrirEEscolher();
    await act(async () => {}); // a medida da duração chega

    expect(screen.queryByText(/primeiros 5:00/i)).not.toBeInTheDocument();
  });

  it("sem como medir, não avisa nada", async () => {
    setup({ measureDuration: vi.fn().mockResolvedValue(null) });

    abrirEEscolher();
    await act(async () => {}); // a medida da duração chega

    expect(screen.queryByText(/primeiros 5:00/i)).not.toBeInTheDocument();
  });
});
