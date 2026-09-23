import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { InstallHint } from "./InstallHint";

const IPHONE =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.5 Mobile/15E148 Safari/604.1";

function comoSe(agente: string, instalado = false): void {
  vi.spyOn(navigator, "userAgent", "get").mockReturnValue(agente);
  Object.defineProperty(navigator, "standalone", { value: instalado, configurable: true });
}

afterEach(() => {
  vi.restoreAllMocks();
  Object.defineProperty(navigator, "standalone", { value: undefined, configurable: true });
});

describe("usar como aplicativo", () => {
  it("no iPhone, ensina o caminho escondido no Compartilhar do Safari", () => {
    comoSe(IPHONE);
    render(<InstallHint />);

    expect(screen.getByRole("heading", { name: /usar como aplicativo/i })).toBeInTheDocument();
    expect(screen.getByText(/adicionar à tela de início/i)).toBeInTheDocument();
    expect(screen.getByText("Safari")).toBeInTheDocument();
  });

  it("já instalado, não mostra nada", () => {
    comoSe(IPHONE, true);
    const { container } = render(<InstallHint />);
    expect(container).toBeEmptyDOMElement();
  });

  it("no computador, não mostra nada", () => {
    comoSe("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36");
    const { container } = render(<InstallHint />);
    expect(container).toBeEmptyDOMElement();
  });
});
