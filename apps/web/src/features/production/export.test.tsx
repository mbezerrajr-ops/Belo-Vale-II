/**
 * Exportação da produção de um período.
 *
 * O dono escolhe o período (ou um atalho: este mês, mês passado, 30 dias) e
 * baixa a planilha. Período sem leitura avisa em vez de baixar um arquivo
 * vazio; datas trocadas e período longo demais são barrados antes de pedir.
 * Só revisor e administrador veem a opção.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ExportPanel } from "./ExportPanel";
import { ProductionPage } from "./ProductionPage";
import { ApiError, type ProductionSheet } from "../../api/types";

const TOKEN = "token-de-teste";
const TODAY = "2026-10-06";

function exported(readings: number) {
  return { blob: new Blob(["x"]), filename: "producao-2026-10-01-a-2026-10-06.xlsx", readings };
}

function setup(onExport = vi.fn().mockResolvedValue(exported(12))) {
  const onSave = vi.fn();
  render(<ExportPanel token={TOKEN} today={TODAY} onExport={onExport} onSave={onSave} />);
  return { onExport, onSave };
}

describe("Exportar produção", () => {
  it("começa no mês corrente e baixa a planilha do período", async () => {
    const { onExport, onSave } = setup();

    expect(screen.getByLabelText("De")).toHaveValue("2026-10-01");
    expect(screen.getByLabelText("Até")).toHaveValue(TODAY);
    fireEvent.click(screen.getByRole("button", { name: "Baixar planilha" }));

    await waitFor(() => expect(onSave).toHaveBeenCalledTimes(1));
    expect(onExport).toHaveBeenCalledWith(TOKEN, "2026-10-01", TODAY);
    expect(onSave.mock.calls[0][1]).toBe("producao-2026-10-01-a-2026-10-06.xlsx");
    expect(screen.getByRole("status")).toHaveTextContent("Planilha baixada: 12 leituras de 01/10/2026 a 06/10/2026");
  });

  it("os atalhos preenchem o período", () => {
    setup();

    fireEvent.click(screen.getByRole("button", { name: "Mês passado" }));
    expect(screen.getByLabelText("De")).toHaveValue("2026-09-01");
    expect(screen.getByLabelText("Até")).toHaveValue("2026-09-30");

    fireEvent.click(screen.getByRole("button", { name: "Últimos 30 dias" }));
    expect(screen.getByLabelText("De")).toHaveValue("2026-09-07");
    expect(screen.getByLabelText("Até")).toHaveValue(TODAY);
  });

  it("período sem leitura avisa e não baixa nada", async () => {
    const { onSave } = setup(vi.fn().mockResolvedValue(exported(0)));

    fireEvent.click(screen.getByRole("button", { name: "Baixar planilha" }));

    await screen.findByText(/Nenhuma leitura entre 01\/10\/2026 e 06\/10\/2026/);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("data final antes da inicial é barrada antes de pedir", () => {
    const { onExport } = setup();

    fireEvent.change(screen.getByLabelText("De"), { target: { value: "2026-10-05" } });
    fireEvent.change(screen.getByLabelText("Até"), { target: { value: "2026-10-02" } });

    expect(screen.getByRole("alert")).toHaveTextContent("A data final vem antes da inicial.");
    expect(screen.getByRole("button", { name: "Baixar planilha" })).toBeDisabled();
    expect(onExport).not.toHaveBeenCalled();
  });

  it("mais de um ano é barrado", () => {
    setup();

    fireEvent.change(screen.getByLabelText("De"), { target: { value: "2025-10-05" } });

    expect(screen.getByRole("alert")).toHaveTextContent("O período vai até 366 dias");
    expect(screen.getByRole("button", { name: "Baixar planilha" })).toBeDisabled();
  });

  it("mostra o motivo que o servidor deu", async () => {
    setup(vi.fn().mockRejectedValue(new ApiError(403, { code: "forbidden", detail: "Forbidden" })));

    fireEvent.click(screen.getByRole("button", { name: "Baixar planilha" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Exportar é de revisor ou administrador.");
  });
});

describe("Exportar na tela de Produção", () => {
  const sheet: ProductionSheet = { measured_on: TODAY, lote: null, lotes: [], items: [] };

  it("só aparece para revisor e administrador", () => {
    const { unmount } = render(
      <ProductionPage token={TOKEN} canCorrect={false} today={TODAY} onLoadSheet={vi.fn().mockResolvedValue(sheet)} />,
    );
    expect(screen.queryByRole("button", { name: "Exportar" })).toBeNull();
    unmount();

    render(<ProductionPage token={TOKEN} canCorrect today={TODAY} onLoadSheet={vi.fn().mockResolvedValue(sheet)} />);
    expect(screen.getByRole("button", { name: "Exportar" })).toBeInTheDocument();
  });

  it("abre o painel de exportação", async () => {
    render(<ProductionPage token={TOKEN} canCorrect today={TODAY} onLoadSheet={vi.fn().mockResolvedValue(sheet)} />);

    fireEvent.click(screen.getByRole("button", { name: "Exportar" }));

    expect(await screen.findByRole("button", { name: "Baixar planilha" })).toBeInTheDocument();
  });
});
