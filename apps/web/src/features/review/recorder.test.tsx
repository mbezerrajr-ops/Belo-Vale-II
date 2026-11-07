/**
 * Gravar a ordenha dentro do próprio app.
 *
 * Aperta, fala, para, ouve o que gravou e envia — sem sair da Revisão e sem
 * procurar arquivo. No iPhone é o único jeito de gravar pelo app: o Safari
 * não abre gravador num campo de arquivo.
 *
 * O que não pode acontecer: perder a gravação. Ela só existe na tela até ser
 * enviada — por isso o envio que falha deixa a gravação ali para tentar de
 * novo, cancelar pergunta antes, e sair da página avisa.
 */

import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AudioRecorder, type RecorderApi, type RecorderLike } from "./AudioRecorder";
import { SendAudio } from "./SendAudio";

const TOKEN = "token-de-teste";
const FARM = "f-1";

class GravadorFalso implements RecorderLike {
  state = "inactive";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;

  constructor(readonly mimeType: string) {}

  start(): void {
    this.state = "recording";
  }

  stop(): void {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["som da ordenha"], { type: this.mimeType }) });
    this.onstop?.();
  }
}

function microfone() {
  const faixa = { stop: vi.fn() };
  const stream = { getTracks: () => [faixa] } as unknown as MediaStream;
  const gravadores: GravadorFalso[] = [];
  const api: RecorderApi = {
    getUserMedia: vi.fn().mockResolvedValue(stream),
    create: vi.fn((_: MediaStream, mimeType: string | undefined) => {
      const gravador = new GravadorFalso(mimeType ?? "audio/webm");
      gravadores.push(gravador);
      return gravador;
    }),
    isTypeSupported: (type: string) => type === "audio/webm;codecs=opus",
  };
  return { api, faixa, gravadores };
}

function setup(props = {}) {
  const { api, faixa, gravadores } = microfone();
  const onUpload = vi.fn().mockResolvedValue({ id: "i-1", status: "queued" });
  const onWatch = vi.fn().mockResolvedValue({
    id: "i-1",
    kind: "audio",
    status: "pending",
    proposals: null,
    failure: null,
  });
  const confirmDiscard = vi.fn(() => true);
  const view = render(
    <SendAudio
      token={TOKEN}
      farmId={FARM}
      onUpload={onUpload}
      onWatch={onWatch}
      recorder={api}
      confirmDiscard={confirmDiscard}
      {...props}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: /enviar [áa]udio/i }));
  return { api, faixa, gravadores, onUpload, confirmDiscard, view };
}

async function gravarEParar(): Promise<void> {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /gravar agora/i }));
  });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: /parar/i }));
  });
}

beforeEach(() => {
  vi.stubGlobal(
    "URL",
    Object.assign(URL, {
      createObjectURL: vi.fn(() => "blob:gravacao"),
      revokeObjectURL: vi.fn(),
    }),
  );
});

describe("Gravar a ordenha no próprio app", () => {
  it("grava, para, deixa ouvir e envia a gravação", async () => {
    const { onUpload } = setup();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /gravar agora/i }));
    });
    expect(screen.getByText(/gravando 0:00/i)).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /parar/i }));
    });

    const tocador = screen.getByLabelText(/ouvir o que foi gravado/i);
    expect(tocador).toHaveAttribute("src", "blob:gravacao");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^enviar (áudio )?para leitura$/i }));
    });

    const [[{ file }]] = onUpload.mock.calls;
    expect(file.name).toMatch(/^ordenha-\d{4}-\d{2}-\d{2}-\d{4}\.webm$/);
    expect(file.type).toBe("audio/webm");
    expect(await screen.findByText(/ouvindo a grava[çc][ãa]o/i)).toBeInTheDocument();
  });

  it("solta o microfone quando para", async () => {
    const { faixa } = setup();

    await gravarEParar();

    expect(faixa.stop).toHaveBeenCalled();
  });

  it("mantém a tela acesa enquanto grava, e deixa apagar depois", async () => {
    // No celular a tela apaga sozinha em meio minuto, e com ela a gravação para.
    const { api } = microfone();
    const trava = { release: vi.fn().mockResolvedValue(undefined) };
    api.keepAwake = vi.fn().mockResolvedValue(trava);
    setup({ recorder: api });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /gravar agora/i }));
    });
    expect(api.keepAwake).toHaveBeenCalled();
    expect(trava.release).not.toHaveBeenCalled();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /parar/i }));
    });

    expect(trava.release).toHaveBeenCalled();
  });

  it("grava no formato que o navegador sabe gravar", async () => {
    const { api } = setup();

    await gravarEParar();

    expect(api.create).toHaveBeenCalledWith(expect.anything(), "audio/webm;codecs=opus");
  });

  it("gravar de novo descarta a anterior", async () => {
    setup();
    await gravarEParar();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /gravar de novo/i }));
    });

    expect(screen.getByRole("button", { name: /^enviar (áudio )?para leitura$/i })).toBeDisabled();
  });

  it("microfone negado explica o que fazer, e o campo de arquivo continua ali", async () => {
    const { api } = microfone();
    api.getUserMedia = vi.fn().mockRejectedValue(new DOMException("negado", "NotAllowedError"));
    setup({ recorder: api });

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /gravar agora/i }));
    });

    expect(screen.getByRole("alert")).toHaveTextContent(/libere o microfone/i);
    expect(screen.getByLabelText(/grava[çc][ãa]o da ordenha/i)).toBeInTheDocument();
  });
});

