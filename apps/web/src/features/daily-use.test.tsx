/**
 * Uso diário: senha provisória, baixa de animal e mensagens do login.
 *
 * Complementa os testes de cada tela com o que esta etapa acrescentou.
 */

import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LoginForm } from "../auth/LoginForm";
import { AnimalDetailPanel } from "./animals/AnimalDetailPanel";
import { AnimalSearchPage } from "./animals/AnimalSearchPage";
import { ChangePasswordForm } from "./users/ChangePasswordForm";
import { UsersPage } from "./users/UsersPage";
import type { AnimalDetail, UserAccount } from "../api/types";

// A ficha carrega o histórico de produção sozinha. Estes testes tratam de
// outras partes da ficha: o histórico fica "carregando" e não atualiza a
// tela depois que o teste termina.
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api/client")>()),
  getAnimalProduction: () => new Promise(() => {}),
}));

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

function animal(overrides: Partial<AnimalDetail> = {}): AnimalDetail {
  return {
    id: "a-1",
    farm_id: "f-1",
    brinco: "389",
    brinco_origem: "389",
    legacy_id: null,
    numero_legado: null,
    name: "ÁGATA",
    situacao: "Em lactação",
    status: "Ativo",
    ultimo_parto: null,
    nascimento: null,
    peso: null,
    observacoes: null,
    lote_atual: "LOTE 1",
    grupo_manejo: null,
    exited_on: null,
    exit_reason: null,
    exit_notes: null,
    historico_lotes: [],
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("Redefinir senha (administrador)", () => {
  it("gera a senha provisória e a mostra uma única vez", async () => {
    const reset = vi.fn().mockResolvedValue({
      temporary_password: "caju-pedra-rio-47",
      expires_at: "2026-09-21T12:00:00Z",
    });
    const list = vi.fn().mockResolvedValue({ items: [account()], total: 1 });

    render(<UsersPage token={TOKEN} currentUserId="u-9" onList={list} onReset={reset} />);

    fireEvent.click(await screen.findByRole("button", { name: /redefinir senha/i }));
    // Confirmação antes: redefinir derruba as sessões abertas da pessoa.
    expect(screen.getByText(/sessões abertas/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /gerar senha provisória/i }));

    await waitFor(() => expect(reset).toHaveBeenCalledWith(TOKEN, "u-1"));
    expect(await screen.findByText("caju-pedra-rio-47")).toBeInTheDocument();
    expect(screen.getByText(/não aparece de novo/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /já anotei/i }));
    expect(screen.queryByText("caju-pedra-rio-47")).not.toBeInTheDocument();
  });

  it("não oferece redefinir a própria conta", async () => {
    const list = vi.fn().mockResolvedValue({ items: [account({ id: "u-9" })], total: 1 });

    render(<UsersPage token={TOKEN} currentUserId="u-9" onList={list} />);

    await screen.findByText("joao@belovale");
    expect(screen.queryByRole("button", { name: /redefinir senha/i })).not.toBeInTheDocument();
  });

  it("marca a conta que ainda não trocou a senha provisória", async () => {
    const list = vi
      .fn()
      .mockResolvedValue({ items: [account({ reset_pending: true })], total: 1 });

    render(<UsersPage token={TOKEN} currentUserId="u-9" onList={list} />);

    expect(await screen.findByText(/aguardando nova senha/i)).toBeInTheDocument();
  });
});

describe("Troca de senha", () => {
  it("avisa quem a chamou quando a troca dá certo", async () => {
    const onChanged = vi.fn();
    render(
      <ChangePasswordForm
        token={TOKEN}
        onChange={vi.fn().mockResolvedValue(undefined)}
        onChanged={onChanged}
      />,
    );

    fireEvent.change(screen.getByLabelText(/senha atual/i), {
      target: { value: "caju-pedra-rio-47" },
    });
    fireEvent.change(screen.getByLabelText(/nova senha/i), {
      target: { value: "pitomba madura no pe" },
    });
    fireEvent.click(screen.getByRole("button", { name: /trocar senha/i }));

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });
});

