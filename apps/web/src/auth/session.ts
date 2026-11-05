import type { CurrentUser } from "../api/types";

const SESSION_STORAGE_KEY = "belo-vale.session-token";
const USER_STORAGE_KEY = "belo-vale.session-user";
const OFFLINE_USER_KEY = "belo-vale.offline-user";
const OFFLINE_MAX_AGE = 7 * 24 * 60 * 60 * 1000;

// O token curto fica só na aba. A retomada online usa o cookie HttpOnly;
// offline, uma identidade local com validade permite guardar trabalho,
// sem conceder autorização de escrita no servidor.
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
  try { localStorage.removeItem(OFFLINE_USER_KEY); } catch { /* Armazenamento bloqueado. */ }
}

/**
 * Identidade vista com sinal. A cópia local permite reabrir sem rede por
 * até sete dias; sair voluntariamente a remove. Nunca contém credenciais.
 */
export function storeUser(user: CurrentUser): void {
  try {
    sessionStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user));
    // Identidade local com validade, nunca senha ou token persistente.
    localStorage.setItem(OFFLINE_USER_KEY, JSON.stringify({ user, at: Date.now() }));
  } catch {
    // Sem armazenamento: recarregar sem sinal pede login, como antes.
  }
}

export function loadStoredUser(): CurrentUser | null {
  try {
    const raw = sessionStorage.getItem(USER_STORAGE_KEY);
    if (raw) return JSON.parse(raw) as CurrentUser;
    const saved = JSON.parse(localStorage.getItem(OFFLINE_USER_KEY) ?? "null") as { user: CurrentUser; at: number } | null;
    return saved && Date.now() - saved.at >= 0 && Date.now() - saved.at <= OFFLINE_MAX_AGE ? saved.user : null;
  } catch {
    return null;
  }
}
