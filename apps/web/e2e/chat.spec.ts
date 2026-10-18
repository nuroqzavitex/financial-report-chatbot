import { expect, test } from "@playwright/test";

type Frame = [string, unknown];

function sseBody(frames: Frame[]): string {
  return frames
    .map(([ev, data]) => `event: ${ev}\ndata: ${JSON.stringify(data)}\n\n`)
    .join("");
}

const answerFixture = {
  session_id: "s1",
  status: "answered",
  text: "Dư nợ vay tăng 26,9% [tr. 59].",
  claims: [
    {
      text: "Dư nợ vay RBG năm 2025 tăng 26,9%.",
      printed_pages: [59],
      citation: "[tr. 59]",
      sources: [
        {
          kind: "chunk",
          id: "p30R_k",
          printed_pages: [59],
          evidence: "Dư nợ vay tăng 26,9%",
        },
      ],
    },
  ],
  notes: [],
  calcs: [],
  conflict_kind: null,
  trace_id: "t1",
  latency_ms: {},
  cost_usd: "0",
};

test.beforeEach(async ({ page }) => {
  await page.route("**/v1/chat", (r) =>
    r.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: sseBody([
        ["status", { step: "prefetch", label: "Đang tìm trong báo cáo…" }],
        ["answer", answerFixture],
        ["done", { session_id: "s1", trace_id: "t1" }],
      ]),
    }),
  );
  await page.route("**/v1/pages/59/image**", (r) =>
    r.fulfill({
      status: 200,
      contentType: "image/png",
      path: "e2e/fixtures/page.png",
    }),
  );
});

async function ask(page: import("@playwright/test").Page) {
  await page.goto("/");
  await page
    .getByRole("textbox", { name: "Câu hỏi" })
    .fill("Dư nợ vay RBG năm 2025?");
  await page.keyboard.press("Enter");
}

test("ask -> click [tr. 59] -> see page 59", async ({ page }) => {
  await ask(page);
  const reqPromise = page.waitForRequest(/\/v1\/pages\/59\/image/);
  await page.getByRole("button", { name: "Xem trang 59" }).click();
  await expect(page.getByRole("img", { name: "Trang 59" })).toBeVisible();
  const req = await reqPromise;
  expect(new URL(req.url()).searchParams.get("source")).toBe("chunk:p30R_k");
});

test("narrow screen shows the page in a sheet and closes it", async ({
  page,
}) => {
  await page.setViewportSize({ width: 600, height: 800 });
  await ask(page);
  await page.getByRole("button", { name: "Xem trang 59" }).click();
  await expect(page.getByRole("img", { name: "Trang 59" })).toBeVisible();
  await page.getByRole("button", { name: "Đóng" }).click();
  await expect(page.getByRole("img", { name: "Trang 59" })).toHaveCount(0);
});

test("missing PDF falls back to the evidence text", async ({ page }) => {
  await page.route("**/v1/pages/59/image**", (r) =>
    r.fulfill({
      status: 503,
      contentType: "application/json",
      body: '{"code":"pdf_missing"}',
    }),
  );
  await ask(page);
  await page.getByRole("button", { name: "Xem trang 59" }).click();
  await expect(page.getByText(/thiếu file PDF/)).toBeVisible();
  await expect(
    page.getByText("Dư nợ vay tăng 26,9%", { exact: true }),
  ).toBeVisible();
});
