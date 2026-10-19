import { afterEach, describe, expect, it } from "vitest";
import { ownerHeaders, setTokenSource } from "@/lib/auth";

afterEach(() => setTokenSource(null));

describe("ownerHeaders", () => {
  it("sends the browser id when nobody is signed in", async () => {
    const h = await ownerHeaders();
    expect(h["X-Client-Id"]).toMatch(/^[0-9a-f]{32}$/);
    expect(h.Authorization).toBeUndefined();
    expect((await ownerHeaders())["X-Client-Id"]).toBe(h["X-Client-Id"]);
  });

  it("sends the Clerk session token, and only it, when signed in", async () => {
    setTokenSource(async () => "tok-123");
    expect(await ownerHeaders()).toEqual({ Authorization: "Bearer tok-123" });
  });

  it("sends nothing when the signed-in session has no token yet", async () => {
    setTokenSource(async () => null);
    expect(await ownerHeaders()).toEqual({});
  });
});
