/**
 * Impressão: folha de coleta em branco e lista de animais.
 *
 * No curral nem sempre dá para digitar na hora. A folha impressa tem as vacas
 * do lote, na ordem do caderno, com a coluna de litros em branco; depois o
 * funcionário digita ou importa. A lista impressa leva todos os animais do
 * filtro, não só a página que está na tela.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AnimalSearchPage } from "./animals/AnimalSearchPage";
import { ProductionPage } from "./production/ProductionPage";
import type { Animal, AnimalPage, ProductionSheet } from "../api/types";

const TOKEN = "token-de-teste";

let print: ReturnType<typeof vi.fn<() => void>>;

beforeEach(() => {
  print = vi.fn<() => void>();
  window.print = print;
});

afterEach(() => {
  vi.restoreAllMocks();
});

function sheet(): ProductionSheet {
  return {
    measured_on: "2026-09-18",
    lote: "LOTE 1",
    lotes: ["LOTE 1"],
    items: [
      {
        animal_id: "a-027",
        brinco: "027",
        name: "BORBOREMA",
        situacao: "Em lactação",
        producao: 35,
        measurement_id: "m-1",
        provenance: "manual_entry",
      },
      {
        animal_id: "a-389",
        brinco: "389",
        name: "ÁGATA",
        situacao: "Em lactação",
        producao: null,
        measurement_id: null,
        provenance: null,
      },
    ],
  };
}

function animal(index: number): Animal {
  return {
    id: `a-${index}`,
    farm_id: "f-1",
    brinco: String(100 + index),
    brinco_origem: null,
    legacy_id: null,
    numero_legado: null,
    name: `VACA ${index}`,
    situacao: "Em lactação",
    status: "Ativo",
    ultimo_parto: null,
    nascimento: null,
    peso: null,
    observacoes: null,
    lote_atual: "LOTE 1",
    grupo_manejo: null,
  };
}

describe("Folha de coleta em branco", () => {
  it("imprime as vacas do lote com a coluna de litros vazia", async () => {
    const { container } = render(
      <ProductionPage
        token={TOKEN}
        canCorrect={false}
        today="2026-09-18"
        onLoadSheet={vi.fn().mockResolvedValue(sheet())}
        onEnter={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /imprimir folha em branco/i }));

    expect(print).toHaveBeenCalled();
    const area = container.querySelector(".print-area") as HTMLElement;
    expect(area).toHaveTextContent("LOTE 1");
    expect(area).toHaveTextContent("18/09/2026");
    expect(area).toHaveTextContent("BORBOREMA");
    expect(area).toHaveTextContent("ÁGATA");
    // Folha em branco: nem o valor já lançado aparece.
    expect(area).not.toHaveTextContent("35");
  });
});

describe("Lista de animais impressa", () => {
  it("busca todas as páginas do filtro antes de imprimir", async () => {
    const all = Array.from({ length: 230 }, (_, index) => animal(index));
    const search = vi.fn(async (_token: string, query: { limit?: number; offset?: number }) => {
      const offset = query.offset ?? 0;
      const limit = query.limit ?? 25;
      const page: AnimalPage = {
        items: all.slice(offset, offset + limit),
        total: all.length,
        limit,
        offset,
      };
      return page;
    });

    const { container } = render(
      <AnimalSearchPage token={TOKEN} canEdit={false} onOpen={vi.fn()} onSearch={search} />,
    );

    fireEvent.click(screen.getByRole("button", { name: /^todos$/i }));
    fireEvent.click(await screen.findByRole("button", { name: /imprimir lista/i }));

    await waitFor(() => expect(print).toHaveBeenCalled());
    const area = container.querySelector(".print-area") as HTMLElement;
    expect(area.querySelectorAll("tbody tr")).toHaveLength(230);
    expect(area).toHaveTextContent("230 animais");
    expect(search).toHaveBeenCalledWith(TOKEN, expect.objectContaining({ limit: 200, offset: 200 }));
  });
});
