import { clientId } from "@/lib/clientId";

// Inlined at build time: with a key the web requires a Clerk sign-in, without one it runs
// anonymously with a per-browser id (the API decides the same way from its own settings).
export const AUTH_ENABLED = Boolean(
  process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY,
);

type TokenSource = () => Promise<string | null>;
let tokenSource: TokenSource | null = null;

/** Set by the sign-in gate while a user is signed in; cleared on sign-out. */
export function setTokenSource(source: TokenSource | null): void {
  tokenSource = source;
}

/** Who is asking: the Clerk session token when signed in, else the browser id. */
export async function ownerHeaders(): Promise<Record<string, string>> {
  if (tokenSource) {
    const token = await tokenSource();
    return token ? { Authorization: `Bearer ${token}` } : {};
  }
  return { "X-Client-Id": clientId() };
}
