/**
 * Caixa de revisão: propostas lidas de fotos, áudios e textos.
 *
 * O que não pode falhar aqui:
 * - quem revisa vê o que foi lido e de onde veio, antes de decidir;
 * - só o brinco associa: nome lido vira sugestão, e aprovar exige um animal
 *   escolhido;
 * - corrigir um valor não apaga o que foi lido; a correção vai no envio;
 * - uma produção diferente da já lançada pede motivo para substituir;
 * - operador vê, mas só revisor decide.
 */

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ReviewInbox } from "./ReviewInbox";
import { ApiError, type AnimalSummary, type Proposal } from "../../api/types";

const TOKEN = "token-de-teste";

function animal(overrides: Partial<AnimalSummary> = {}): AnimalSummary {
  return {
    id: "a-389",
    brinco: "389",
    name: "ÁGATA",
    situacao: "Em lactação",
    lote_atual: "LOTE 1",
    grupo_manejo: null,
    exited_on: null,
    ...overrides,
  };
}

function proposal(overrides: Partial<Proposal> = {}): Proposal {
  return {
    id: "p-1",
    source: {
      id: "s-1",
      kind: "photo",
      label: "caderno de 25/08",
      reference_date: "2026-08-25",
      reference_date_read: "2026-08-25",
      corrected_by: null,
      media_url: null,
      extractor_name: "teste",
      created_at: "2026-09-18T10:00:00Z",
    },
    position: 1,
    event_type: "production",
    brinco_lido: "389",
    nome_lido: "Ágata",
    candidate: animal(),
    name_suggestions: [],
    payload: { measured_on: "2026-08-25", producao: 215 },
    raw_fields: { brinco: "389", nome: "Ágata", producao: "215" },
    evidence: { text: "389 Ágata 215" },
    confidence: { brinco: 0.95, producao: 0.4 },
    alerts: [{ code: "implausible_value", message: "215 L está fora do plausível.", field: "producao" }],
    status: "pending",
    version: 1,
    decided_by: null,
    decided_at: null,
    decision_reason: null,
    applied_payload: null,
    result: null,
    ...overrides,
  };
}

function setup(
  props: Partial<Parameters<typeof ReviewInbox>[0]> = {},
  items: Proposal[] = [proposal()],
) {
  const onList = vi.fn().mockResolvedValue(items);
  const onApprove = vi.fn().mockResolvedValue({ id: "p-1", status: "approved", result: {} });
  const onReject = vi.fn().mockResolvedValue(undefined);
  const onSearch = vi.fn().mockResolvedValue({ items: [], total: 0, limit: 25, offset: 0 });
  const onRedate = vi.fn().mockResolvedValue({ updated: 1, kept_decided: 0 });
  const onChanged = vi.fn();
  render(
    <ReviewInbox
      token={TOKEN}
      canDecide
      onList={onList}
      onApprove={onApprove}
      onReject={onReject}
      onSearch={onSearch}
      onRedate={onRedate}
      onChanged={onChanged}
      {...props}
    />,
  );
  return { onList, onApprove, onReject, onSearch, onRedate, onChanged };
}

