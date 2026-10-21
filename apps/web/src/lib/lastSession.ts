// The session the chat reopens on load; a per-browser convenience, not account state.
const LAST = "ircb.last-session";

export function lastSession(): string | null {
  try {
    return localStorage.getItem(LAST);
  } catch {
    return null;
  }
}

export function rememberSession(id: string | null): void {
  try {
    if (id) localStorage.setItem(LAST, id);
    else localStorage.removeItem(LAST);
  } catch {
    /* per-viewer convenience only */
  }
}
