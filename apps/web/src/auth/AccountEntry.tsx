import { useState, type FormEvent } from "react";
import { LoginForm } from "./LoginForm";
import { accountRequest } from "../api/client";
import { ApiError, type LoginResult } from "../api/types";

export function apiMessage(error: unknown): string {
  const detail = error instanceof ApiError ? error.body.detail : null;
  return typeof detail === "string" ? detail : "Não foi possível concluir. Confira a conexão e tente novamente.";
}

export function AccountEntry({ onLoggedIn }: { onLoggedIn: (result: LoginResult) => void | Promise<void> }): JSX.Element {
  const query = new URLSearchParams(window.location.search);
  const initial = query.get("action");
  const [mode, setMode] = useState(initial === "verify" ? "verify" : initial === "reset" ? "recover-password" : "login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [producer, setProducer] = useState("");
  const [farm, setFarm] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent): Promise<void> {
    event.preventDefault(); setBusy(true); setError(null); setMessage(null);
    try {
      const body = mode === "register" ? { email, password, producer_name: producer, farm_name: farm }
        : mode === "forgot-password" ? { email }
        : { token: query.get("token") ?? "", ...(mode === "recover-password" ? { password } : {}) };
      const result = await accountRequest(mode, body);
      setMessage(result.message);
      setPassword("");
      if (mode === "verify" || mode === "recover-password") window.history.replaceState(null, "", "/");
    } catch (caught) { setError(apiMessage(caught)); }
    finally { setBusy(false); }
  }
  const labels: Record<string, string> = { register: "Criar conta de produtor", "forgot-password": "Recuperar acesso", verify: "Confirmar e-mail", "recover-password": "Escolher nova senha" };
  return <>
    {mode === "login" ? <LoginForm onLoggedIn={onLoggedIn} /> : (
      <form onSubmit={(event) => void submit(event)} className="account-entry">
        <h2>{labels[mode]}</h2>
        {(mode === "register" || mode === "forgot-password") && <><label htmlFor="account-email">Seu e-mail</label><input id="account-email" type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></>}
        {mode === "register" && <><label htmlFor="producer-name">Seu nome ou nome da empresa</label><input id="producer-name" required maxLength={255} value={producer} onChange={(e) => setProducer(e.target.value)} /><label htmlFor="first-farm">Nome da fazenda</label><input id="first-farm" required maxLength={255} value={farm} onChange={(e) => setFarm(e.target.value)} /></>}
        {(mode === "register" || mode === "recover-password") && <><label htmlFor="account-password">Nova senha</label><input id="account-password" type="password" autoComplete="new-password" required minLength={12} value={password} onChange={(e) => setPassword(e.target.value)} /><p className="hint">Use uma frase longa, com pelo menos 12 caracteres.</p></>}
        <button type="submit" disabled={busy}>{busy ? "Aguarde…" : labels[mode]}</button>
      </form>
    )}
    {message && <p role="status">{message}</p>}
    {error && <p role="alert">{error}</p>}
    <div className="send-photo-actions">
      {mode !== "login" ? <button type="button" className="link-btn" onClick={() => { setMode("login"); setError(null); setMessage(null); }}>Voltar para entrar</button> : <>
        <button type="button" className="link-btn" onClick={() => setMode("register")}>Sou produtor: criar conta</button>
        <button type="button" className="link-btn" onClick={() => setMode("forgot-password")}>Esqueci minha senha</button>
      </>}
    </div>
  </>;
}
