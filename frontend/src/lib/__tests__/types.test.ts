import { describe, it, expect } from "vitest";
import { PROMPT_KEYS } from "@/lib/types";

describe("PROMPT_KEYS", () => {
  it("lists the eight prompt keys", () => {
    expect(PROMPT_KEYS).toHaveLength(8);
    expect(PROMPT_KEYS).toContain("new_signal");
  });
});
