import { afterEach, describe, expect, it, vi } from "vitest";
import {
  apiUrl,
  health,
  pageImageUrl,
  reportUrl,
  streamChat,
} from "@/lib/api/client";
import { citationLabel } from "@/lib/format";

function sseResponse(frames: string[]): Response {
  const enc = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      for (const f of frames) c.enqueue(enc.encode(f));
      c.close();
    },
  });
  return new Response(body, {
    status: 200,
    headers: { "content-type": "text/event-stream" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("client", () => {
  it("streamChat dispatches status then answer", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          sseResponse([
            'event: status\ndata: {"step":"rewrite","label":"x"}\n\n',
            'event: answer\ndata: {"status":"ok"}\n\nevent: do',
            'ne\ndata: {"session_id":"s","trace_id":"t"}\n\n',
          ]),
        ),
    );
    const seen: string[] = [];
    await streamChat(
      { message: "x" },
      {
        onStatus: () => seen.push("s"),
        onAnswer: () => seen.push("a"),
        onError: () => seen.push("e"),
      },
    );
    expect(seen).toEqual(["s", "a"]);
  });

  it("pageImageUrl encodes source and truncates evidence", () => {
    const u = new URL(
      pageImageUrl(59, {
        kind: "chunk",
        id: "p30R_k",
        printed_pages: [59],
        evidence: "x".repeat(900),
      }),
    );
    expect(u.pathname).toBe("/v1/pages/59/image");
    expect(u.searchParams.get("source")).toBe("chunk:p30R_k");
    expect(u.searchParams.get("evidence")!.length).toBe(500);
  });

  it("streamChat surfaces HTTP errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            code: "validation_error",
            message: "Tin nhắn trống",
          }),
          { status: 422 },
        ),
      ),
    );
    const errors: string[] = [];
    await streamChat(
      { message: "" },
      { onStatus: vi.fn(), onAnswer: vi.fn(), onError: (m) => errors.push(m) },
    );
    expect(errors).toEqual(["Tin nhắn trống"]);
  });

  it("streamChat forwards SSE error events", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          sseResponse([
            'event: error\ndata: {"code":"x","message":"hỏng"}\n\n',
          ]),
        ),
    );
    const errors: string[] = [];
    await streamChat(
      { message: "x" },
      { onStatus: vi.fn(), onAnswer: vi.fn(), onError: (m) => errors.push(m) },
    );
    expect(errors).toEqual(["hỏng"]);
  });

  it("apiUrl defaults to localhost:8000", () => {
    expect(apiUrl("/health")).toMatch(/\/health$/);
  });

  it("citationLabel formats pages", () => {
    expect(citationLabel([5])).toBe("[tr. 5]");
    expect(citationLabel([5, 48])).toBe("[tr. 5, 48]");
  });
});

describe("client fixes", () => {
  it("health fetches /v1/health", async () => {
    const f = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ status: "ok" })));
    vi.stubGlobal("fetch", f);
    await health();
    expect(String(f.mock.calls[0][0])).toMatch(/\/v1\/health$/);
  });

  it("reports an error when the stream ends without answer or error", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          sseResponse(['event: status\ndata: {"step":"a","label":"b"}\n\n']),
        ),
    );
    const errors: string[] = [];
    await streamChat(
      { message: "x" },
      { onStatus: vi.fn(), onAnswer: vi.fn(), onError: (m) => errors.push(m) },
    );
    expect(errors).toEqual(["Kết nối bị ngắt, vui lòng thử lại."]);
  });

  it("maps fetch exceptions to a Vietnamese message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    const errors: string[] = [];
    await streamChat(
      { message: "x" },
      { onStatus: vi.fn(), onAnswer: vi.fn(), onError: (m) => errors.push(m) },
    );
    expect(errors).toEqual(["Không kết nối được máy chủ, vui lòng thử lại."]);
  });

  it("maps mid-stream read exceptions to a Vietnamese message", async () => {
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        c.error(new TypeError("network error"));
      },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(body)));
    const errors: string[] = [];
    await streamChat(
      { message: "x" },
      { onStatus: vi.fn(), onAnswer: vi.fn(), onError: (m) => errors.push(m) },
    );
    expect(errors).toEqual(["Không kết nối được máy chủ, vui lòng thử lại."]);
  });
});

describe("reportUrl", () => {
  it("points at the whole report PDF on the API", () => {
    expect(reportUrl()).toBe(apiUrl("/v1/report.pdf"));
  });
});
