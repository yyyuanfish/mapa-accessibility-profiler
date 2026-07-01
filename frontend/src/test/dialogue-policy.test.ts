import { describe, expect, it } from "vitest";
import { extractTriageFromText } from "@/lib/dialogue-policy";

describe("extractTriageFromText", () => {
  it("detects mobility and simple-language needs in a mixed free-text answer", () => {
    const flags = extractTriageFromText(
      "I use a wheelchair and need step-free routes. I also have trouble reading long texts, so please keep instructions short.",
    );

    expect(flags.wheelchair).toBe(true);
    expect(flags.step_free).toBe(true);
    expect(flags.simple_lang).toBe(true);
  });
});
