import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ChatAnswer } from "@/lib/api/client";
import { answer } from "./fixtures";

type Handlers = {
  onStatus(s: { step: string; label: string }): void;
  onAnswer(a: ChatAnswer): void;
  onError(m: string): void;
};
const calls: {
  body: { session_id?: string; message: string };
  h: Handlers;
  signal?: AbortSignal;
}[] = [];

const getSession = vi.fn();

vi.mock("@/lib/api/client", () => ({
  NotFound: class NotFound extends Error {},
  getSession: (id: string) => getSession(id),
  streamChat: vi.fn(
    async (
      body: { session_id?: string; message: string },
      h: Handlers,
      signal?: AbortSignal,
    ) => {
      calls.push({ body, h, signal });
    },
  ),
}));

import { useChat } from "@/hooks/useChat";
import { NotFound } from "@/lib/api/client";

beforeEach(() => {
  calls.length = 0;
  localStorage.clear();
});
afterEach(() => vi.clearAllMocks());

describe("useChat", () => {
  it("keeps session id and ignores sends while busy", async () => {
    const { result } = renderHook(() => useChat());
    act(() => result.current.send("một"));
    act(() => result.current.send("hai"));
    expect(calls).toHaveLength(1);
    expect(result.current.busy).toBe(true);
    expect(result.current.messages).toEqual([{ role: "user", text: "một" }]);

    act(() => calls[0].h.onStatus({ step: "x", label: "Đang tìm" }));
    expect(result.current.status).toBe("Đang tìm");

    const a = answer({ session_id: "sess-9" });
    act(() => calls[0].h.onAnswer(a));
    await waitFor(() => expect(result.current.busy).toBe(false));
    expect(result.current.status).toBeNull();
    expect(result.current.sessionId).toBe("sess-9");
    expect(localStorage.getItem("ircb.last-session")).toBe("sess-9");
    expect(result.current.messages[1]).toEqual({
      role: "assistant",
      answer: a,
    });

    act(() => result.current.send("ba"));
    expect(calls[1].body).toEqual({ session_id: "sess-9", message: "ba" });
  });

  it("records errors and reset clears session and aborts", async () => {
    const { result } = renderHook(() => useChat());
    act(() => result.current.send("một"));
    act(() => calls[0].h.onAnswer(answer({ session_id: "old" })));
    await waitFor(() => expect(result.current.busy).toBe(false));

    act(() => result.current.send("hai"));
    expect(calls[1].body.session_id).toBe("old");
    act(() => calls[1].h.onError("hỏng"));
    expect(result.current.messages[3]).toEqual({ role: "error", text: "hỏng" });
    expect(result.current.busy).toBe(false);

    act(() => result.current.send("ba"));
    act(() => result.current.reset());
    expect(calls[2].signal?.aborted).toBe(true);
    expect(result.current.messages).toEqual([]);
    expect(result.current.busy).toBe(false);

    act(() => result.current.send("bốn"));
    expect(calls[3].body.session_id).toBeUndefined();
    expect(localStorage.getItem("ircb.last-session")).toBeNull();
  });

  it("a reload reopens the last conversation and continues it", async () => {
    const a = answer({ session_id: "sess-1" });
    getSession.mockResolvedValue({
      id: "sess-1",
      title: "một",
      messages: [
        { role: "user", content: "một", created_at: "", answer: null },
        { role: "assistant", content: a.text, created_at: "", answer: a },
        { role: "assistant", content: "Câu cũ.", created_at: "", answer: null },
      ],
    });
    localStorage.setItem("ircb.last-session", "sess-1");
    const { result } = renderHook(() => useChat());
    await waitFor(() => expect(result.current.messages).toHaveLength(3));
    expect(getSession).toHaveBeenCalledWith("sess-1");
    expect(result.current.messages).toEqual([
      { role: "user", text: "một" },
      { role: "assistant", answer: a },
      { role: "legacy", text: "Câu cũ." },
    ]);
    act(() => result.current.send("hai"));
    expect(calls[0].body.session_id).toBe("sess-1");
  });

  it("a remembered conversation that is gone starts fresh", async () => {
    getSession.mockRejectedValue(new NotFound("x"));
    localStorage.setItem("ircb.last-session", "gone");
    const { result } = renderHook(() => useChat());
    await waitFor(() => expect(result.current.sessionId).toBeNull());
    expect(result.current.messages).toEqual([]);
    expect(localStorage.getItem("ircb.last-session")).toBeNull();
    act(() => result.current.send("một"));
    expect(calls[0].body.session_id).toBeUndefined();
  });

  it("onSaved fires after a stored answer", async () => {
    const onSaved = vi.fn();
    const { result } = renderHook(() => useChat({ onSaved }));
    act(() => result.current.send("một"));
    act(() => calls[0].h.onAnswer(answer({ session_id: "s" })));
    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
  });

  it("aborts on unmount", () => {
    const { result, unmount } = renderHook(() => useChat());
    act(() => result.current.send("một"));
    unmount();
    expect(calls[0].signal?.aborted).toBe(true);
  });
});
