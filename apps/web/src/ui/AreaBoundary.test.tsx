import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AreaBoundary } from "./AreaBoundary";

function Quebra(): JSX.Element {
  throw new TypeError("Failed to fetch dynamically imported module");
}

describe("tela que não abriu", () => {
  it("mostra o que aconteceu e como tentar de novo, sem derrubar o resto", () => {
    // O React registra o erro no console; aqui ele é esperado.
    vi.spyOn(console, "error").mockImplementation(() => undefined);
    render(
      <>
        <p>barra de áreas</p>
        <AreaBoundary>
          <Quebra />
        </AreaBoundary>
      </>,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(/não foi possível abrir esta tela/i);
    expect(screen.getByRole("button", { name: "Tentar de novo" })).toBeInTheDocument();
    expect(screen.getByText("barra de áreas")).toBeInTheDocument();
  });
});
