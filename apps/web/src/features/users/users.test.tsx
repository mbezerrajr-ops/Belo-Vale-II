/**
 * Telas de contas.
 *
 * Só o dono (admin) gerencia contas. Trocar a própria senha é de todos.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChangePasswordForm } from "./ChangePasswordForm";
import { UsersPage } from "./UsersPage";
import type { UserAccount } from "../../api/types";

const TOKEN = "token-de-teste";

function account(overrides: Partial<UserAccount> = {}): UserAccount {
  return {
    id: "u-1",
    email: "joao@belovale",
    role: "operator",
    is_active: true,
    created_at: "2026-09-18T12:00:00Z",
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("UsersPage", () => {
  it("lista as contas existentes", async () => {
    const list = vi.fn().mockResolvedValue({
      items: [account(), account({ id: "u-2", email: "maria@belovale", role: "reviewer" })],
      total: 2,
    });

    render(<UsersPage token={TOKEN} currentUserId="u-9" onList={list} />);

    expect(await screen.findByText("joao@belovale")).toBeInTheDocument();
    expect(screen.getByText("maria@belovale")).toBeInTheDocument();
  });

  it("cria uma conta com papel escolhido", async () => {
    const create = vi.fn().mockResolvedValue(account({ email: "novo@belovale" }));
    const list = vi.fn().mockResolvedValue({ items: [], total: 0 });

    render(
      <UsersPage token={TOKEN} currentUserId="u-9" onList={list} onCreate={create} />,
    );

    fireEvent.change(await screen.findByLabelText(/e-mail/i), {
      target: { value: "novo@belovale" },
    });
    fireEvent.change(screen.getByLabelText(/^senha/i), {
      target: { value: "bezerra no pasto" },
    });
    fireEvent.change(screen.getByLabelText(/fun[çc][ãa]o/i), {
      target: { value: "reviewer" },
    });
    fireEvent.click(screen.getByRole("button", { name: /criar conta/i }));

    await waitFor(() =>
      expect(create).toHaveBeenCalledWith(
        TOKEN,
        "novo@belovale",
        "bezerra no pasto",
        "reviewer",
      ),
    );
  });

  it("mostra a regra de senha antes de o dono errar", async () => {
    render(
      <UsersPage
        token={TOKEN}
        currentUserId="u-9"
        onList={vi.fn().mockResolvedValue({ items: [], total: 0 })}
      />,
    );

    expect(await screen.findByText(/pelo menos 8 caracteres/i)).toBeInTheDocument();
  });

  it("explica o motivo quando a senha é recusada", async () => {
    const create = vi.fn().mockRejectedValue(
      Object.assign(new Error("fraca"), {
        status: 422,
        body: { detail: "A senha contém uma palavra fácil de adivinhar." },
      }),
    );

    render(
      <UsersPage
        token={TOKEN}
        currentUserId="u-9"
        onList={vi.fn().mockResolvedValue({ items: [], total: 0 })}
        onCreate={create}
      />,
    );

    fireEvent.change(await screen.findByLabelText(/e-mail/i), {
      target: { value: "fraco@belovale" },
    });
    fireEvent.change(screen.getByLabelText(/^senha/i), {
      target: { value: "senha123" },
    });
    fireEvent.click(screen.getByRole("button", { name: /criar conta/i }));

    expect(await screen.findByText(/f[áa]cil de adivinhar/i)).toBeInTheDocument();
  });

  it("desativa uma conta", async () => {
    const update = vi.fn().mockResolvedValue(account({ is_active: false }));
    const list = vi.fn().mockResolvedValue({ items: [account()], total: 1 });

    render(
      <UsersPage token={TOKEN} currentUserId="u-9" onList={list} onUpdate={update} />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /desativar/i }));

    await waitFor(() =>
      expect(update).toHaveBeenCalledWith(TOKEN, "u-1", { is_active: false }),
    );
  });

  it("não oferece desativar a própria conta", async () => {
    const list = vi
      .fn()
      .mockResolvedValue({ items: [account({ id: "u-9", role: "admin" })], total: 1 });

    render(<UsersPage token={TOKEN} currentUserId="u-9" onList={list} />);

    await screen.findByText("joao@belovale");
    expect(
      screen.queryByRole("button", { name: /desativar/i }),
    ).not.toBeInTheDocument();
  });
});

describe("ChangePasswordForm", () => {
  it("envia a senha atual e a nova", async () => {
    const change = vi.fn().mockResolvedValue(undefined);

    render(<ChangePasswordForm token={TOKEN} onChange={change} />);

    fireEvent.change(screen.getByLabelText(/senha atual/i), {
      target: { value: "capim elefante molhado" },
    });
    fireEvent.change(screen.getByLabelText(/nova senha/i), {
      target: { value: "bezerra no pasto" },
    });
    fireEvent.click(screen.getByRole("button", { name: /trocar senha/i }));

    await waitFor(() =>
      expect(change).toHaveBeenCalledWith(
        TOKEN,
        "capim elefante molhado",
        "bezerra no pasto",
      ),
    );
  });

  it("confirma quando a troca dá certo", async () => {
    render(
      <ChangePasswordForm token={TOKEN} onChange={vi.fn().mockResolvedValue(undefined)} />,
    );

    fireEvent.change(screen.getByLabelText(/senha atual/i), {
      target: { value: "capim elefante molhado" },
    });
    fireEvent.change(screen.getByLabelText(/nova senha/i), {
      target: { value: "bezerra no pasto" },
    });
    fireEvent.click(screen.getByRole("button", { name: /trocar senha/i }));

    expect(await screen.findByText(/senha alterada/i)).toBeInTheDocument();
  });

  it("mostra o motivo quando a senha atual está errada", async () => {
    const change = vi.fn().mockRejectedValue(
      Object.assign(new Error("403"), {
        status: 403,
        body: { detail: "Senha atual incorreta." },
      }),
    );

    render(<ChangePasswordForm token={TOKEN} onChange={change} />);

    fireEvent.change(screen.getByLabelText(/senha atual/i), {
      target: { value: "errada demais" },
    });
    fireEvent.change(screen.getByLabelText(/nova senha/i), {
      target: { value: "bezerra no pasto" },
    });
    fireEvent.click(screen.getByRole("button", { name: /trocar senha/i }));

    expect(await screen.findByText(/senha atual incorreta/i)).toBeInTheDocument();
  });
});
