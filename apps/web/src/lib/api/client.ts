import { clientId } from "@/lib/clientId";
import { parseSse } from "@/lib/sse";
import type {
  ChatAnswer,
  Health,
  SessionDetail,
  SessionSummary,
  SourceDTO,
  StatusEvent,
} from "./types";

export type {
  CalcDTO,
  ChatAnswer,
  ClaimDTO,
  Health,
  SessionDetail,
  SessionSummary,
  SourceDTO,
  StatusEvent,
  StoredMessage,
} from "./types";

export interface ChatHandlers {
  onStatus(s: StatusEvent): void;
  onAnswer(a: ChatAnswer): void;
  onError(msg: string): void;
}

const EVIDENCE_MAX = 500;
const NETWORK_ERROR = "Không kết nối được máy chủ, vui lòng thử lại.";

export function apiUrl(path: string): string {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  return base.replace(/\/+$/, "") + path;
}

function owner(): Record<string, string> {
  return { "X-Client-Id": clientId() };
}

export async function health(): Promise<Health> {
  const res = await fetch(apiUrl("/v1/health"));
  if (!res.ok) throw new Error(`health ${res.status}`);
  return (await res.json()) as Health;
}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { message?: string };
    if (body.message) return body.message;
  } catch {
    /* fall through */
  }
  return `HTTP ${res.status}`;
}

export async function streamChat(
  body: { session_id?: string; message: string },
  handlers: ChatHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let res: Response;
  try {
    res = await fetch(apiUrl("/v1/chat"), {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "text/event-stream",
        ...owner(),
      },
      body: JSON.stringify(body),
      signal,
    });
  } catch {
    if (signal?.aborted) return;
    handlers.onError(NETWORK_ERROR);
    return;
  }
  if (!res.ok) {
    handlers.onError(await errorMessage(res));
    return;
  }
  if (!res.body) {
    handlers.onError("Phản hồi rỗng");
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let carry = "";
  let terminal = false;
  const dispatch = (events: { event: string; data: string }[]) => {
    for (const ev of events) {
      let payload: unknown;
      try {
        payload = JSON.parse(ev.data);
      } catch {
        continue;
      }
      if (ev.event === "status") handlers.onStatus(payload as StatusEvent);
      else if (ev.event === "answer") {
        terminal = true;
        handlers.onAnswer(payload as ChatAnswer);
      } else if (ev.event === "error") {
        terminal = true;
        handlers.onError((payload as { message?: string }).message ?? "Lỗi");
      }
    }
  };
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      const r = parseSse(decoder.decode(value, { stream: true }), carry);
      carry = r.carry;
      dispatch(r.events);
    }
    dispatch(parseSse(decoder.decode() + "\n\n", carry).events);
    if (!terminal && !signal?.aborted)
      handlers.onError("Kết nối bị ngắt, vui lòng thử lại.");
  } catch {
    if (signal?.aborted) return;
    handlers.onError(NETWORK_ERROR);
  }
}

export class NotFound extends Error {}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(apiUrl(path), { headers: owner() });
  if (res.status === 404) throw new NotFound(await errorMessage(res));
  if (!res.ok) throw new Error(await errorMessage(res));
  return (await res.json()) as T;
}

export async function listSessions(): Promise<SessionSummary[]> {
  return (await getJson<{ sessions: SessionSummary[] }>("/v1/sessions"))
    .sessions;
}

export function getSession(id: string): Promise<SessionDetail> {
  return getJson<SessionDetail>(`/v1/sessions/${encodeURIComponent(id)}`);
}

export async function deleteSession(id: string): Promise<void> {
  const res = await fetch(apiUrl(`/v1/sessions/${encodeURIComponent(id)}`), {
    method: "DELETE",
    headers: owner(),
  });
  if (!res.ok && res.status !== 404) throw new Error(await errorMessage(res));
}

export function pageImageUrl(printed: number, source?: SourceDTO): string {
  const url = new URL(apiUrl(`/v1/pages/${printed}/image`));
  if (source) {
    url.searchParams.set("source", `${source.kind}:${source.id}`);
    url.searchParams.set("evidence", source.evidence.slice(0, EVIDENCE_MAX));
  }
  return url.toString();
}