describe("LoginForm", () => {
  function failWith(status: number, detail: string): void {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status,
      json: async () => ({ detail }),
    }) as unknown as typeof fetch;
  }

  async function submit(): Promise<void> {
    fireEvent.change(screen.getByLabelText("E-mail"), { target: { value: "joao@belovale" } });
    fireEvent.change(screen.getByLabelText("Senha"), { target: { value: "qualquer coisa" } });
    fireEvent.click(screen.getByRole("button", { name: "Entrar" }));
  }

  it("explica que a senha provisória expirou", async () => {
    const original = globalThis.fetch;
    failWith(401, "A senha provisória expirou. Peça ao administrador uma nova.");
    render(<LoginForm onLoggedIn={vi.fn()} />);

    await submit();

    expect(await screen.findByRole("alert")).toHaveTextContent(/provisória expirou/i);
    globalThis.fetch = original;
  });

  it("explica o bloqueio por excesso de tentativas", async () => {
    const original = globalThis.fetch;
    failWith(429, "Muitas tentativas de login. Tente novamente em 15 minuto(s).");
    render(<LoginForm onLoggedIn={vi.fn()} />);

    await submit();

    expect(await screen.findByRole("alert")).toHaveTextContent(/muitas tentativas/i);
    globalThis.fetch = original;
  });

  it("mantém a mensagem genérica para credencial errada", async () => {
    const original = globalThis.fetch;
    failWith(401, "Invalid email or password");
    render(<LoginForm onLoggedIn={vi.fn()} />);

    await submit();

    expect(await screen.findByRole("alert")).toHaveTextContent("E-mail ou senha inválidos.");
    globalThis.fetch = original;
  });
});

describe("Baixa de animal", () => {
  it("revisor registra a baixa com data, motivo e observação", async () => {
    const onExit = vi.fn().mockResolvedValue(animal());
    const onChanged = vi.fn();

    render(
      <AnimalDetailPanel
        token={TOKEN}
        animal={animal()}
        canEdit
        onChanged={onChanged}
        onExit={onExit}
        today="2026-09-18"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /dar baixa/i }));
    fireEvent.change(screen.getByLabelText(/motivo da baixa/i), {
      target: { value: "morte" },
    });
    fireEvent.change(screen.getByLabelText(/observação/i), {
      target: { value: "picada de cobra" },
    });
    fireEvent.click(screen.getByRole("button", { name: /confirmar baixa/i }));

    await waitFor(() =>
      expect(onExit).toHaveBeenCalledWith(
        TOKEN,
        "a-1",
        "2026-09-18",
        "morte",
        "picada de cobra",
      ),
    );
    expect(onChanged).toHaveBeenCalled();
  });

  it("operador não vê a baixa", () => {
    render(
      <AnimalDetailPanel token={TOKEN} animal={animal()} canEdit={false} onChanged={vi.fn()} />,
    );

    expect(screen.queryByRole("button", { name: /dar baixa/i })).not.toBeInTheDocument();
  });

  it("animal baixado mostra a saída e só oferece desfazer", async () => {
    const onUndoExit = vi.fn().mockResolvedValue(animal());
    render(
      <AnimalDetailPanel
        token={TOKEN}
        animal={animal({
          exited_on: "2026-09-12",
          exit_reason: "venda",
          exit_notes: "vendida para o vizinho",
          status: "Inativo",
          lote_atual: null,
        })}
        canEdit
        onChanged={vi.fn()}
        onUndoExit={onUndoExit}
      />,
    );

    const banner = screen.getByText(/baixa em 12\/09\/2026/i).closest("div, p") as HTMLElement;
    expect(within(banner).getByText(/venda/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /mudar de lote/i })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /desfazer baixa/i }));
    fireEvent.change(screen.getByLabelText(/por que desfazer/i), {
      target: { value: "baixa na vaca errada" },
    });
    fireEvent.click(screen.getByRole("button", { name: /confirmar e trazer de volta/i }));

    await waitFor(() =>
      expect(onUndoExit).toHaveBeenCalledWith(TOKEN, "a-1", "baixa na vaca errada"),
    );
  });

  it("a busca tem atalho para os animais que saíram do rebanho", async () => {
    const search = vi.fn().mockResolvedValue({
      items: [animal({ exited_on: "2026-09-12", exit_reason: "venda", lote_atual: null })],
      total: 1,
      limit: 25,
      offset: 0,
    });

    render(<AnimalSearchPage token={TOKEN} canEdit onOpen={vi.fn()} onSearch={search} />);
    await act(async () => {}); // a lista do rebanho, que abre sozinha

    fireEvent.click(screen.getByRole("button", { name: /baixados/i }));

    await waitFor(() => expect(search).toHaveBeenCalledWith(TOKEN, { rebanho: "baixados" }));
    expect(await screen.findByText(/baixa · venda/i)).toBeInTheDocument();
  });
});
