import { useState } from "react";

import { changeOwnPassword } from "../../api/client";

/** Troca da própria senha. Disponível a qualquer usuário. */

type ChangeFn = (
  token: string,
  currentPassword: string,
  newPassword: string,
) => Promise<void>;

interface Props {
  token: string;
  onChange?: ChangeFn;
}

function errorMessage(error: unknown): string {
  const body = (error as { body?: { detail?: string } })?.body;
  return body?.detail ?? "Não foi possível trocar a senha. Tente novamente.";
}

export function ChangePasswordForm({
  token,
  onChange = changeOwnPassword,
}: Props): JSX.Element {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function submit(): Promise<void> {
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      await onChange(token, current, next);
      setDone(true);
      setCurrent("");
      setNext("");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className="change-password"
      onSubmit={(event) => {
        event.preventDefault();
        void submit();
      }}
    >
      <h3>Trocar minha senha</h3>
      <label htmlFor="current-password">Senha atual</label>
      <input
        id="current-password"
        type="password"
        value={current}
        onChange={(event) => setCurrent(event.target.value)}
        autoComplete="current-password"
      />
      <label htmlFor="new-password">Nova senha</label>
      <input
        id="new-password"
        type="password"
        value={next}
        onChange={(event) => setNext(event.target.value)}
        autoComplete="new-password"
      />
      <p className="hint">Pelo menos 8 caracteres.</p>
      {error && <p role="alert">{error}</p>}
      {done && <p className="notice">Senha alterada.</p>}
      <button type="submit" disabled={busy}>
        Trocar senha
      </button>
    </form>
  );
}
