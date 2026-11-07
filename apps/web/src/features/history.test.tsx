/**
 * Histórico e consulta: produção na ficha do animal, histórico de preço dos
 * insumos e o aviso de primeiro acesso ao criar conta.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnimalDetailPanel } from "./animals/AnimalDetailPanel";
import { SuppliesPage } from "./dashboard/SuppliesPage";
import { UsersPage } from "./users/UsersPage";
import type { AnimalDetail, ProductionHistoryEntry, Supply } from "../api/types";

const TOKEN = "token-de-teste";

function animal(): AnimalDetail {
  return {
    id: "a-1",
    farm_id: "f-1",
    brinco: "389",
    brinco_origem: "389",
    legacy_id: null,
    numero_legado: null,
    name: "ÁGATA",
    situacao: "Em lactação",
    status: "Ativo",
    ultimo_parto: null,
    nascimento: null,
    peso: null,
    observacoes: null,
    lote_atual: "LOTE 1",
    grupo_manejo: null,
    historico_lotes: [],
  };
}

function entry(overrides: Partial<ProductionHistoryEntry>): ProductionHistoryEntry {
  return {
    id: "m-1",
    measured_on: "2026-09-10",
    producao: 21.5,
    status: "active",
    provenance: "manual_entry",
    responsible: "joao@belovale",
    created_at: "2026-09-10T09:00:00Z",
    supersedes: null,
    source: null,
    reason: null,
    lote_observado: "LOTE 1",
    ...overrides,
  };
}

const HISTORY: ProductionHistoryEntry[] = [
  entry({ id: "m-3", measured_on: "2026-09-10", producao: 12, supersedes: "m-2", reason: "anotado errado", responsible: "maria@belovale" }),
  entry({ id: "m-2", measured_on: "2026-09-10", producao: 21.5, status: "superseded" }),
  entry({ id: "m-4", measured_on: "2026-08-25", producao: 30, provenance: "file_import", source: "agosto.csv", reason: "dados normalizados" }),
  entry({ id: "m-1", measured_on: "2026-07-22", producao: 20, provenance: "legacy_baseline", responsible: "titular" }),
];

afterEach(() => {
  vi.restoreAllMocks();
});

function renderDetail(props: Partial<Parameters<typeof AnimalDetailPanel>[0]> = {}) {
  const onLoadProduction = vi.fn().mockResolvedValue(HISTORY);
  render(
    <AnimalDetailPanel
      token={TOKEN}
      animal={animal()}
      canEdit={false}
      onChanged={vi.fn()}
      onLoadProduction={onLoadProduction}
      {...props}
    />,
  );
  return { onLoadProduction };
}

describe("Produção na ficha do animal", () => {
  it("mostra as leituras em vigor com origem e responsável", async () => {
    const { onLoadProduction } = renderDetail();

    const table = await screen.findByRole("table", { name: /leituras de produção/i });
    expect(onLoadProduction).toHaveBeenCalledWith(TOKEN, "a-1");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("10/09/2026");
    expect(rows[0]).toHaveTextContent("12");
    expect(rows[0]).toHaveTextContent(/corrigida/i);
    expect(rows[0]).toHaveTextContent("anotado errado");
    expect(rows[1]).toHaveTextContent(/importada.*agosto\.csv/i);
    expect(rows[2]).toHaveTextContent(/sistema antigo/i);
  });

  it("resume a produção da vaca", async () => {
    renderDetail();

    expect(await screen.findByText(/3 coletas/i)).toBeInTheDocument();
    // Média das leituras em vigor: (12 + 30 + 20) / 3.
    expect(screen.getByText(/20,7 L/)).toBeInTheDocument();
  });

  it("guarda as versões antigas à parte, sem apagá-las", async () => {
    renderDetail();

    const older = await screen.findByText(/versões anteriores \(1\)/i);
    const details = older.closest("details") as HTMLElement;
    expect(within(details).getByText(/substituída/i)).toBeInTheDocument();
    expect(within(details).getByText("21,5")).toBeInTheDocument();
  });

  it("revisor corrige uma leitura direto da ficha", async () => {
    const onCorrect = vi.fn().mockResolvedValue({});
    const { onLoadProduction } = renderDetail({ canEdit: true, onCorrect });

    const table = await screen.findByRole("table", { name: /leituras de produção/i });
    const row = within(table).getAllByRole("row")[2];
    fireEvent.click(within(row).getByRole("button", { name: /corrigir/i }));

    fireEvent.change(screen.getByLabelText(/novo valor/i), { target: { value: "28,5" } });
    fireEvent.change(screen.getByLabelText(/motivo/i), { target: { value: "confere com o tanque" } });
    fireEvent.click(screen.getByRole("button", { name: /salvar correção/i }));

    await waitFor(() =>
      expect(onCorrect).toHaveBeenCalledWith(TOKEN, "m-4", 28.5, "confere com o tanque"),
    );
    await waitFor(() => expect(onLoadProduction).toHaveBeenCalledTimes(2));
  });

  it("revisor anula uma leitura com motivo", async () => {
    const onVoid = vi.fn().mockResolvedValue(undefined);
    renderDetail({ canEdit: true, onVoid });

    const table = await screen.findByRole("table", { name: /leituras de produção/i });
    const row = within(table).getAllByRole("row")[1];
    fireEvent.click(within(row).getByRole("button", { name: /anular/i }));
    fireEvent.change(screen.getByLabelText(/motivo/i), { target: { value: "vaca errada" } });
    fireEvent.click(screen.getByRole("button", { name: /anular leitura/i }));

    await waitFor(() => expect(onVoid).toHaveBeenCalledWith(TOKEN, "m-3", "vaca errada"));
  });

  it("leitura aprovada na caixa de revisão aparece com a origem legível", async () => {
    renderDetail({
      onLoadProduction: vi
        .fn()
        .mockResolvedValue([entry({ provenance: "proposal_review", responsible: "maria@belovale" })]),
    });

    const table = await screen.findByRole("table", { name: /leituras de produção/i });
    expect(table).toHaveTextContent("Leitura revisada");
    expect(table).not.toHaveTextContent("proposal_review");
  });

  it("operador consulta, mas não corrige", async () => {
    renderDetail({ canEdit: false });

    await screen.findByRole("table", { name: /leituras de produção/i });
    expect(screen.queryByRole("button", { name: /corrigir/i })).not.toBeInTheDocument();
  });

  it("vaca sem leituras diz isso", async () => {
    renderDetail({ onLoadProduction: vi.fn().mockResolvedValue([]) });

    expect(await screen.findByText(/nenhuma leitura de produção/i)).toBeInTheDocument();
  });
});

describe("Histórico de preço dos insumos", () => {
  it("mostra os preços anteriores com data e quem registrou", async () => {
    const supply: Supply = {
      id: "s-1",
      name: "Concentrado",
      price_per_kg: 2.35,
      legacy_id: null,
      diets: [],
    };
    const onLoadPrices = vi.fn().mockResolvedValue([
      { effective_on: "2026-10-01", price_per_kg: 2.35, source: "manual", recorded_by: "dono@belovale" },
      { effective_on: "2026-08-25", price_per_kg: 2.12125, source: "legacy_baseline", recorded_by: "titular" },
    ]);

    render(
      <SuppliesPage
        token={TOKEN}
        canEdit={false}
        onList={vi.fn().mockResolvedValue([supply])}
        onLoadPrices={onLoadPrices}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /histórico de preço/i }));

    await waitFor(() => expect(onLoadPrices).toHaveBeenCalledWith(TOKEN, "s-1"));
    const list = await screen.findByRole("list", { name: /preços de concentrado/i });
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(list).toHaveTextContent("01/10/2026");
    expect(list).toHaveTextContent("dono@belovale");
    expect(list).toHaveTextContent(/sistema antigo/i);
  });
});

describe("Conta nova", () => {
  it("avisa que a pessoa escolhe a própria senha no primeiro acesso", async () => {
    render(
      <UsersPage
        token={TOKEN}
        currentUserId="u-9"
        onList={vi.fn().mockResolvedValue({ items: [], total: 0 })}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /adicionar pessoa/i }));
    expect(screen.getByText(/no primeiro acesso/i)).toBeInTheDocument();
  });
});
