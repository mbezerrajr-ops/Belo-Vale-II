import type { CurrentUser } from "../api/types";

const SESSION_STORAGE_KEY = "belo-vale.session-token";
const USER_STORAGE_KEY = "belo-vale.session-user";

// sessionStorage, not localStorage: the token does not survive closing the
// tab/browser. There is no "remember me" — every new browser session
// requires a fresh login. This is a deliberate, documented limitation, not
// an oversight; the backend's bearer tokens are short-lived (auth_token_ttl
// seconds) regardless of where the frontend keeps them.
export function loadStoredToken(): string | null {
  try {
    return sessionStorage.getItem(SESSION_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function storeToken(token: string): void {
  try {
    sessionStorage.setItem(SESSION_STORAGE_KEY, token);
  } catch {
    // Storage can be unavailable (private browsing, quota); the session
    // still works for the current render, it just won't survive a reload.
  }
}

export function clearStoredToken(): void {
  try {
    sessionStorage.removeItem(SESSION_STORAGE_KEY);
    sessionStorage.removeItem(USER_STORAGE_KEY);
  } catch {
    // Nothing to clean up if storage was never reachable.
  }
}

/**
 * Quem está nesta aba, para recarregar sem sinal. Mesma vida do token (a
 * aba), e só o que a tela usa para se montar — o servidor continua sendo
 * quem decide o que cada um pode fazer.
 */
export function storeUser(user: CurrentUser): void {
  try {
    sessionStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user));
  } catch {
    // Sem armazenamento: recarregar sem sinal pede login, como antes.
  }
}

export function loadStoredUser(): CurrentUser | null {
  try {
    const raw = sessionStorage.getItem(USER_STORAGE_KEY);
    return raw ? (JSON.parse(raw) as CurrentUser) : null;
  } catch {
    return null;
  }
}
