import { useState, type FormEvent } from "react";

import { login } from "../api/client";
import { ApiError, type LoginResult } from "../api/types";

interface LoginFormProps {
  onLoggedIn: (result: LoginResult) => void;
}

type LoginState = "idle" | "submitting" | "error";

const GENERIC_ERROR = "E-mail ou senha inválidos.";

/**
 * Mensagem para quem tentou entrar.
 *
 * Credencial errada recebe sempre a mesma frase: o backend não distingue
 * e-mail desconhecido de senha errada, e a tela também não. As outras
 * respostas — bloqueio por excesso de tentativas, senha provisória vencida —
 * não revelam nada a quem está chutando e dizem ao usuário o que fazer.
 */
function loginError(error: unknown): string {
  if (!(error instanceof ApiError)) return GENERIC_ERROR;
  const detail = (error.body as { detail?: unknown }).detail;
  if (typeof detail !== "string") return GENERIC_ERROR;
  if (error.status === 429) return detail;
  if (error.status === 401 && detail.includes("provisória")) return detail;
  return GENERIC_ERROR;
}

export function LoginForm({ onLoggedIn }: LoginFormProps): JSX.Element {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [state, setState] = useState<LoginState>("idle");
  const [message, setMessage] = useState(GENERIC_ERROR);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setState("submitting");
    try {
      const result = await login(email, password);
      onLoggedIn(result);
    } catch (error) {
      setMessage(loginError(error));
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
      {state === "error" ? <p role="alert">{message}</p> : null}
    </form>
  );
}
