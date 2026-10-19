import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HistoryPanel, whenLabel } from "@/components/history/HistoryPanel";
import type { SessionSummary } from "@/lib/api/client";

const session = (id: string, title: string): SessionSummary => ({
  id,
  title,
  created_at: "2026-10-19T02:00:00Z",
  updated_at: "2026-10-19T02:00:00Z",
  n_messages: 2,
});

function setup(over: Partial<Parameters<typeof HistoryPanel>[0]> = {}) {
  const props = {
    sessions: [session("a", "Tổng tài sản 2025?"), session("b", "RBG là gì?")],
    activeId: "b",
    failed: false,
    onOpen: vi.fn(),
    onNew: vi.fn(),
    onDelete: vi.fn(),
    onRetry: vi.fn(),
    ...over,
  };
  render(<HistoryPanel {...props} />);
  return props;
}

describe("HistoryPanel", () => {
  it("lists sessions, marks the open one and opens on click", async () => {
    const p = setup();
    const open = screen.getByRole("button", { name: /^RBG là gì\?/ });
    expect(open.getAttribute("aria-current")).toBe("true");
    await userEvent.click(
      screen.getByRole("button", { name: /^Tổng tài sản/ }),
    );
    expect(p.onOpen).toHaveBeenCalledWith("a");
    await userEvent.click(
      screen.getByRole("button", { name: "Cuộc trò chuyện mới" }),
    );
    expect(p.onNew).toHaveBeenCalled();
  });

  it("deletes only after confirmation", async () => {
    const confirm = vi.spyOn(window, "confirm");
    const p = setup();
    const del = screen.getByRole("button", { name: "Xoá “RBG là gì?”" });
    confirm.mockReturnValueOnce(false);
    await userEvent.click(del);
    expect(p.onDelete).not.toHaveBeenCalled();
    confirm.mockReturnValueOnce(true);
    await userEvent.click(del);
    expect(p.onDelete).toHaveBeenCalledWith("b");
  });

  it("shows an empty invitation and a retry on failure", async () => {
    setup({ sessions: [] });
    expect(screen.getByText(/Chưa có cuộc trò chuyện nào/)).toBeTruthy();
  });

  it("retry is offered when the list failed to load", async () => {
    const p = setup({ failed: true });
    await userEvent.click(screen.getByRole("button", { name: "Thử lại" }));
    expect(p.onRetry).toHaveBeenCalled();
  });
});

describe("whenLabel", () => {
  const now = new Date(2026, 9, 19, 15, 0);
  it("time today, 'Hôm qua' yesterday, date before", () => {
    expect(whenLabel(new Date(2026, 9, 19, 9, 5).toISOString(), now)).toBe(
      "09:05",
    );
    expect(whenLabel(new Date(2026, 9, 18, 23, 0).toISOString(), now)).toBe(
      "Hôm qua",
    );
    expect(whenLabel(new Date(2026, 9, 1, 8, 0).toISOString(), now)).toBe(
      "01/10/2026",
    );
  });
});