async function card(): Promise<HTMLElement> {
  return (await screen.findByRole("article", { name: /produção|parto|baixa|observação/i })) as HTMLElement;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ReviewInbox", () => {
  it("mostra de onde veio, o que foi lido e o animal achado pelo brinco", async () => {
    setup();

    const item = await card();
    expect(screen.getByRole("heading", { name: /caderno de 25\/08/ })).toBeInTheDocument();
    expect(within(item).getByText("389 Ágata 215")).toBeInTheDocument();
    expect(within(item).getByText(/fora do plausível/i)).toBeInTheDocument();
    expect(within(item).getByText("ÁGATA")).toBeInTheDocument();
    expect(within(item).getByText(/confiança baixa/i)).toBeInTheDocument();
  });

  it("mostra as ordenhas lidas da folha de pesagem, para conferir a conta", async () => {
    setup({}, [
      proposal({
        payload: { measured_on: "2026-08-25", producao: 9.5 },
        raw_fields: { brinco: "016", nome: "BELMONTE", producao: "9,5", parcelas: "5 + 4" },
        alerts: [{ code: "sum_mismatch", message: "As ordenhas não fecham: 5 + 4 = 9, mas o total lido é 9,5 L." }],
      }),
    ]);

    const item = await card();
    expect(within(item).getByText(/ordenhas 5 \+ 4/)).toBeInTheDocument();
  });

  it("brinco de uma vaca com nome de outra oferece trocar num toque", async () => {
    const sariema = animal({ id: "a-447", brinco: "447", name: "SARIEMA" });
    const { onApprove } = setup({}, [
      proposal({
        brinco_lido: "B2-016",
        nome_lido: "SARIEMA",
        candidate: animal({ id: "a-016", brinco: "B2-016", name: "BELMONTE" }),
        name_suggestions: [sariema],
        payload: { measured_on: "2026-07-22", producao: 21 },
        alerts: [{ code: "name_mismatch", message: "Nome lido: SARIEMA; no cadastro: BELMONTE." }],
      }),
    ]);

    const item = await card();
    fireEvent.click(within(item).getByRole("button", { name: /ou é esta.*447.*sariema/i }));
    await act(async () => {
      fireEvent.click(within(item).getByRole("button", { name: /aprovar/i }));
    });

    expect(onApprove).toHaveBeenCalledWith(
      TOKEN,
      "p-1",
      expect.objectContaining({ animal_id: "a-447" }),
    );
  });

  it("revisor corrige os litros e aprova", async () => {
    const { onApprove, onChanged } = setup();

    const item = await card();
    fireEvent.change(within(item).getByLabelText(/litros/i), { target: { value: "21,5" } });
    await act(async () => {
      fireEvent.click(within(item).getByRole("button", { name: /aprovar/i }));
    });

    expect(onApprove).toHaveBeenCalledWith(TOKEN, "p-1", {
      expected_version: 1,
      animal_id: "a-389",
      payload: { measured_on: "2026-08-25", producao: 21.5 },
      replace_reason: null,
    });
    expect(onChanged).toHaveBeenCalled();
  });

  it("sem brinco, aprovar exige escolher o animal entre as sugestões pelo nome", async () => {
    const { onApprove } = setup({}, [
      proposal({
        brinco_lido: null,
        candidate: null,
        name_suggestions: [animal()],
        payload: { measured_on: "2026-08-25", producao: 20 },
        alerts: [{ code: "no_brinco", message: "Brinco não lido." }],
      }),
    ]);

    const item = await card();
    const approve = within(item).getByRole("button", { name: /aprovar/i });
    expect(approve).toBeDisabled();

    fireEvent.click(within(item).getByRole("button", { name: /é esta.*389/i }));
    expect(approve).toBeEnabled();
    await act(async () => {
      fireEvent.click(approve);
    });

    expect(onApprove).toHaveBeenCalledWith(
      TOKEN,
      "p-1",
      expect.objectContaining({ animal_id: "a-389" }),
    );
  });

  it("acha o animal pelo brinco quando a leitura não trouxe nenhum", async () => {
    const onSearch = vi.fn().mockResolvedValue({
      items: [{ ...animal({ id: "a-027", brinco: "027", name: "BORBOREMA" }), farm_id: "f", brinco_origem: null, legacy_id: null, numero_legado: null, status: "Ativo", ultimo_parto: null, nascimento: null, peso: null, observacoes: null }],
      total: 1,
      limit: 25,
      offset: 0,
    });
    setup({ onSearch }, [
      proposal({ brinco_lido: null, candidate: null, name_suggestions: [], payload: { measured_on: "2026-08-25", producao: 20 } }),
    ]);

    const item = await card();
    fireEvent.change(within(item).getByLabelText(/buscar pelo brinco/i), { target: { value: "027" } });
    await act(async () => {
      fireEvent.click(within(item).getByRole("button", { name: /^buscar$/i }));
    });

    await waitFor(() => expect(onSearch).toHaveBeenCalledWith(TOKEN, { brinco: "027" }));
    fireEvent.click(await within(item).findByRole("button", { name: /é esta.*027/i }));
    expect(within(item).getByRole("button", { name: /aprovar/i })).toBeEnabled();
  });

  it("produção diferente da já lançada pede motivo para substituir", async () => {
    const conflict = new ApiError(409, {
      code: "conflict",
      detail: {
        message: "Esta vaca já tem outra produção lançada nesta data.",
        existing: { id: "m-1", producao: 30, provenance: "manual_entry", entered_by: "joao@belovale" },
      },
    });
    const onApprove = vi
      .fn()
      .mockRejectedValueOnce(conflict)
      .mockResolvedValue({ id: "p-1", status: "approved", result: {} });
    setup({ onApprove }, [proposal({ payload: { measured_on: "2026-08-25", producao: 21.5 }, alerts: [] })]);

    const item = await card();
    await act(async () => {
      fireEvent.click(within(item).getByRole("button", { name: /aprovar/i }));
    });

    expect(await within(item).findByText(/já lançado: 30 L por joao@belovale/i)).toBeInTheDocument();
    fireEvent.change(within(item).getByLabelText(/motivo para substituir/i), {
      target: { value: "caderno confere" },
    });
    await act(async () => {
      fireEvent.click(within(item).getByRole("button", { name: /substituir e aprovar/i }));
    });

    expect(onApprove).toHaveBeenLastCalledWith(
      TOKEN,
      "p-1",
      expect.objectContaining({ replace_reason: "caderno confere" }),
    );
  });

  it("rejeitar pede motivo", async () => {
    const { onReject } = setup();

    const item = await card();
    fireEvent.click(within(item).getByRole("button", { name: /^rejeitar$/i }));
    const confirm = within(item).getByRole("button", { name: /confirmar rejeição/i });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(item).getByLabelText(/motivo da rejeição/i), {
      target: { value: "leitura de um rabisco" },
    });
    await act(async () => {
      fireEvent.click(confirm);
    });

    expect(onReject).toHaveBeenCalledWith(TOKEN, "p-1", 1, "leitura de um rabisco");
  });

  it("parto calculado por DEL mostra o aviso para confirmar", async () => {
    setup({}, [
      proposal({
        event_type: "calving",
        payload: { calved_on: "2026-04-27" },
        alerts: [{ code: "derived_from_del", message: "Data de parto calculada a partir de DEL 120." }],
      }),
    ]);

    const item = await card();
    expect(within(item).getByText(/calculada a partir de DEL 120/i)).toBeInTheDocument();
    expect(within(item).getByLabelText(/data do parto/i)).toHaveValue("2026-04-27");
  });

  it("baixa oferece os motivos fechados", async () => {
    const { onApprove } = setup({}, [
      proposal({
        event_type: "exit",
        payload: { exited_on: "2026-08-25", reason: null, notes: "pro vizinho" },
        alerts: [],
      }),
    ]);

    const item = await card();
    fireEvent.change(within(item).getByLabelText(/motivo da baixa/i), { target: { value: "venda" } });
    await act(async () => {
      fireEvent.click(within(item).getByRole("button", { name: /aprovar/i }));
    });

    expect(onApprove).toHaveBeenCalledWith(
      TOKEN,
      "p-1",
      expect.objectContaining({
        payload: { exited_on: "2026-08-25", reason: "venda", notes: "pro vizinho" },
      }),
    );
  });

  it("operador vê a caixa, mas não decide", async () => {
    setup({ canDecide: false });

    const item = await card();
    expect(within(item).queryByRole("button", { name: /aprovar/i })).not.toBeInTheDocument();
    expect(screen.getByText(/um revisor aprova/i)).toBeInTheDocument();
  });

  it("caixa vazia explica de onde vêm as propostas", async () => {
    setup({}, []);

    expect(await screen.findByText(/nada esperando revisão/i)).toBeInTheDocument();
  });

  it("as decididas mostram quem decidiu", async () => {
    const onList = vi.fn(async (_token: string, status: string) =>
      status === "approved"
        ? [
            proposal({
              status: "approved",
              decided_by: "maria@belovale",
              decided_at: "2026-09-18T11:00:00Z",
              applied_payload: { measured_on: "2026-08-25", producao: 21.5 },
            }),
          ]
        : [],
    );
    setup({ onList });

    fireEvent.click(await screen.findByRole("button", { name: /aprovadas/i }));

    expect(await screen.findByText(/maria@belovale/)).toBeInTheDocument();
    expect(screen.getByText(/Data da coleta: 25\/08\/2026 · Litros: 21,5 L/)).toBeInTheDocument();
    expect(onList).toHaveBeenLastCalledWith(TOKEN, "approved");
  });
});

