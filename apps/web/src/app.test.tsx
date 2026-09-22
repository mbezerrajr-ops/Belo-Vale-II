/**
 * Casca do aplicativo: para onde cada pessoa vai ao entrar.
 */

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  api.listProposals.mockResolvedValue([]);
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

  it("mostra quantas propostas esperam revisão", async () => {
    signedIn({ role: "reviewer", email: "revisor@belovale" });
    api.listProposals.mockResolvedValue([{ id: "p-1" }, { id: "p-2" }] as never);

    render(<App />);

    expect(await screen.findByLabelText("2 pendentes")).toBeInTheDocument();
    expect(api.listProposals).toHaveBeenCalledWith("token-de-teste", "pending");
  });

  it("no celular, o que não cabe na barra fica em Mais", async () => {
    // Oito destinos numa barra de 390 px cortavam o último rótulo e
    // escondiam os seguintes, sem sinal de que existiam.
    signedIn({ role: "admin", email: "dono@belovale" });
    api.listSupplies.mockResolvedValue([]);
    render(<App />);
    const mais = await screen.findByRole("button", { name: /^mais$/i });
    expect(mais).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(mais);
    const painel = screen.getByRole("group", { name: /mais áreas/i });
    expect(within(painel).getByRole("button", { name: /contas/i })).toBeInTheDocument();
    expect(within(painel).queryByRole("button", { name: /produção/i })).not.toBeInTheDocument();
    fireEvent.click(within(painel).getByRole("button", { name: /insumos/i }));

    expect(screen.queryByRole("group", { name: /mais áreas/i })).not.toBeInTheDocument();
    // O botão diz em que área a pessoa está.
    expect(screen.getByRole("button", { name: /^insumos$/i, expanded: false })).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("Minha conta abre pelo avatar, não pela barra, e tem o Sair do celular", async () => {
    // Na barra seria um terceiro caminho para o mesmo lugar; e o Sair do
    // topo, no celular, era o botão mais fácil de tocar sem querer.
    signedIn({ role: "admin", email: "dono@belovale" });
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Áreas" });
    expect(within(nav).queryByRole("button", { name: /minha conta/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Minha conta" }));

    expect(await screen.findByRole("heading", { name: "Minha conta" })).toBeInTheDocument();
    const sair = screen.getAllByRole("button", { name: /sair/i });
    expect(sair.map((button) => button.className)).toEqual(
      expect.arrayContaining([expect.stringContaining("logout-top"), expect.stringContaining("logout-account")]),
    );
  });

  it("Esc fecha o Mais", async () => {
    signedIn({ role: "admin", email: "dono@belovale" });
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /^mais$/i }));

    fireEvent.keyDown(window, { key: "Escape" });

    expect(screen.queryByRole("group", { name: /mais áreas/i })).not.toBeInTheDocument();
  });

  it("não há mais área Fichas: a foto é enviada pela Revisão", async () => {
    // Duas telas faziam a mesma coisa — enviar folha e revisar o que saiu
    // dela. O envio foi para dentro da Revisão, que é onde o resultado
    // aparece; as fichas antigas continuam no banco.
    signedIn({ role: "admin", email: "dono@belovale" });

    render(<App />);

    await screen.findByRole("button", { name: /produção/i });
    expect(screen.queryByRole("button", { name: /fichas/i })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /revisão/i })).toBeInTheDocument();
  });

  it("sair só mostra o login depois que o servidor encerrou a sessão", async () => {
    // Regressão: a revogação saía sem esperar resposta; recarregar a página
    // logo depois cortava o pedido, e o cookie ainda válido reabria a sessão
    // de quem tinha acabado de sair.
    signedIn({ role: "operator" });
    let finish: () => void = () => {};
    api.logout.mockReturnValue(new Promise<void>((resolve) => (finish = resolve)));

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /sair/i }));

    expect(api.logout).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: /entrar/i })).not.toBeInTheDocument();
    finish();
    expect(await screen.findByRole("button", { name: /entrar/i })).toBeInTheDocument();
  });

  it("sair funciona mesmo se o servidor não responder", async () => {
    signedIn({ role: "operator" });
    api.logout.mockRejectedValue(new Error("sem rede"));

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: /sair/i }));

    expect(await screen.findByRole("button", { name: /entrar/i })).toBeInTheDocument();
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
