/**
 * Painel do rebanho e insumos.
 *
 * Porta os indicadores da plataforma legada. Os testes fixam o que mais
 * importa para quem lê: os números certos, e a distinção entre "zero" e "não
 * dá para calcular" — que é o caso quando falta o preço do leite.
 */

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HerdDashboard } from "./HerdDashboard";
import { SuppliesPage } from "./SuppliesPage";
import type { DashboardSummary, Supply } from "../../api/types";

const TOKEN = "token-de-teste";

function summary(overrides: Partial<DashboardSummary> = {}): DashboardSummary {
  return {
    measured_on: "2026-08-25",
    available_dates: ["2026-08-25", "2026-07-22"],
    production_by_date: [
      { measured_on: "2026-07-22", liters: 2500, animals: 107 },
      { measured_on: "2026-08-25", liters: 2000, animals: 45 },
    ],
    milk_price: 2.59,
    total_animals: 401,
    animals_without_lot: 118,
    animals_with_reading: 45,
    by_situation: { "Em lactação": 250, Seca: 151 },
    by_status: { Ativo: 401 },
    by_management_group: { BEZERREIRO: 28, ENGORDA: 14 },
    lactation_stages: { "0-100": 40, "101-200": 30, "201-305": 20, "305+": 10 },
    lots: [
      {
        lote: "LOTE 1",
        animals: 100,
        production: 2000,
        feed_cost: 1964.8,
        revenue: 5180,
        profit: 3215.2,
        cost_per_animal: 19.648,
        production_per_animal: 20,
        cost_ratio: 0.379,
      },
    ],
    feed_breakdown: [
      {
        name: "Concentrado",
        price_per_kg: 2.12125,
        total_cost: 1018.2,
        cost_by_lot: { "LOTE 1": 1018.2 },
      },
    ],
    top_producers: [
      {
        animal_id: "a-1",
        brinco: "389",
        name: "ÁGATA",
        lote: "LOTE 3",
        production: 38.5,
      },
    ],
    bottom_producers: [
      {
        animal_id: "a-2",
        brinco: "128",
        name: "SEREIA",
        lote: "LOTE 1",
        production: 8,
      },
    ],
    total_production: 2000,
    total_feed_cost: 1964.8,
    total_revenue: 5180,
    total_profit: 3215.2,
    ...overrides,
  };
}

