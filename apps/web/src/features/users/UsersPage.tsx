import { useEffect, useState } from "react";

import { createUser, listUsers, updateUser } from "../../api/client";
import type { Role, UserAccount, UserPage } from "../../api/types";

/**
 * Gestão de contas, só para o dono.
 *
 * A regra de senha aparece na tela antes de o dono tentar criar a conta, para
 * ele não descobrir o requisito por erro. Desativar a própria conta não é
 * oferecido — o servidor também recusa, mas esconder evita a frustração.
 */

type ListFn = (token: string) => Promise<UserPage>;
type CreateFn = (
  token: string,
  email: string,
  password: string,
  role: Role,
) => Promise<UserAccount>;
type UpdateFn = (
  token: string,
  userId: string,
  changes: { role?: Role; is_active?: boolean },
) => Promise<UserAccount>;

interface Props {
  token: string;
  currentUserId: string;
  onList?: ListFn;
  onCreate?: CreateFn;
  onUpdate?: UpdateFn;
}

const ROLE_LABEL: Record<string, string> = {
  operator: "Operador — envia fichas e consulta",
  reviewer: "Revisor — confere fichas e edita cadastro",
  admin: "Administrador — também gerencia contas",
};

function errorMessage(error: unknown): string {
  const body = (error as { body?: { detail?: string } })?.body;
  return body?.detail ?? "Não foi possível completar a ação. Tente novamente.";
}

export function UsersPage({
  token,
  currentUserId,
  onList = listUsers,
  onCreate = createUser,
  onUpdate = updateUser,
}: Props): JSX.Element {
  const [page, setPage] = useState<UserPage | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("operator");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function reload(): Promise<void> {
    try {
      setPage(await onList(token));
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  useEffect(() => {
    void reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function handleCreate(): Promise<void> {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const created = await onCreate(token, email.trim(), password, role);
      setNotice(`Conta criada para ${created.email}.`);
      setEmail("");
      setPassword("");
      await reload();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function toggleActive(user: UserAccount): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      await onUpdate(token, user.id, { is_active: !user.is_active });
      await reload();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="users">
      <h2>Contas</h2>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          void handleCreate();
        }}
      >
        <h3>Criar conta</h3>
        <label htmlFor="user-email">E-mail</label>
        <input
          id="user-email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          autoComplete="off"
        />
        <label htmlFor="user-password">Senha</label>
        <input
          id="user-password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          autoComplete="new-password"
        />
        <p className="hint">
          A senha precisa ter pelo menos 8 caracteres. Quanto mais longa, mais
          segura: uma frase com duas ou três palavras é fácil de lembrar e
          difícil de adivinhar.
        </p>
        <label htmlFor="user-role">Função</label>
        <select
          id="user-role"
          value={role}
          onChange={(event) => setRole(event.target.value as Role)}
        >
          <option value="operator">Operador</option>
          <option value="reviewer">Revisor</option>
          <option value="admin">Administrador</option>
        </select>
        <p className="hint">{ROLE_LABEL[role]}</p>
        <button type="submit" disabled={busy}>
          Criar conta
        </button>
      </form>

      {error && <p role="alert">{error}</p>}
      {notice && <p className="notice">{notice}</p>}

      <h3>Contas existentes</h3>
      {page === null ? (
        <p>Carregando…</p>
      ) : (
        <ul className="user-list">
          {page.items.map((user) => (
            <li key={user.id}>
              <span>{user.email}</span>
              <small>{ROLE_LABEL[user.role] ?? user.role}</small>
              {!user.is_active && <em>desativada</em>}
              {user.id !== currentUserId && (
                <button
                  type="button"
                  onClick={() => void toggleActive(user)}
                  disabled={busy}
                >
                  {user.is_active ? "Desativar" : "Reativar"}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
