import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";

describe("frontend workspace", () => {
  it("keeps the web application private", async () => {
    const manifest = JSON.parse(
      await readFile("apps/web/package.json", "utf8"),
    ) as {
      private?: boolean;
    };

    expect(manifest.private).toBe(true);
  });
});