function supply(overrides: Partial<Supply> = {}): Supply {
  return {
    id: "s-1",
    name: "Concentrado",
    price_per_kg: 2.12125,
    legacy_id: "i1",
    diets: [{ lote: "LOTE 1", kg_per_day: 480 }],
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("HerdDashboard", () => {
  it("mostra os indicadores principais", async () => {
    render(
      <HerdDashboard token={TOKEN} onLoad={vi.fn().mockResolvedValue(summary())} />,
    );

    // Os números aparecem em mais de um lugar (KPI, aviso de cobertura,
    // linha do lote); o que importa é que o painel os apresente.
    expect((await screen.findAllByText(/401/)).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/2\.000/).length).toBeGreaterThan(0);
  });

  it("mostra a composição do rebanho por situação", async () => {
    render(
      <HerdDashboard token={TOKEN} onLoad={vi.fn().mockResolvedValue(summary())} />,
    );

    // O rótulo aparece no filtro de situação e na barra de composição.
    expect((await screen.findAllByText(/em lacta[çc][ãa]o/i)).length).toBeGreaterThan(1);
    expect(screen.getByText("250")).toBeInTheDocument();
  });

  it("mostra o comparativo por lote com custo e receita", async () => {
    render(
      <HerdDashboard token={TOKEN} onLoad={vi.fn().mockResolvedValue(summary())} />,
    );

    await screen.findAllByText("LOTE 1");
    // Os valores aparecem nos KPIs e na tabela; verificar dentro da tabela
    // prova que a linha do lote traz custo, receita e lucro.
    // Há mais de uma visão em tabela no painel; a do comparativo é a que
    // tem a coluna "Vacas".
    const tabela = screen
      .getAllByRole("table")
      .find((table) => within(table).queryByText("Vacas") !== null)!;
    const linha = within(tabela).getAllByRole("row")[1];
    expect(within(linha).getByText(/1\.964,80/)).toBeInTheDocument();
    expect(within(linha).getByText(/5\.180,00/)).toBeInTheDocument();
    expect(within(linha).getByText(/3\.215,20/)).toBeInTheDocument();
  });

  it("mostra o estágio de lactação", async () => {
    render(
      <HerdDashboard token={TOKEN} onLoad={vi.fn().mockResolvedValue(summary())} />,
    );

    expect(await screen.findByText(/est[áa]gio de lacta[çc][ãa]o/i)).toBeInTheDocument();
    expect(screen.getByText("0-100")).toBeInTheDocument();
  });

  it("mostra maiores e menores produções no mesmo cartão", async () => {
    render(
      <HerdDashboard token={TOKEN} onLoad={vi.fn().mockResolvedValue(summary())} />,
    );

    expect(await screen.findByText("ÁGATA")).toBeInTheDocument();
    expect(screen.queryByText("SEREIA")).not.toBeInTheDocument();

    const menores = screen.getByRole("button", { name: "Menores" });
    fireEvent.click(menores);

    expect(menores).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("SEREIA")).toBeInTheDocument();
    expect(screen.queryByText("ÁGATA")).not.toBeInTheDocument();
  });

  it("filtra por lote", async () => {
    const load = vi.fn().mockResolvedValue(summary());

    render(<HerdDashboard token={TOKEN} onLoad={load} />);

    await screen.findAllByText("LOTE 1");
    fireEvent.change(screen.getByLabelText("Lote de ordenha"), {
      target: { value: "LOTE 1" },
    });

    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    expect(load.mock.calls[1][1]).toMatchObject({ lote: "LOTE 1" });
  });

  it("permite escolher a data da coleta", async () => {
    const load = vi.fn().mockResolvedValue(summary());

    render(<HerdDashboard token={TOKEN} onLoad={load} />);

    await screen.findAllByText("LOTE 1");
    fireEvent.change(screen.getByLabelText(/data da coleta/i), {
      target: { value: "2026-07-22" },
    });

    await waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    expect(load.mock.calls[1][1]).toMatchObject({ measuredOn: "2026-07-22" });
  });

  it("não inventa receita quando falta o preço do leite", async () => {
    const semPreco = summary({
      milk_price: null,
      total_revenue: null,
      total_profit: null,
      lots: [{ ...summary().lots[0], revenue: null, profit: null }],
    });

    render(<HerdDashboard token={TOKEN} onLoad={vi.fn().mockResolvedValue(semPreco)} />);

    expect(await screen.findByText(/pre[çc]o do leite/i)).toBeInTheDocument();
    // Ausência de preço não pode virar "R$ 0,00".
    expect(screen.queryByText("R$ 0,00")).not.toBeInTheDocument();
  });

  it("avisa que o lucro fica subestimado com cobertura parcial", async () => {
    // Caso real: o custo é do lote inteiro, mas só parte dos animais foi
    // medida naquela data — sem o aviso, o painel sugeriria prejuízo.
    render(
      <HerdDashboard
        token={TOKEN}
        onLoad={vi.fn().mockResolvedValue(
          summary({ total_animals: 401, animals_with_reading: 45 }),
        )}
      />,
    );

    expect(await screen.findByText(/subestimados/i)).toBeInTheDocument();
  });

  it("não avisa quando todos os animais têm leitura", async () => {
    render(
      <HerdDashboard
        token={TOKEN}
        onLoad={vi.fn().mockResolvedValue(
          summary({ total_animals: 45, animals_with_reading: 45 }),
        )}
      />,
    );

    await screen.findAllByText("LOTE 1");
    expect(screen.queryByText(/subestimados/i)).not.toBeInTheDocument();
  });

  it("avisa quando ainda não há medição registrada", async () => {
    const vazio = summary({
      measured_on: null,
      available_dates: [],
      total_production: 0,
      lots: [],
      top_producers: [],
      bottom_producers: [],
    });

    render(<HerdDashboard token={TOKEN} onLoad={vi.fn().mockResolvedValue(vazio)} />);

    expect(await screen.findByText(/nenhuma medi[çc][ãa]o/i)).toBeInTheDocument();
  });
});

