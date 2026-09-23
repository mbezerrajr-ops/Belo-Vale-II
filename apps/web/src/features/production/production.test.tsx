/**
 * Lançamento de produção no curral.
 *
 * Quem usa está de pé, com o celular numa mão e o caderno na outra. Os testes
 * cobrem o que não pode falhar ali:
 *
 * - digitar e seguir para a próxima vaca sem tocar em botão de salvar;
 * - vírgula decimal, como se escreve no caderno;
 * - na tela, só o total: manhã e tarde ficam para a folha impressa;
 * - a observação da pesagem vai junto, e anotá-la depois não é correção;
 * - sinal ruim não perde o valor digitado;
 * - um valor diferente do já lançado nunca sobrescreve: o operador é avisado,
 *   o revisor corrige com motivo.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProductionPage } from "./ProductionPage";
import { ApiError, type ProductionSheet, type Reading } from "../../api/types";

const TOKEN = "token-de-teste";
const DAY = "2026-09-18";

function sheet(overrides: Partial<ProductionSheet> = {}): ProductionSheet {
  return {
    measured_on: DAY,
    lote: "LOTE 1",
    lotes: ["LOTE 1", "LOTE 2"],
    items: [
      {
        animal_id: "a-027",
        brinco: "027",
        name: "BORBOREMA",
        situacao: "Em lactação",
        producao: null,
        measurement_id: null,
        provenance: null,
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
    ...overrides,
  };
}

function reading(overrides: Partial<Reading> = {}): Reading {
  return {
    id: "m-1",
    animal_id: "a-027",
    measured_on: DAY,
    producao: 21.5,
    provenance: "manual_entry",
    entered_by: "joao@belovale",
    supersedes: null,
    created_at: "2026-09-18T09:00:00Z",
    ...overrides,
  };
}

function setup(
  props: Partial<Parameters<typeof ProductionPage>[0]> = {},
  loaded: ProductionSheet = sheet(),
) {
  const onLoadSheet = vi.fn().mockResolvedValue(loaded);
  const onEnter = vi.fn().mockResolvedValue(reading());
  render(
    <ProductionPage
      token={TOKEN}
      canCorrect={false}
      today={DAY}
      onLoadSheet={onLoadSheet}
      onEnter={onEnter}
      {...props}
    />,
  );
  return { onLoadSheet, onEnter };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ProductionPage", () => {
  it("abre no dia de hoje e, sem lote escolhido, pega o primeiro", async () => {
    const onLoadSheet = vi
      .fn()
      .mockResolvedValueOnce(sheet({ lote: null, items: [] }))
      .mockResolvedValue(sheet());

    render(
      <ProductionPage
        token={TOKEN}
        canCorrect={false}
        today={DAY}
        onLoadSheet={onLoadSheet}
        onEnter={vi.fn()}
      />,
    );

    expect(await screen.findByText("BORBOREMA")).toBeInTheDocument();
    expect(onLoadSheet).toHaveBeenNthCalledWith(1, TOKEN, DAY, null);
    expect(onLoadSheet).toHaveBeenNthCalledWith(2, TOKEN, DAY, "LOTE 1");
    expect(screen.getByRole("button", { name: "LOTE 1" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("salva ao sair do campo, aceitando vírgula decimal", async () => {
    const { onEnter } = setup();

    const field = await screen.findByLabelText("Litros de BORBOREMA");
    fireEvent.change(field, { target: { value: "21,5" } });
    fireEvent.blur(field);

    await waitFor(() =>
      expect(onEnter).toHaveBeenCalledWith(TOKEN, "a-027", DAY, { producao: 21.5 }),
    );
    expect(await screen.findByText(/1 de 2 lançadas/i)).toBeInTheDocument();
  });

  it("Enter salva e leva para a próxima vaca", async () => {
    setup();

    const first = await screen.findByLabelText("Litros de BORBOREMA");
    first.focus();
    fireEvent.change(first, { target: { value: "18" } });
    fireEvent.keyDown(first, { key: "Enter" });

    await waitFor(() =>
      expect(screen.getByLabelText("Litros de ÁGATA")).toHaveFocus(),
    );
  });

  it("recusa valor fora do plausível sem chamar o servidor", async () => {
    const { onEnter } = setup();

    const field = await screen.findByLabelText("Litros de BORBOREMA");
    fireEvent.change(field, { target: { value: "215" } });
    fireEvent.blur(field);

    expect(await screen.findByText(/confira o valor/i)).toBeInTheDocument();
    expect(onEnter).not.toHaveBeenCalled();
  });

  it("sem sinal, mantém o valor digitado e oferece tentar de novo", async () => {
    const onEnter = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("Failed to fetch"))
      .mockResolvedValue(reading());
    setup({ onEnter });

    const field = await screen.findByLabelText("Litros de BORBOREMA");
    fireEvent.change(field, { target: { value: "21,5" } });
    fireEvent.blur(field);

    const retry = await screen.findByRole("button", { name: /tentar de novo/i });
    expect(field).toHaveValue("21,5");

    fireEvent.click(retry);
    await waitFor(() => expect(onEnter).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/1 de 2 lançadas/i)).toBeInTheDocument();
  });

  it("avisa o operador quando outra pessoa já lançou outro valor", async () => {
    const conflict = new ApiError(409, {
      code: "conflict",
      detail: {
        message: "Esta vaca já tem produção lançada nesta data, com outro valor.",
        existing: reading({ producao: 30, entered_by: "maria@belovale" }),
      },
    });
    setup({ onEnter: vi.fn().mockRejectedValue(conflict) });

    const field = await screen.findByLabelText("Litros de BORBOREMA");
    fireEvent.change(field, { target: { value: "12" } });
    fireEvent.blur(field);

    const row = (await screen.findByText(/já lançado: 30 L/i)).closest("li");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText(/maria@belovale/)).toBeInTheDocument();
    expect(within(row as HTMLElement).getByText(/revisor/i)).toBeInTheDocument();
    expect(field).toHaveValue("30");
  });

  it("revisor corrige um valor já lançado informando o motivo", async () => {
    const onCorrect = vi.fn().mockResolvedValue(reading({ id: "m-2", producao: 12 }));
    setup(
      { canCorrect: true, onCorrect },
      sheet({
        items: [
          {
            animal_id: "a-027",
            brinco: "027",
            name: "BORBOREMA",
            situacao: "Em lactação",
            producao: 21.5,
            measurement_id: "m-1",
            provenance: "manual_entry",
          },
        ],
      }),
    );

    const field = await screen.findByLabelText("Litros de BORBOREMA");
    expect(field).toHaveValue("21,5");
    fireEvent.change(field, { target: { value: "12" } });
    fireEvent.blur(field);

    fireEvent.change(await screen.findByLabelText(/motivo da correção/i), {
      target: { value: "anotado errado" },
    });
    fireEvent.click(screen.getByRole("button", { name: /salvar correção/i }));

    await waitFor(() =>
      expect(onCorrect).toHaveBeenCalledWith(
        TOKEN,
        "m-1",
        { producao: 12, observacao: null },
        "anotado errado",
      ),
    );
  });

  it("operador não recebe a opção de corrigir", async () => {
    setup(
      { canCorrect: false },
      sheet({
        items: [
          {
            animal_id: "a-027",
            brinco: "027",
            name: "BORBOREMA",
            situacao: "Em lactação",
            producao: 21.5,
            measurement_id: "m-1",
            provenance: "manual_entry",
          },
        ],
      }),
    );

    const field = await screen.findByLabelText("Litros de BORBOREMA");
    fireEvent.change(field, { target: { value: "12" } });
    fireEvent.blur(field);

    expect(await screen.findByText(/peça a um revisor/i)).toBeInTheDocument();
    expect(screen.queryByLabelText(/motivo da correção/i)).not.toBeInTheDocument();
    expect(field).toHaveValue("21,5");
  });

  it("revisor anula pela própria linha, com motivo", async () => {
    const onVoid = vi.fn().mockResolvedValue(undefined);
    setup(
      { canCorrect: true, onVoid },
      sheet({
        items: [
          {
            animal_id: "a-027",
            brinco: "027",
            name: "BORBOREMA",
            situacao: "Em lactação",
            producao: 21.5,
            measurement_id: "m-1",
            provenance: "manual_entry",
          },
        ],
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Anular o lançamento de BORBOREMA" }));
    fireEvent.change(screen.getByLabelText(/motivo para anular/i), {
      target: { value: "lançado na vaca errada" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Anular lançamento" }));

    await waitFor(() => expect(onVoid).toHaveBeenCalledWith(TOKEN, "m-1", "lançado na vaca errada"));
  });

  it("operador não vê anular", async () => {
    setup(
      { canCorrect: false },
      sheet({
        items: [
          {
            animal_id: "a-027",
            brinco: "027",
            name: "BORBOREMA",
            situacao: "Em lactação",
            producao: 21.5,
            measurement_id: "m-1",
            provenance: "manual_entry",
          },
        ],
      }),
    );

    await screen.findByLabelText("Litros de BORBOREMA");
    expect(screen.queryByRole("button", { name: /anular/i })).not.toBeInTheDocument();
  });

  it("leitura com manhã e tarde aparece na tela só com o total", async () => {
    setup(
      {},
      sheet({
        items: [
          {
            animal_id: "a-027",
            brinco: "027",
            name: "BORBOREMA",
            situacao: "Em lactação",
            producao: 33,
            manha: 18,
            tarde: 15,
            measurement_id: "m-1",
            provenance: "file_import",
          },
        ],
      }),
    );

    expect(await screen.findByLabelText("Litros de BORBOREMA")).toHaveValue("33");
    expect(screen.queryByLabelText(/manhã de/i)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/tarde de/i)).not.toBeInTheDocument();
  });

  it("a observação vai junto dos litros", async () => {
    const { onEnter } = setup();

    fireEvent.click(await screen.findByRole("button", { name: "Anotar observação de BORBOREMA" }));
    fireEvent.change(screen.getByLabelText("Litros de BORBOREMA"), { target: { value: "7" } });
    const note = screen.getByLabelText("Observação de BORBOREMA");
    fireEvent.change(note, { target: { value: "→ Seca" } });
    fireEvent.blur(note);

    await waitFor(() =>
      expect(onEnter).toHaveBeenCalledWith(TOKEN, "a-027", DAY, { producao: 7, observacao: "→ Seca" }),
    );
  });

  it("anotar a observação depois não pede correção", async () => {
    const onEnter = vi.fn().mockResolvedValue(reading({ producao: 21.5, observacao: "→ 3º Lote" }));
    setup(
      { onEnter },
      sheet({
        items: [
          {
            animal_id: "a-027",
            brinco: "027",
            name: "BORBOREMA",
            situacao: "Em lactação",
            producao: 21.5,
            measurement_id: "m-1",
            provenance: "manual_entry",
          },
        ],
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Anotar observação de BORBOREMA" }));
    const note = screen.getByLabelText("Observação de BORBOREMA");
    fireEvent.change(note, { target: { value: "→ 3º Lote" } });
    fireEvent.blur(note);

    await waitFor(() =>
      expect(onEnter).toHaveBeenCalledWith(TOKEN, "a-027", DAY, {
        producao: 21.5,
        observacao: "→ 3º Lote",
      }),
    );
    expect(screen.queryByText(/peça a um revisor/i)).not.toBeInTheDocument();
  });

  it("trocar de lote recarrega a folha", async () => {
    const { onLoadSheet } = setup();

    fireEvent.click(await screen.findByRole("button", { name: "LOTE 2" }));

    await waitFor(() => expect(onLoadSheet).toHaveBeenCalledWith(TOKEN, DAY, "LOTE 2"));
  });

  it("mostra o total de litros do lote", async () => {
    setup(
      {},
      sheet({
        items: [
          {
            animal_id: "a-027",
            brinco: "027",
            name: "BORBOREMA",
            situacao: "Em lactação",
            producao: 21.5,
            measurement_id: "m-1",
            provenance: "manual_entry",
          },
          {
            animal_id: "a-389",
            brinco: "389",
            name: "ÁGATA",
            situacao: "Em lactação",
            producao: 18,
            measurement_id: "m-2",
            provenance: "manual_entry",
          },
        ],
      }),
    );

    expect(await screen.findByText("39,5 L")).toBeInTheDocument();
    expect(screen.getByText(/2 de 2 lançadas/i)).toBeInTheDocument();
  });
});
