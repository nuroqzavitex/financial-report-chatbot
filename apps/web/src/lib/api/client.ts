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
  const res = await fetch(apiUrl(path));
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
  });
  if (!res.ok && res.status !== 404) throw new Error(await errorMessage(res));
}

/** The whole annual report, opened inline by the browser's PDF viewer. */
export function reportUrl(): string {
  return apiUrl("/v1/report.pdf");
}

// Bumped when the API changes how evidence is highlighted, so images cached under the old
// one-day max-age are not shown again (2: red text instead of a yellow box).
const PAGE_IMAGE_VERSION = "2";

export function pageImageUrl(printed: number, source?: SourceDTO): string {
  const url = new URL(apiUrl(`/v1/pages/${printed}/image`));
  url.searchParams.set("v", PAGE_IMAGE_VERSION);
  if (source) {
    url.searchParams.set("source", `${source.kind}:${source.id}`);
    url.searchParams.set("evidence", source.evidence.slice(0, EVIDENCE_MAX));
  }
  return url.toString();
}