describe("SuppliesPage", () => {
  it("mostra o preço do leite em vigor, mesmo quando ele chega depois", async () => {
    // A fazenda é buscada junto com a tela; antes o campo ficava vazio mesmo
    // com o preço definido.
    const view = render(
      <SuppliesPage token={TOKEN} canEdit onList={vi.fn().mockResolvedValue([])} milkPrice={null} />,
    );
    expect(screen.getByLabelText(/pre[çc]o por litro/i)).toHaveValue(null);

    view.rerender(
      <SuppliesPage token={TOKEN} canEdit onList={vi.fn().mockResolvedValue([])} milkPrice={2.45} />,
    );

    expect(screen.getByLabelText(/pre[çc]o por litro/i)).toHaveValue(2.45);
  });

  it("salvar o preço do leite avisa e devolve o valor novo", async () => {
    const onSetMilkPrice = vi.fn().mockResolvedValue(undefined);
    const onMilkPriceSaved = vi.fn();
    render(
      <SuppliesPage
        token={TOKEN}
        canEdit
        milkPrice={2.45}
        onList={vi.fn().mockResolvedValue([])}
        onSetMilkPrice={onSetMilkPrice}
        onMilkPriceSaved={onMilkPriceSaved}
      />,
    );

    fireEvent.change(screen.getByLabelText(/pre[çc]o por litro/i), { target: { value: "2.6" } });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /salvar pre[çc]o do leite/i }));
    });

    expect(onSetMilkPrice).toHaveBeenCalledWith(TOKEN, 2.6);
    expect(onMilkPriceSaved).toHaveBeenCalledWith(2.6);
    expect(screen.getByRole("status")).toHaveTextContent(/pre[çc]o do leite salvo/i);
  });

  it("lista os insumos com preço e dieta", async () => {
    render(
      <SuppliesPage
        token={TOKEN}
        canEdit
        onList={vi.fn().mockResolvedValue([supply()])}
      />,
    );

    expect(await screen.findByText("Concentrado")).toBeInTheDocument();
    expect(screen.getByText(/480/)).toBeInTheDocument();
  });

  it("atualiza o preço de um insumo", async () => {
    const update = vi.fn().mockResolvedValue(supply({ price_per_kg: 2.5 }));

    render(
      <SuppliesPage
        token={TOKEN}
        canEdit
        onList={vi.fn().mockResolvedValue([supply()])}
        onUpdatePrice={update}
      />,
    );

    // O preço abre pelo botão do insumo: fechado, cada insumo cabe numa olhada.
    fireEvent.click(await screen.findByRole("button", { name: /alterar preço/i }));
    fireEvent.change(screen.getByLabelText(/pre[çc]o.*concentrado/i), {
      target: { value: "2.50" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Salvar preço" }));

    await waitFor(() => expect(update).toHaveBeenCalledWith(TOKEN, "s-1", 2.5));
  });

  it("explica que o preço anterior fica no histórico", async () => {
    render(
      <SuppliesPage
        token={TOKEN}
        canEdit
        onList={vi.fn().mockResolvedValue([supply()])}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /alterar preço/i }));
    expect(screen.getByText(/pre[çc]o anterior fica no hist[óo]rico/i)).toBeInTheDocument();
  });

  it("esconde a edição de quem não pode editar", async () => {
    render(
      <SuppliesPage
        token={TOKEN}
        canEdit={false}
        onList={vi.fn().mockResolvedValue([supply()])}
      />,
    );

    await screen.findByText("Concentrado");
    expect(
      screen.queryByRole("button", { name: "Salvar preço" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /alterar preço|novo insumo/i })).not.toBeInTheDocument();
  });
});

describe("HerdDashboard — grupos de manejo", () => {
  it("mostra as áreas da fazenda apartadas dos lotes", () => {
    render(
      <HerdDashboard token={TOKEN} onLoad={vi.fn().mockResolvedValue(summary())} />,
    );

    return screen.findByText(/onde os animais est[ãa]o/i).then(() => {
      expect(screen.getByText("BEZERREIRO")).toBeInTheDocument();
      // O filtro lista só lotes de ordenha, não as áreas.
      const filtro = screen.getByLabelText("Lote de ordenha");
      expect(within(filtro).queryByText("BEZERREIRO")).not.toBeInTheDocument();
    });
  });

  it("diz que área da fazenda não tem dieta nem custo", async () => {
    render(
      <HerdDashboard token={TOKEN} onLoad={vi.fn().mockResolvedValue(summary())} />,
    );

    expect(
      await screen.findByText(/n[ãa]o s[ãa]o lotes de ordenha/i),
    ).toBeInTheDocument();
  });
});