describe("Quando o navegador não grava", () => {
  it("sem gravador (ou sem https), fica o campo de arquivo e a dica do iPhone", () => {
    setup({ recorder: null });

    expect(screen.queryByRole("button", { name: /gravar agora/i })).not.toBeInTheDocument();
    expect(screen.getByText(/no iphone, grave no app gravador/i)).toBeInTheDocument();
  });

  it("com gravador, a dica do iPhone dá lugar à de outro app", () => {
    setup();

    expect(screen.queryByText(/no iphone, grave no app gravador/i)).not.toBeInTheDocument();
    expect(screen.getByText(/escolha uma grava[çc][ãa]o feita em outro app/i)).toBeInTheDocument();
  });
});

describe("A gravação não se perde", () => {
  it("o envio que falha deixa a gravação ali para tentar de novo", async () => {
    const onUpload = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValue({ id: "i-1", status: "queued" });
    setup({ onUpload });
    await gravarEParar();

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^enviar (áudio )?para leitura$/i }));
    });
    expect(screen.getByRole("alert")).toHaveTextContent(/confira a conex[ãa]o/i);
    expect(screen.getByLabelText(/ouvir o que foi gravado/i)).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^enviar (áudio )?para leitura$/i }));
    });

    expect(onUpload).toHaveBeenCalledTimes(2);
    expect(onUpload.mock.calls[1][0].file).toBe(onUpload.mock.calls[0][0].file);
  });

  it("cancelar com uma gravação não enviada pergunta antes", async () => {
    const confirmDiscard = vi.fn(() => false);
    setup({ confirmDiscard });
    await gravarEParar();

    fireEvent.click(screen.getByRole("button", { name: /cancelar/i }));

    expect(confirmDiscard).toHaveBeenCalledWith(expect.stringMatching(/ainda n[ãa]o foi enviada/i));
    expect(screen.getByLabelText(/ouvir o que foi gravado/i)).toBeInTheDocument();
  });

  it("sair da página com uma gravação não enviada avisa", async () => {
    setup();
    await gravarEParar();

    const saida = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(saida);

    expect(saida.defaultPrevented).toBe(true);
  });

  it("depois de enviada, sair da página não avisa mais", async () => {
    setup();
    await gravarEParar();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^enviar (áudio )?para leitura$/i }));
    });

    const saida = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(saida);

    expect(saida.defaultPrevented).toBe(false);
  });

  it("sair da tela no meio da gravação solta o microfone", async () => {
    const { faixa, view } = setup();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /gravar agora/i }));
    });

    view.unmount();

    expect(faixa.stop).toHaveBeenCalled();
  });
});

describe("O limite de duração", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("para sozinho no limite e diz por quê", async () => {
    const { api } = microfone();
    let agora = 0;
    const onRecorded = vi.fn();
    render(<AudioRecorder api={api} onRecorded={onRecorded} maxSeconds={2} now={() => agora} />);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /gravar agora/i }));
    });
    agora = 2_100;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });

    expect(onRecorded).toHaveBeenLastCalledWith(expect.any(File));
    expect(screen.getByText(/parou em 0:02, o limite/i)).toBeInTheDocument();
  });
});
