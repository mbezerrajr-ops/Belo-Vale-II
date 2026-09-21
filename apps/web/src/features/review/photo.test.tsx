/**
 * Enviar a foto da folha pela própria Revisão, que é onde o resultado
 * aparece — uma tela a menos para o funcionário aprender.
 *
 * A leitura é assíncrona: o app não trava esperando o modelo. Enquanto ela
 * não termina, a tela diz isso; se a mesma foto já foi enviada, oferece ler
 * de novo em vez de criar outra cópia.
 */

import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewInbox } from "./ReviewInbox";
import { ApiError, type Proposal } from "../../api/types";

const TOKEN = "token-de-teste";
const FARM = "f-1";

function base(): Proposal {
  return {
    id: "p-1",
    source: {
      id: "s-1",
      kind: "photo",
      label: "Foto de 20/09/2026 14:10",
      reference_date: "2026-09-20",
      reference_date_read: "2026-09-20",
      corrected_by: null,
      media_url: null,
      extractor_name: "leitor-local-folha",
      created_at: "2026-09-20T14:10:00Z",
    },
    position: 1,
    event_type: "production",
    brinco_lido: "389",
    nome_lido: "ÁGATA",
    candidate: {
      id: "a-389",
      brinco: "389",
      name: "ÁGATA",
      situacao: "Em lactação",
      lote_atual: "LOTE 1",
      grupo_manejo: null,
      exited_on: null,
    },
    name_suggestions: [],
    payload: { measured_on: "2026-09-20", producao: 20 },
    raw_fields: { brinco: "389", nome: "ÁGATA", producao: "20" },
    evidence: { text: "389 ÁGATA 20" },
    confidence: {},
    alerts: [],
    status: "pending",
    version: 1,
    decided_by: null,
    decided_at: null,
    applied_payload: null,
    decision_reason: null,
    result: null,
  };
}

function setup(props = {}, items: Proposal[] = [base()]) {
  const onList = vi.fn().mockResolvedValue(items);
  const onUpload = vi.fn().mockResolvedValue({ id: "i-1", status: "queued" });
  const onReprocess = vi.fn().mockResolvedValue({ id: "i-1", status: "queued" });
  render(
    <ReviewInbox
      token={TOKEN}
      farmId={FARM}
      canDecide
      onList={onList}
      onUpload={onUpload}
      onReprocess={onReprocess}
      onApprove={vi.fn()}
      onReject={vi.fn()}
      onSearch={vi.fn().mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 })}
      onRedate={vi.fn()}
      onChanged={vi.fn()}
      {...props}
    />,
  );
  return { onList, onUpload, onReprocess };
}

function chooseFile(): void {
  const input = screen.getByLabelText(/foto da folha/i) as HTMLInputElement;
  const file = new File(["conteudo"], "folha.jpg", { type: "image/jpeg" });
  fireEvent.change(input, { target: { files: [file] } });
}

describe("Enviar foto pela Revisão", () => {
  it("manda a foto e avisa que a leitura está em andamento", async () => {
    const { onUpload } = setup();

    fireEvent.click(await screen.findByRole("button", { name: /enviar foto/i }));
    chooseFile();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^enviar$/i }));
    });

    expect(onUpload).toHaveBeenCalledWith(
      expect.objectContaining({ farmId: FARM, file: expect.any(File) }),
      TOKEN,
    );
    expect(await screen.findByText(/lendo a folha/i)).toBeInTheDocument();
  });

  it("a mesma foto enviada duas vezes oferece ler de novo, sem duplicar", async () => {
    const onUpload = vi
      .fn()
      .mockRejectedValue(
        new ApiError(409, { code: "duplicate_image", existing_import_id: "i-antigo" }),
      );
    const { onReprocess } = setup({ onUpload });

    fireEvent.click(await screen.findByRole("button", { name: /enviar foto/i }));
    chooseFile();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^enviar$/i }));
    });

    expect(await screen.findByText(/j[áa] foi enviada/i)).toBeInTheDocument();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /ler de novo/i }));
    });
    expect(onReprocess).toHaveBeenCalledWith("i-antigo", TOKEN);
  });

  it("uma falha no envio não deixa a tela em silêncio", async () => {
    const onUpload = vi.fn().mockRejectedValue(new Error("sem rede"));
    setup({ onUpload });

    fireEvent.click(await screen.findByRole("button", { name: /enviar foto/i }));
    chooseFile();
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /^enviar$/i }));
    });

    expect(await screen.findByRole("alert")).toHaveTextContent(/n[ãa]o foi poss[íi]vel enviar/i);
  });
});

describe("A folha e a gravação ao lado das propostas", () => {
  // O arquivo vem da própria API, com o login: o navegador não manda o token
  // num <img src> comum, então a tela busca e mostra como blob:. Até a fase 2c
  // o link apontava para o armazenamento interno, que navegador nenhum abria —
  // e o teste só conferia o endereço, nunca se ele abria.
  const URL_ARQUIVO = "/api/proposals/sources/s-1/media";

  beforeEach(() => {
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: vi.fn(() => "blob:arquivo"),
      revokeObjectURL: vi.fn(),
    }));
  });

  it("mostra a folha de onde a leitura saiu, buscada com o login", async () => {
    const item = base();
    item.source.media_url = URL_ARQUIVO;
    const onFetchMedia = vi.fn().mockResolvedValue(new Blob(["x"], { type: "image/jpeg" }));
    setup({ onFetchMedia }, [item]);

    const foto = await screen.findByRole("link", { name: /ver a folha/i });
    expect(foto).toHaveAttribute("href", "blob:arquivo");
    expect(onFetchMedia).toHaveBeenCalledWith(URL_ARQUIVO, TOKEN);
  });

  it("uma gravação vira um tocador, não um link de imagem", async () => {
    const item = base();
    item.source.kind = "audio";
    item.source.media_url = URL_ARQUIVO;
    const onFetchMedia = vi.fn().mockResolvedValue(new Blob(["x"], { type: "audio/mp4" }));
    setup({ onFetchMedia }, [item]);

    const tocador = await screen.findByLabelText(/ouvir a grava[çc][ãa]o/i);
    expect(tocador.tagName).toBe("AUDIO");
    expect(tocador).toHaveAttribute("src", "blob:arquivo");
    expect(screen.queryByRole("link", { name: /ver a folha/i })).not.toBeInTheDocument();
  });

  it("um arquivo que não abre avisa, em vez de sumir", async () => {
    const item = base();
    item.source.media_url = URL_ARQUIVO;
    setup({ onFetchMedia: vi.fn().mockRejectedValue(new Error("404")) }, [item]);

    expect(await screen.findByText(/n[ãa]o foi poss[íi]vel abrir o arquivo/i)).toBeInTheDocument();
  });

  it("leitura sem arquivo não mostra nada", async () => {
    setup();

    await screen.findByRole("article");
    expect(screen.queryByRole("link", { name: /ver a folha/i })).not.toBeInTheDocument();
  });
});

describe("Atualizar a caixa", () => {
  it("relê a lista sem trocar de aba", async () => {
    // A leitura termina em segundo plano: sem isto, quem enviou a foto fica
    // olhando uma tela parada, porque clicar na aba já selecionada não
    // recarrega nada.
    const { onList } = setup();

    await screen.findByRole("article");
    const antes = onList.mock.calls.length;
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /atualizar/i }));
    });

    expect(onList.mock.calls.length).toBeGreaterThan(antes);
  });
});
