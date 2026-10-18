import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PageViewer } from "@/components/evidence/PageViewer";
import { claim, src } from "./fixtures";

describe("PageViewer", () => {
  it("picks the source on that page and builds the image url", () => {
    const c = claim(
      "A",
      [5, 48],
      [
        src("fact", "f5", [5]),
        src("chunk", "p25L_k", [48], "Tỷ lệ CASA: 40,4 %"),
      ],
    );
    render(<PageViewer claim={c} page={48} onClose={vi.fn()} />);
    const img = screen.getByRole("img", {
      name: "Trang 48",
    }) as HTMLImageElement;
    expect(new URL(img.src).searchParams.get("source")).toBe("chunk:p25L_k");
    expect(screen.getByText("Trang 48")).toBeTruthy();
  });

  it("loads without highlight when no source matches the page", () => {
    const c = claim("A", [7], [src("fact", "f5", [5])]);
    render(<PageViewer claim={c} page={7} onClose={vi.fn()} />);
    const img = screen.getByRole("img", {
      name: "Trang 7",
    }) as HTMLImageElement;
    expect(new URL(img.src).searchParams.has("source")).toBe(false);
  });

  it("falls back to evidence text when the image fails", () => {
    const c = claim(
      "A",
      [48],
      [src("chunk", "p25L_k", [48], "Tỷ lệ CASA: 40,4 %")],
    );
    render(<PageViewer claim={c} page={48} onClose={vi.fn()} />);
    fireEvent.error(screen.getByRole("img", { name: "Trang 48" }));
    expect(screen.getByText(/Tỷ lệ CASA: 40,4 %/)).toBeTruthy();
    expect(screen.getByText(/thiếu file PDF/)).toBeTruthy();
    expect(screen.queryByRole("img", { name: "Trang 48" })).toBeNull();
  });

  it("resets the fallback when the page changes", () => {
    const c = claim("A", [48, 49]);
    const { rerender } = render(
      <PageViewer claim={c} page={48} onClose={vi.fn()} />,
    );
    fireEvent.error(screen.getByRole("img", { name: "Trang 48" }));
    rerender(<PageViewer claim={c} page={49} onClose={vi.fn()} />);
    expect(screen.getByRole("img", { name: "Trang 49" })).toBeTruthy();
  });

  it("calls onClose", () => {
    const onClose = vi.fn();
    render(<PageViewer claim={claim("A", [1])} page={1} onClose={onClose} />);
    fireEvent.click(screen.getByRole("button", { name: "Đóng" }));
    expect(onClose).toHaveBeenCalled();
  });
});
