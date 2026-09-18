import { useEffect, useState, type CSSProperties } from "react";

import { createUser, listUsers, resetUserPassword, updateUser } from "../../api/client";
import type { PasswordReset, Role, UserAccount, UserPage } from "../../api/types";

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

type ResetFn = (token: string, userId: string) => Promise<PasswordReset>;

interface Props {
  token: string;
  currentUserId: string;
  onList?: ListFn;
  onCreate?: CreateFn;
  onUpdate?: UpdateFn;
  onReset?: ResetFn;
}

function until(iso: string): string {
  const moment = new Date(iso);
  return moment.toLocaleString("pt-BR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

const ROLE_LABEL: Record<string, string> = {
  operator: "Operador — lança a produção e consulta",
  reviewer: "Revisor — confere fichas e edita cadastro",
  admin: "Administrador — também gerencia contas",
};

const ROLE_SHORT: Record<string, string> = {
  operator: "Operador",
  reviewer: "Revisor",
  admin: "Administrador",
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
  onReset = resetUserPassword,
}: Props): JSX.Element {
  const [page, setPage] = useState<UserPage | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("operator");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [confirmReset, setConfirmReset] = useState<UserAccount | null>(null);
  const [issued, setIssued] = useState<(PasswordReset & { email: string }) | null>(null);

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

  async function handleReset(user: UserAccount): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      const result = await onReset(token, user.id);
      setConfirmReset(null);
      setIssued({ ...result, email: user.email });
      await reload();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function copyIssued(): Promise<void> {
    if (issued === null) return;
    try {
      await navigator.clipboard?.writeText(issued.temporary_password);
      setNotice("Senha copiada.");
    } catch {
      // Sem permissão de área de transferência: a senha continua na tela.
    }
  }

  return (
    <section className="users">
      <h2>Contas</h2>
      <p className="muted">Cada pessoa com a sua conta: é o que dá nome a cada alteração.</p>

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
          inputMode="email"
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
          Senha inicial, com pelo menos 8 caracteres. A pessoa escolhe a própria
          senha no primeiro acesso — esta serve só para entrar a primeira vez.
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

      {confirmReset !== null && (
        <div className="confirm-box" role="dialog" aria-label="Redefinir senha">
          <p>
            Gerar uma senha provisória para <strong>{confirmReset.email}</strong>? As
            sessões abertas dessa conta serão encerradas, e a pessoa terá de escolher
            uma senha nova no primeiro acesso.
          </p>
          <div className="row-fix-actions">
            <button
              type="button"
              onClick={() => void handleReset(confirmReset)}
              disabled={busy}
            >
              Gerar senha provisória
            </button>
            <button type="button" className="secondary" onClick={() => setConfirmReset(null)}>
              Cancelar
            </button>
          </div>
        </div>
      )}

      {issued !== null && (
        <div className="temp-password" role="status">
          <p>
            Senha provisória de <strong>{issued.email}</strong>:
          </p>
          <code>{issued.temporary_password}</code>
          <p className="hint">
            Vale até {until(issued.expires_at)}. Repasse agora: ela não aparece de novo.
          </p>
          <div className="row-fix-actions">
            <button type="button" className="secondary" onClick={() => void copyIssued()}>
              Copiar
            </button>
            <button type="button" onClick={() => setIssued(null)}>
              Já anotei
            </button>
          </div>
        </div>
      )}

      <h3>Contas existentes</h3>
      {page === null ? (
        error ? (
          <button type="button" className="secondary" onClick={() => void reload()}>
            Tentar de novo
          </button>
        ) : (
          <div className="skeleton" style={{ height: 56 }} />
        )
      ) : (
        <ul className="user-list">
          {page.items.map((user, index) => (
            <li key={user.id} style={{ "--i": index } as CSSProperties}>
              <span className="avatar" aria-hidden="true">
                {user.email.slice(0, 2)}
              </span>
              <span>{user.email}</span>
              <span className="role-pill">{ROLE_SHORT[user.role] ?? user.role}</span>
              <small>{ROLE_LABEL[user.role]?.split(" — ")[1] ?? ""}</small>
              {!user.is_active && <em>desativada</em>}
              {user.reset_pending && <em className="pending">aguardando nova senha</em>}
              {user.id !== currentUserId && (
                <span className="user-actions">
                  {user.is_active && (
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => {
                        setIssued(null);
                        setConfirmReset(user);
                      }}
                      disabled={busy}
                    >
                      Redefinir senha
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => void toggleActive(user)}
                    disabled={busy}
                  >
                    {user.is_active ? "Desativar" : "Reativar"}
                  </button>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
