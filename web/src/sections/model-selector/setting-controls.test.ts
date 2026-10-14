import {
  maxReasoningStop,
  minReasoningStop,
} from "@/sections/model-selector/setting-controls";

describe("minReasoningStop", () => {
  it("floors at low when the model never stops reasoning", () => {
    expect(minReasoningStop(["low", "medium", "high", "xhigh"])).toBe(1);
  });

  it("allows off when the model supports it", () => {
    expect(minReasoningStop(["off", "low", "medium", "high"])).toBe(0);
  });

  it("parks at zero for an older backend that sends nothing", () => {
    expect(minReasoningStop(undefined)).toBe(0);
  });

  it("parks at zero when the model takes no effort parameter", () => {
    expect(minReasoningStop([])).toBe(0);
    expect(maxReasoningStop([])).toBe(-1);
  });
});
