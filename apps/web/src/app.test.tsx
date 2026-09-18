/**
 * Casca do aplicativo: para onde cada pessoa vai ao entrar.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";
import * as client from "./api/client";
import { clearStoredToken, storeToken } from "./auth/session";
import type { CurrentUser } from "./api/types";

vi.mock("./api/client");

const api = vi.mocked(client);

function signedIn(user: Partial<CurrentUser>): void {
  storeToken("token-de-teste");
  api.getCurrentUser.mockResolvedValue({
    id: "u-1",
    email: "joao@belovale",
    role: "operator",
    must_change_password: false,
    ...user,
  });
}

beforeEach(() => {
  clearStoredToken();
  api.getCurrentFarm.mockResolvedValue({ id: "f-1", name: "Belo Vale II", code: null });
  api.getProductionSheet.mockResolvedValue({
    measured_on: "2026-09-18",
    lote: null,
    lotes: [],
    items: [],
  });
  api.getDashboard.mockReturnValue(new Promise(() => {}));
  api.refreshSession.mockResolvedValue(null);
  api.getFeatures.mockResolvedValue({ photo_sheets: false });
});

afterEach(() => {
  vi.clearAllMocks();
  clearStoredToken();
});

describe("App", () => {
  it("funcionário abre direto no lançamento de produção", async () => {
    signedIn({ role: "operator" });

    render(<App />);

    expect(await screen.findByRole("heading", { name: /produção do dia/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /produção/i })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("dono abre no painel, com a produção a um toque", async () => {
    signedIn({ role: "admin", email: "dono@belovale" });

    render(<App />);

    const production = await screen.findByRole("button", { name: /produção/i });
    expect(production).toHaveAttribute("aria-current", "false");
    expect(screen.getByRole("button", { name: /painel/i })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("esconde Fichas quando não há OCR real", async () => {
    signedIn({ role: "admin", email: "dono@belovale" });

    render(<App />);

    await screen.findByRole("button", { name: /produção/i });
    await waitFor(() => expect(api.getFeatures).toHaveBeenCalled());
    expect(screen.queryByRole("button", { name: /fichas/i })).not.toBeInTheDocument();
  });

  it("mostra Fichas quando a instalação tem OCR", async () => {
    signedIn({ role: "admin", email: "dono@belovale" });
    api.getFeatures.mockResolvedValue({ photo_sheets: true });

    render(<App />);

    expect(await screen.findByRole("button", { name: /fichas/i })).toBeInTheDocument();
  });

  it("senha provisória leva direto à troca, sem acesso ao resto", async () => {
    signedIn({ must_change_password: true });
    api.changeOwnPassword.mockResolvedValue(undefined);

    render(<App />);

    expect(await screen.findByText(/escolha uma senha nova/i)).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: /áreas/i })).not.toBeInTheDocument();

    // Trocada a senha, o servidor passa a responder a conta liberada.
    api.getCurrentUser.mockResolvedValue({
      id: "u-1",
      email: "joao@belovale",
      role: "operator",
      must_change_password: false,
    });
    fireEvent.change(screen.getByLabelText(/senha atual/i), {
      target: { value: "caju-pedra-rio-47" },
    });
    fireEvent.change(screen.getByLabelText(/nova senha/i), {
      target: { value: "pitomba madura no pe" },
    });
    fireEvent.click(screen.getByRole("button", { name: /trocar senha/i }));

    await waitFor(() =>
      expect(screen.getByRole("navigation", { name: /áreas/i })).toBeInTheDocument(),
    );
  });
});
