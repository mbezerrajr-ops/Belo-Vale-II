import { useState, type FormEvent } from "react";

import { login } from "../api/client";
import type { LoginResult } from "../api/types";

interface LoginFormProps {
  onLoggedIn: (result: LoginResult) => void;
}

type LoginState = "idle" | "submitting" | "error";

export function LoginForm({ onLoggedIn }: LoginFormProps): JSX.Element {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [state, setState] = useState<LoginState>("idle");

  const handleSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setState("submitting");
    try {
      const result = await login(email, password);
      onLoggedIn(result);
    } catch {
      // The backend intentionally returns the same 401 for an unknown email
      // and a wrong password, so the UI can't and shouldn't distinguish them.
      setState("error");
    }
  };

  return (
    <form onSubmit={handleSubmit} aria-label="Entrar">
      <label>
        E-mail
        <input
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
        />
      </label>
      <label>
        Senha
        <input
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          required
        />
      </label>
      <button type="submit" disabled={state === "submitting"}>
        {state === "submitting" ? "Entrando…" : "Entrar"}
      </button>
      {state === "error" ? <p role="alert">E-mail ou senha inválidos.</p> : null}
    </form>
  );
}
