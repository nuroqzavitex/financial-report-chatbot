import { describe, expect, it } from "vitest";
import { parseSse } from "@/lib/sse";

describe("parseSse", () => {
  it("parses frames split across chunks", () => {
    let r = parseSse(
      'event: status\ndata: {"step":"rewrite"}\n\nevent: ans',
      "",
    );
    expect(r.events).toEqual([{ event: "status", data: '{"step":"rewrite"}' }]);
    r = parseSse('wer\ndata: {"a":1}\n\n', r.carry);
    expect(r.events).toEqual([{ event: "answer", data: '{"a":1}' }]);
  });
  it("handles CRLF frames", () => {
    expect(
      parseSse("event: done\r\ndata: {}\r\n\r\n", "").events[0].event,
    ).toBe("done");
  });
  it("joins multi-line data", () => {
    const r = parseSse("event: answer\ndata: a\ndata: b\n\n", "");
    expect(r.events).toEqual([{ event: "answer", data: "a\nb" }]);
  });
});

describe("parseSse CRLF split", () => {
  it("keeps CR+LF split across chunks as one line break", () => {
    let r = parseSse("event: answer\r", "");
    r = parseSse('\ndata: {"a":1}\r\n\r\n', r.carry);
    expect(r.events).toEqual([{ event: "answer", data: '{"a":1}' }]);
  });
});
