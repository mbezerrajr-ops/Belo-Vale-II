import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { LoginResult } from "../api/types";
import { LoginForm } from "./LoginForm";
import { clearStoredToken, loadStoredToken, storeToken } from "./session";

describe("LoginForm", () => {
  it("calls onLoggedIn with the token on success", async () => {
    const user = userEvent.setup();
    const result: LoginResult = { access_token: "abc.def.ghi", token_type: "bearer", expires_in: 900 };
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => result,
    }) as unknown as typeof fetch;

    const onLoggedIn = vi.fn();
    render(<LoginForm onLoggedIn={onLoggedIn} />);

    await user.type(screen.getByLabelText("E-mail"), "reviewer@example.com");
    await user.type(screen.getByLabelText("Senha"), "correct horse battery staple");
    await user.click(screen.getByRole("button", { name: "Entrar" }));

    await waitFor(() => expect(onLoggedIn).toHaveBeenCalledWith(result));
    globalThis.fetch = originalFetch;
  });

  it("shows a generic error on invalid credentials without leaking which field was wrong", async () => {
    const user = userEvent.setup();
    const originalFetch = globalThis.fetch;
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      json: async () => ({ code: "invalid_credentials" }),
    }) as unknown as typeof fetch;

    render(<LoginForm onLoggedIn={vi.fn()} />);

    await user.type(screen.getByLabelText("E-mail"), "reviewer@example.com");
    await user.type(screen.getByLabelText("Senha"), "wrong password");
    await user.click(screen.getByRole("button", { name: "Entrar" }));

    expect(await screen.findByText(/e-mail ou senha inválidos/i)).toBeVisible();
    globalThis.fetch = originalFetch;
  });
});

describe("LoginForm — o que dizer quando não entra", () => {
  // No curral o sinal cai. Antes, qualquer falha virava "E-mail ou senha
  // inválidos": a pessoa tentava de novo e podia cair no bloqueio por
  // excesso de tentativas, por um problema que não era a senha.
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.useRealTimers();
  });

  async function tryLogin(): Promise<void> {
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("E-mail"), "reviewer@example.com");
    await user.type(screen.getByLabelText("Senha"), "uma senha qualquer");
    await user.click(screen.getByRole("button", { name: "Entrar" }));
  }

  function respond(status: number, body: unknown): void {
    globalThis.fetch = vi.fn().mockResolvedValue({
      ok: status < 400,
      status,
      json: async () => {
        if (body === null) throw new SyntaxError("não é JSON");
        return body;
      },
    }) as unknown as typeof fetch;
  }

  it("sem conexão, diz que é a conexão", async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new TypeError("Failed to fetch")) as unknown as typeof fetch;
    render(<LoginForm onLoggedIn={vi.fn()} />);

    await tryLogin();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/sem conexão/i);
    expect(alert).not.toHaveTextContent(/inválidos/i);
    expect(screen.getByRole("button", { name: "Entrar" })).toBeEnabled();
  });

  it("servidor fora do ar (resposta do proxy, sem JSON) não é senha errada", async () => {
    respond(502, null);
    render(<LoginForm onLoggedIn={vi.fn()} />);

    await tryLogin();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/fora do ar/i);
    expect(alert).not.toHaveTextContent(/inválidos/i);
  });

  it("autenticação indisponível (503) também não é senha errada", async () => {
    respond(503, { detail: "Authentication is not configured" });
    render(<LoginForm onLoggedIn={vi.fn()} />);

    await tryLogin();

    expect(await screen.findByRole("alert")).toHaveTextContent(/fora do ar/i);
  });

  it("bloqueio por tentativas mostra o que o servidor explicou", async () => {
    respond(429, { detail: "Muitas tentativas de login. Tente de novo em 5 minutos." });
    render(<LoginForm onLoggedIn={vi.fn()} />);

    await tryLogin();

    expect(await screen.findByRole("alert")).toHaveTextContent(/muitas tentativas/i);
  });

  it("não fica em 'Entrando…' para sempre quando o servidor não responde", async () => {
    globalThis.fetch = vi.fn(
      (_url: unknown, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          );
        }),
    ) as unknown as typeof fetch;
    render(<LoginForm onLoggedIn={vi.fn()} timeoutMs={50} />);

    await tryLogin();

    expect(await screen.findByRole("alert")).toHaveTextContent(/demorou/i);
    expect(screen.getByRole("button", { name: "Entrar" })).toBeEnabled();
  });

  it("falha depois do login (ao abrir a conta) não trava o botão", async () => {
    respond(200, { access_token: "t", token_type: "bearer", expires_in: 900 });
    const onLoggedIn = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    render(<LoginForm onLoggedIn={onLoggedIn} />);

    await tryLogin();

    expect(await screen.findByRole("alert")).toHaveTextContent(/sem conexão/i);
    expect(screen.getByRole("button", { name: "Entrar" })).toBeEnabled();
  });
});

describe("session storage", () => {
  beforeEach(() => {
    clearStoredToken();
  });

  it("round-trips a token through sessionStorage", () => {
    expect(loadStoredToken()).toBeNull();
    storeToken("a-token");
    expect(loadStoredToken()).toBe("a-token");
    clearStoredToken();
    expect(loadStoredToken()).toBeNull();
  });
});
