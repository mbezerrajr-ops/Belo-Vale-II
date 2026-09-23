/**
 * Impressão: folha de coleta em branco e lista de animais.
 *
 * No curral nem sempre dá para digitar na hora. Sem lançamento no dia, a folha
 * impressa tem as vacas do lote, na ordem do caderno, com a pesagem anterior
 * de referência e manhã, tarde e observação em branco; depois o funcionário
 * digita ou importa. Com lançamento, a folha é o registro da pesagem. A lista
 * impressa leva todos os animais do filtro, não só a página que está na tela.
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

function sheet(launched: boolean): ProductionSheet {
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
        producao: launched ? 35 : null,
        manha: launched ? 20 : null,
        tarde: launched ? 15 : null,
        observacao: launched ? "→ 3º Lote" : null,
        measurement_id: launched ? "m-1" : null,
        provenance: launched ? "manual_entry" : null,
        anterior: { measured_on: "2026-08-25", producao: 37.5 },
      },
      {
        animal_id: "a-389",
        brinco: "389",
        name: "ÁGATA",
        situacao: "Em lactação",
        producao: null,
        measurement_id: null,
        provenance: null,
        anterior: { measured_on: "2026-07-22", producao: 21 },
      },
    ],
  };
}

function printSheet(launched: boolean, button: RegExp): Promise<HTMLElement> {
  const { container } = render(
    <ProductionPage
      token={TOKEN}
      canCorrect={false}
      today="2026-09-18"
      onLoadSheet={vi.fn().mockResolvedValue(sheet(launched))}
      onEnter={vi.fn()}
    />,
  );
  return screen.findByRole("button", { name: button }).then((found) => {
    fireEvent.click(found);
    expect(print).toHaveBeenCalled();
    return container.querySelector(".print-area") as HTMLElement;
  });
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

describe("Folha de coleta", () => {
  it("sem lançamento, sai em branco com a pesagem anterior de referência", async () => {
    const area = await printSheet(false, /imprimir folha em branco/i);

    expect(area).toHaveTextContent("LOTE 1");
    expect(area).toHaveTextContent("18/09/2026");
    const header = Array.from(area.querySelectorAll("th"), (cell) => cell.textContent);
    expect(header).toEqual(["Brinco", "Nome", "Última (25/08)", "Manhã", "Tarde", "Obs."]);
    const [borborema, agata] = Array.from(area.querySelectorAll<HTMLElement>("tbody tr"));
    expect(borborema).toHaveTextContent("BORBOREMA");
    expect(borborema).toHaveTextContent("37,5");
    // Pesagem anterior de outra data: a data vai junto do valor.
    expect(agata).toHaveTextContent("21 (22/07)");
  });

  it("com lançamento, é o registro da pesagem: manhã, tarde, total e observação", async () => {
    const area = await printSheet(true, /imprimir folha preenchida/i);

    const header = Array.from(area.querySelectorAll("th"), (cell) => cell.textContent);
    expect(header).toEqual(["Brinco", "Nome", "Manhã", "Tarde", "Total", "Obs."]);
    const [borborema, agata] = Array.from(area.querySelectorAll<HTMLElement>("tbody tr"));
    const cells = Array.from(borborema.querySelectorAll("td"), (cell) => cell.textContent);
    expect(cells).toEqual(["027", "BORBOREMA", "20", "15", "35", "→ 3º Lote"]);
    // A vaca ainda sem lançamento fica em branco, para completar.
    expect(Array.from(agata.querySelectorAll("td"), (cell) => cell.textContent)).toEqual([
      "389",
      "ÁGATA",
      "",
      "",
      "—",
      "",
    ]);
    expect(area).toHaveTextContent("Registro da pesagem de leite");
    expect(area).toHaveTextContent(/Total do lote\s*35 L/);
    expect(area).toHaveTextContent(/Vacas lançadas\s*1 de 2/);
  });

  it("sem manhã e tarde lançadas, a folha preenchida mostra só o total", async () => {
    const onlyTotals = sheet(true);
    onlyTotals.items[0] = { ...onlyTotals.items[0], manha: null, tarde: null };
    const { container } = render(
      <ProductionPage
        token={TOKEN}
        canCorrect={false}
        today="2026-09-18"
        onLoadSheet={vi.fn().mockResolvedValue(onlyTotals)}
        onEnter={vi.fn()}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: /imprimir folha preenchida/i }));
    const area = container.querySelector(".print-area") as HTMLElement;

    const header = Array.from(area.querySelectorAll("th"), (cell) => cell.textContent);
    expect(header).toEqual(["Brinco", "Nome", "Total", "Obs."]);
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
