// A random id per browser, sent as X-Client-Id so the API keeps each browser's history apart.
// It is not sign-in: whoever holds the id sees those conversations.
const KEY = "ircb.client-id";
let memory: string | null = null;

function fresh(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

export function clientId(): string {
  try {
    const stored = localStorage.getItem(KEY);
    if (stored) return stored;
    const id = fresh();
    localStorage.setItem(KEY, id);
    return id;
  } catch {
    // storage blocked (private mode): history lasts for this page only
    memory ??= fresh();
    return memory;
  }
}

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
