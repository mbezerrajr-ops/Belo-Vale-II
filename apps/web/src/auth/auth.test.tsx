import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

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