function fromSource(id: string, label: string, overrides: Partial<Proposal> = {}): Proposal {
  const base = proposal();
  return proposal({
    id: `p-${id}-${overrides.position ?? 1}`,
    source: { ...base.source, id, label },
    ...overrides,
  });
}

describe("ReviewInbox — arquivos", () => {
  it("tem um botão para cada arquivo, que filtra a revisão", async () => {
    setup({}, [
      fromSource("s-1", "Folha 3º lote", { brinco_lido: "389" }),
      fromSource("s-1", "Folha 3º lote", { brinco_lido: "853", position: 2 }),
      fromSource("s-2", "Áudio do Zé", { brinco_lido: "701" }),
    ]);

    const files = await screen.findByRole("group", { name: "Arquivos" });
    expect(within(files).getByRole("button", { name: /todos.*3/i })).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(within(files).getByRole("button", { name: /áudio do zé.*1/i }));

    expect(screen.queryByRole("article", { name: /389/ })).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: /701/ })).toBeInTheDocument();

    fireEvent.click(within(files).getByRole("button", { name: /todos/i }));
    expect(screen.getAllByRole("article")).toHaveLength(3);
  });

  it("troca a data do arquivo inteiro de uma vez", async () => {
    const { onRedate, onList, onChanged } = setup({}, [
      fromSource("s-1", "Folha 3º lote", { brinco_lido: "389" }),
      fromSource("s-1", "Folha 3º lote", { brinco_lido: "853", position: 2 }),
    ]);

    fireEvent.click(await screen.findByRole("button", { name: /trocar data do arquivo/i }));
    fireEvent.change(screen.getByLabelText(/nova data do arquivo/i), {
      target: { value: "2026-08-26" },
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /aplicar às 2 pendentes/i }));
    });

    expect(onRedate).toHaveBeenCalledWith(TOKEN, "s-1", "2026-08-26");
    expect(onList).toHaveBeenCalledTimes(2);
    expect(onChanged).toHaveBeenCalled();
  });

  it("mostra a data lida e quem corrigiu", async () => {
    const base = proposal();
    setup({}, [
      proposal({
        source: {
          ...base.source,
          reference_date: "2026-08-25",
          reference_date_read: "2024-08-25",
          corrected_by: "maria@belovale",
        },
      }),
    ]);

    await card();
    expect(screen.getByText(/lida como 25\/08\/2024.*maria@belovale/i)).toBeInTheDocument();
  });

  it("operador não troca a data", async () => {
    setup({ canDecide: false });

    await card();
    expect(screen.queryByRole("button", { name: /trocar data do arquivo/i })).not.toBeInTheDocument();
  });
});

