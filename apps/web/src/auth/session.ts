const SESSION_STORAGE_KEY = "belo-vale.session-token";

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
  } catch {
    // Nothing to clean up if storage was never reachable.
  }
}
