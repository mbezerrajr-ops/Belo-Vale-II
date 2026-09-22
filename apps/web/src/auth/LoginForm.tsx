import { useState, type FormEvent } from "react";

import { login } from "../api/client";
import { ApiError, type LoginResult } from "../api/types";

interface LoginFormProps {
  /** Pode ser assíncrono (abrir a conta depois do login): a falha dele
   *  também tem de soltar o botão e dizer o motivo. */
  onLoggedIn: (result: LoginResult) => void | Promise<void>;
  /** Quanto esperar o servidor antes de desistir. Menor nos testes. */
  timeoutMs?: number;
}

type LoginState = "idle" | "submitting" | "error";

const GENERIC_ERROR = "E-mail ou senha inválidos.";
const NO_CONNECTION =
  "Sem conexão com o sistema. Confira o sinal ou o Wi-Fi e tente de novo — a senha não foi testada.";
const TOO_SLOW =
  "O sistema demorou a responder. Confira o sinal e tente de novo — a senha não foi testada.";
const SERVER_DOWN =
  "O sistema está fora do ar agora. Tente de novo em alguns minutos; se continuar, avise o administrador.";

/** Prazo para o login responder. Com sinal fraco, sem prazo, "Entrando…"
 *  ficava para sempre. */
export const LOGIN_TIMEOUT_MS = 20_000;

/**
 * Mensagem para quem tentou entrar.
 *
 * Credencial errada recebe sempre a mesma frase: o backend não distingue
 * e-mail desconhecido de senha errada, e a tela também não. As outras
 * respostas — bloqueio por excesso de tentativas, senha provisória vencida —
 * não revelam nada a quem está chutando e dizem ao usuário o que fazer.
 *
 * O que não é resposta sobre a credencial não pode parecer senha errada:
 * sem sinal, prazo estourado e servidor fora do ar têm frase própria. Antes,
 * tudo virava "inválidos", e a pessoa tentava de novo até ser bloqueada.
 */
function loginError(error: unknown): string {
  if (error instanceof DOMException && error.name === "AbortError") return TOO_SLOW;
  // É assim que o fetch avisa que nem chegou ao servidor.
  if (error instanceof TypeError) return NO_CONNECTION;
  if (!(error instanceof ApiError)) return SERVER_DOWN;
  if (error.status >= 500 || ![400, 401, 422, 429].includes(error.status)) return SERVER_DOWN;
  const detail = (error.body as { detail?: unknown }).detail;
  if (typeof detail !== "string") return GENERIC_ERROR;
  if (error.status === 429) return detail;
  if (error.status === 401 && detail.includes("provisória")) return detail;
  return GENERIC_ERROR;
}

export function LoginForm({
  onLoggedIn,
  timeoutMs = LOGIN_TIMEOUT_MS,
}: LoginFormProps): JSX.Element {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [state, setState] = useState<LoginState>("idle");
  const [message, setMessage] = useState(GENERIC_ERROR);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setState("submitting");
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const result = await login(email, password, controller.signal);
      window.clearTimeout(timer);
      // Aguardado: se abrir a conta falhar, o erro cai aqui, e não fica
      // solto com o botão travado em "Entrando…".
      await onLoggedIn(result);
    } catch (error) {
      setMessage(loginError(error));
      setState("error");
    } finally {
      window.clearTimeout(timer);
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
