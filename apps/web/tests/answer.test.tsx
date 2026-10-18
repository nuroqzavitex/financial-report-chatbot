import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AnswerCard } from "@/components/answer/AnswerCard";
import { CalcChip } from "@/components/answer/CalcChip";
import { answer, calc, claim, op } from "./fixtures";

describe("AnswerCard", () => {
  it("renders claims with one chip per page and notes", () => {
    render(
      <AnswerCard
        answer={answer({
          claims: [claim("Tổng tài sản 1.192 nghìn tỷ đồng.", [5, 48])],
          notes: ["Số liệu tổng quan đã được làm tròn từ số kiểm toán."],
        })}
        onCite={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Xem trang 5" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Xem trang 48" })).toBeTruthy();
    expect(screen.getByText(/đã được làm tròn/)).toBeTruthy();
    expect(screen.getByText("Đã xác minh")).toBeTruthy();
  });

  it("citation click reports claim and page", async () => {
    const onCite = vi.fn();
    const c = claim("A", [59]);
    render(<AnswerCard answer={answer({ claims: [c] })} onCite={onCite} />);
    await userEvent.click(screen.getByRole("button", { name: "Xem trang 59" }));
    expect(onCite).toHaveBeenCalledWith(c, 59);
  });

  it("refusal shows the code-written text and no chips", () => {
    render(
      <AnswerCard
        answer={answer({
          status: "refused",
          claims: [],
          notes: [
            "Không tìm thấy thông tin này trong Báo cáo thường niên 2025.",
          ],
        })}
        onCite={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /Xem trang/ })).toBeNull();
    expect(screen.getByText("Không tìm thấy")).toBeTruthy();
  });

  it("maps partial and error badges", () => {
    const { rerender } = render(
      <AnswerCard answer={answer({ status: "partial" })} onCite={vi.fn()} />,
    );
    expect(screen.getByText("Một phần")).toBeTruthy();
    rerender(
      <AnswerCard answer={answer({ status: "error" })} onCite={vi.fn()} />,
    );
    expect(screen.getByText("Lỗi")).toBeTruthy();
  });

  it("copy button copies answer.text", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText");
    render(
      <AnswerCard answer={answer({ text: "Nội dung" })} onCite={vi.fn()} />,
    );
    await user.click(screen.getByRole("button", { name: /Sao chép/ }));
    expect(writeText).toHaveBeenCalledWith("Nội dung");
    expect(await screen.findByText("Đã sao chép")).toBeTruthy();
  });
});

describe("CalcChip", () => {
  it("shows formula and operands", async () => {
    render(
      <CalcChip
        calc={calc({
          rendered: "tăng 21,82%",
          formula: "(a - b) / b",
          operands: [
            op("Tổng tài sản", "FY2025", "1.192.344.137", 297),
            op("Tổng tài sản", "FY2024", "978.798.549", 297),
          ],
        })}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /tăng 21,82%/ }));
    expect(screen.getByText("(a - b) / b")).toBeTruthy();
    expect(screen.getAllByText(/\[tr\. 297\]/)).toHaveLength(2);
  });
});
