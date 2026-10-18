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

vi.mock("@/lib/api/client", () => ({
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
    expect(localStorage.length).toBe(0);
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
  });

  it("a new mount (page reload) starts a fresh conversation", async () => {
    localStorage.setItem("ircb.session", "stale"); // written by an older build
    const first = renderHook(() => useChat());
    act(() => first.result.current.send("một"));
    expect(calls[0].body.session_id).toBeUndefined();
    act(() => calls[0].h.onAnswer(answer({ session_id: "sess-1" })));
    await waitFor(() => expect(first.result.current.busy).toBe(false));
    first.unmount();

    const second = renderHook(() => useChat());
    expect(second.result.current.messages).toEqual([]);
    act(() => second.result.current.send("hai"));
    expect(calls[1].body.session_id).toBeUndefined();
  });

  it("aborts on unmount", () => {
    const { result, unmount } = renderHook(() => useChat());
    act(() => result.current.send("một"));
    unmount();
    expect(calls[0].signal?.aborted).toBe(true);
  });
});
