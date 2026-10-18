import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MessageList } from "@/components/chat/MessageList";

const props = { status: null, onCite: vi.fn(), onPick: vi.fn() };

afterEach(() => {
  delete (Element.prototype as { scrollIntoView?: unknown }).scrollIntoView;
});

describe("MessageList", () => {
  it("scrolls the newest item into view when messages change", () => {
    const spy = vi.fn();
    Element.prototype.scrollIntoView = spy;
    const { rerender } = render(
      <MessageList
        {...props}
        busy={false}
        messages={[{ role: "user", text: "a" }]}
      />,
    );
    const n = spy.mock.calls.length;
    expect(n).toBeGreaterThan(0);
    rerender(
      <MessageList
        {...props}
        busy={false}
        messages={[
          { role: "user", text: "a" },
          { role: "user", text: "b" },
        ]}
      />,
    );
    expect(spy.mock.calls.length).toBeGreaterThan(n);
  });

  it("does not crash when scrollIntoView is missing", () => {
    render(
      <MessageList {...props} busy messages={[{ role: "user", text: "a" }]} />,
    );
  });
});
