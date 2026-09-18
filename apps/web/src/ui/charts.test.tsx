/**
 * Primitivas de gráfico.
 *
 * O que estes testes fixam não é a aparência, é o contrato de leitura: todo
 * valor está em texto (nunca só em cor ou comprimento), a legenda existe
 * quando há mais de uma série, e o vazio é dito em vez de desenhado.
 */

import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BarList, Columns, Donut, Sparkline, StatTile, TableView, fmt } from "./charts";

describe("StatTile", () => {
  it("mostra o valor formatado", () => {
    render(<StatTile label="Animais" value={401} />);
    expect(screen.getByText("401")).toBeInTheDocument();
  });

  it("mostra travessão para valor indisponível, nunca zero", () => {
    render(<StatTile label="Receita" value={null} format={fmt.brl} />);
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.queryByText(/R\$/)).not.toBeInTheDocument();
  });

  it("marca valor negativo", () => {
    render(<StatTile label="Lucro" value={-10} format={fmt.brl} />);
    expect(screen.getByText(/-?R\$\s?10,00|R\$\s?-10,00/)).toHaveClass("negative");
  });
});

describe("BarList", () => {
  it("escreve o valor de cada barra em texto", () => {
    render(
      <BarList
        data={[
          { label: "LOTE 1", value: 1077 },
          { label: "LOTE 2", value: 39 },
        ]}
      />,
    );
    expect(screen.getByText("1.077")).toBeInTheDocument();
    expect(screen.getByText("39")).toBeInTheDocument();
  });

  it("dá a cada barra um tooltip acessível por teclado", () => {
    render(<BarList data={[{ label: "Silagem", value: 630 }]} format={fmt.brl} />);
    const item = screen.getByText("Silagem").closest("li");
    expect(item).toHaveAttribute("data-tip", expect.stringContaining("Silagem"));
    expect(item).toHaveAttribute("tabindex", "0");
  });
});

describe("Donut", () => {
  it("mostra o total no centro e cada fatia na legenda", () => {
    render(
      <Donut
        centerLabel="animais"
        data={[
          { label: "Em lactação", value: 250 },
          { label: "Seca", value: 151 },
        ]}
      />,
    );
    expect(screen.getByRole("img", { name: /animais: 401/ })).toBeInTheDocument();
    const legend = screen.getByRole("list");
    expect(within(legend).getByText("250")).toBeInTheDocument();
    expect(within(legend).getByText("62%")).toBeInTheDocument();
  });
});

describe("Columns", () => {
  it("tem legenda quando há mais de uma série", () => {
    render(
      <Columns
        series={["Custo", "Receita"]}
        groups={[{ label: "LOTE 1", values: [100, 200] }]}
      />,
    );
    const legend = screen.getByLabelText("Legenda");
    expect(within(legend).getByText("Custo")).toBeInTheDocument();
    expect(within(legend).getByText("Receita")).toBeInTheDocument();
  });

  it("escreve a nota com sinal sob o lote", () => {
    render(
      <Columns
        series={["Custo", "Receita"]}
        groups={[
          { label: "LOTE 2", values: [10, 5], note: { text: "-R$ 5,00", sign: "neg" } },
        ]}
      />,
    );
    expect(screen.getByText("-R$ 5,00")).toHaveClass("neg");
  });
});

describe("Sparkline", () => {
  it("diz quando não há leituras em vez de desenhar vazio", () => {
    render(<Sparkline points={[]} />);
    expect(screen.getByText(/sem leituras/i)).toBeInTheDocument();
  });

  it("rotula a primeira e a última data", () => {
    render(
      <Sparkline
        points={[
          { label: "22/07/26", value: 1500 },
          { label: "25/08/26", value: 1199 },
        ]}
      />,
    );
    expect(screen.getByText("22/07/26")).toBeInTheDocument();
    expect(screen.getByText("25/08/26")).toBeInTheDocument();
  });
});

describe("TableView", () => {
  it("oferece o gráfico como tabela", () => {
    render(<TableView columns={["Lote", "Litros"]} rows={[["LOTE 1", "1.077,0"]]} />);
    expect(screen.getByText(/ver como tabela/i)).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
  });
});
