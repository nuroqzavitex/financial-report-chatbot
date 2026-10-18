export interface SseEvent {
  event: string;
  data: string;
}

/** Incremental SSE parser. Frames end at a blank line; `carry` holds the unfinished tail. */
export function parseSse(
  chunk: string,
  carry: string,
): { events: SseEvent[]; carry: string } {
  let buffer = carry + chunk;
  // Hold back a trailing CR: it may be the first half of a CRLF split across chunks.
  let held = "";
  if (buffer.endsWith("\r")) {
    held = "\r";
    buffer = buffer.slice(0, -1);
  }
  buffer = buffer.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const frames = buffer.split("\n\n");
  const rest = frames.pop() ?? "";
  const events: SseEvent[] = [];
  for (const frame of frames) {
    let event = "message";
    const data: string[] = [];
    for (const line of frame.split("\n")) {
      if (line === "" || line.startsWith(":")) continue;
      const idx = line.indexOf(":");
      const field = idx === -1 ? line : line.slice(0, idx);
      let value = idx === -1 ? "" : line.slice(idx + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "event") event = value;
      else if (field === "data") data.push(value);
    }
    if (data.length > 0 || event !== "message")
      events.push({ event, data: data.join("\n") });
  }
  return { events, carry: rest + held };
}
