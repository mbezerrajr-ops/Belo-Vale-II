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
      // O backend devolve o mesmo 401 para e-mail desconhecido e senha errada,
      // então a interface não distingue — e não deve.
      setState("error");
    }
  };

  return (
    <form onSubmit={handleSubmit} aria-label="Entrar">
      <h2>Entrar</h2>
      <p className="sub">Use a conta criada pelo administrador da fazenda.</p>
      <label htmlFor="login-email">E-mail</label>
      <input
        id="login-email"
        type="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        autoComplete="username"
        inputMode="email"
        required
      />
      <label htmlFor="login-password">Senha</label>
      <input
        id="login-password"
        type="password"
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        autoComplete="current-password"
        required
      />
      <button type="submit" disabled={state === "submitting"}>
        {state === "submitting" ? "Entrando…" : "Entrar"}
      </button>
      {state === "error" ? <p role="alert">E-mail ou senha inválidos.</p> : null}
    </form>
  );
}