describe("ReviewInbox — o que chegou enquanto a caixa estava aberta", () => {
  // Quem revisa deixa a caixa aberta enquanto o funcionário manda fotos e
  // gravações do curral. Sem aviso, só apertando "Atualizar" se descobria o
  // que chegou. E a tela não pode se reorganizar sozinha no meio de uma
  // revisão: o aviso oferece mostrar, e quem revisa decide quando.
  const ESPERA = 30_000;

  async function passar(ms: number): Promise<void> {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ms);
    });
  }

  it("avisa quantas chegaram, sem mexer na tela, e mostra quando pedirem", async () => {
    vi.useFakeTimers();
    try {
      const primeira = proposal();
      const nova = proposal({ id: "p-2", brinco_lido: "633", nome_lido: "GIGANTE" });
      const onList = vi.fn().mockResolvedValueOnce([primeira]).mockResolvedValue([primeira, nova]);
      const { onChanged } = setup({ onList });
      await passar(0);
      expect(screen.getAllByRole("article")).toHaveLength(1);

      await passar(ESPERA);

      expect(screen.getByRole("status")).toHaveTextContent(/chegou 1 proposta nova/i);
      expect(screen.getAllByRole("article")).toHaveLength(1); // nada se mexeu sozinho
      expect(onChanged).toHaveBeenCalled(); // o contador da navegação atualiza
      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: /mostrar agora/i }));
      });
      expect(screen.getAllByRole("article")).toHaveLength(2);
      expect(screen.queryByText(/chegou 1 proposta nova/i)).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("avisa também o que outra pessoa já decidiu", async () => {
    vi.useFakeTimers();
    try {
      const primeira = proposal();
      const outra = proposal({ id: "p-2", brinco_lido: "633", nome_lido: "GIGANTE" });
      const onList = vi.fn().mockResolvedValueOnce([primeira, outra]).mockResolvedValue([primeira]);
      setup({ onList });
      await passar(0);

      await passar(ESPERA);

      expect(screen.getByRole("status")).toHaveTextContent(/1 já foi decidida por outra pessoa/i);
    } finally {
      vi.useRealTimers();
    }
  });

  it("sem novidade, não avisa nada", async () => {
    vi.useFakeTimers();
    try {
      const { onList } = setup();
      await passar(0);

      await passar(ESPERA * 2);

      expect(onList.mock.calls.length).toBeGreaterThan(1);
      expect(screen.queryByRole("status")).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("não pergunta com a tela escondida", async () => {
    vi.useFakeTimers();
    const visibilidade = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    try {
      const { onList } = setup();
      await passar(0);
      const chamadas = onList.mock.calls.length;

      await passar(ESPERA * 3);

      expect(onList.mock.calls.length).toBe(chamadas);
    } finally {
      visibilidade.mockRestore();
      vi.useRealTimers();
    }
  });
});
