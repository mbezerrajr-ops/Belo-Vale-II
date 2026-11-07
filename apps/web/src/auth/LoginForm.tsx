import { useEffect, useState, type FormEvent } from "react";

import { login } from "../api/client";
import { ApiError, type LoginResult } from "../api/types";
import { Icons } from "../ui/Brand";

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
  if (error.status >= 500 || ![400, 401, 403, 422, 429].includes(error.status)) return SERVER_DOWN;
  const detail = (error.body as { detail?: unknown }).detail;
  if (typeof detail !== "string") return GENERIC_ERROR;
  if (error.status === 429 || error.status === 403) return detail;
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
  // Só a resposta sobre a credencial marca os campos: sem sinal, a senha
  // pode estar certa.
  const [badCredentials, setBadCredentials] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [capsLock, setCapsLock] = useState(false);
  // Entrar precisa de sinal: dizer isso antes de a pessoa digitar a senha.
  const [online, setOnline] = useState(() => navigator.onLine !== false);
  useEffect(() => {
    const up = (): void => setOnline(true);
    const down = (): void => setOnline(false);
    window.addEventListener("online", up);
    window.addEventListener("offline", down);
    return () => {
      window.removeEventListener("online", up);
      window.removeEventListener("offline", down);
    };
  }, []);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setState("submitting");
    setShowPassword(false);
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const result = await login(email, password, controller.signal);
      window.clearTimeout(timer);
      // Aguardado: se abrir a conta falhar, o erro cai aqui, e não fica
      // solto com o botão travado em "Entrando…".
      await onLoggedIn(result);
    } catch (error) {
      const text = loginError(error);
      setMessage(text);
      setBadCredentials(text === GENERIC_ERROR);
      setState("error");
    } finally {
      window.clearTimeout(timer);
    }
  };

  const failed = state === "error";
  const invalid = failed && badCredentials ? true : undefined;

  return (
    <form onSubmit={handleSubmit} aria-label="Entrar">
      <h2>Entrar</h2>
      <p className="sub">Entre com seu e-mail e senha para acessar sua fazenda.</p>
      {!online && (
        <p className="warning login-offline" role="status">
          Sem sinal. Para entrar, este aparelho precisa de conexão; depois de entrar, o que você lançar
          sem sinal fica guardado.
        </p>
      )}
      <label htmlFor="login-email">E-mail</label>
      <input
        id="login-email"
        name="email"
        type="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        autoComplete="username"
        inputMode="email"
        // Teclado do celular: sem maiúscula nem correção no e-mail, e a
        // tecla de ação leva para a senha.
        autoCapitalize="none"
        autoCorrect="off"
        spellCheck={false}
        enterKeyHint="next"
        aria-invalid={invalid}
        aria-describedby={failed ? "login-error" : undefined}
        required
      />
      <label htmlFor="login-password">Senha</label>
      <div className="password-field">
        <input
          id="login-password"
          name="password"
          type={showPassword ? "text" : "password"}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          onKeyUp={(event) => setCapsLock(event.getModifierState("CapsLock"))}
          onBlur={() => setCapsLock(false)}
          autoComplete="current-password"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          enterKeyHint="go"
          aria-invalid={invalid}
          aria-describedby={
            [failed ? "login-error" : "", capsLock ? "login-caps" : ""].filter(Boolean).join(" ") ||
            undefined
          }
          required
        />
        {/* No sol, sem ver o que se digita, errar a senha é o mais comum. */}
        <button
          type="button"
          className="password-toggle"
          aria-pressed={showPassword}
          aria-label={showPassword ? "Esconder senha" : "Mostrar senha"}
          onClick={() => setShowPassword((shown) => !shown)}
        >
          {showPassword ? <Icons.olhoFechado /> : <Icons.olho />}
        </button>
      </div>
      {capsLock && (
        <p className="caps-hint" id="login-caps">
          Caps Lock ligado — a senha diferencia maiúsculas.
        </p>
      )}
      {/* Antes do botão: embaixo dele, com o teclado aberto, sumia. */}
      {failed && (
        <p role="alert" id="login-error">
          {message}
        </p>
      )}
      <button type="submit" disabled={state === "submitting"}>
        {state === "submitting" ? "Entrando…" : "Entrar"}
      </button>
      <p className="login-help">
        Você também pode pedir ao administrador uma senha provisória, gerada em Equipe.
      </p>
    </form>
  );
}
