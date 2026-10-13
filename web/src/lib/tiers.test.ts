import { Tier } from "@/lib/settings/types";
import { LLM_GATEWAY_MIN_TIER, tierAtLeast } from "@/lib/tiers";

describe("LLM Gateway tier", () => {
  it("allows Business and Enterprise, but not Community", () => {
    expect(LLM_GATEWAY_MIN_TIER).toBe(Tier.BUSINESS);
    expect(tierAtLeast(Tier.COMMUNITY, LLM_GATEWAY_MIN_TIER)).toBe(false);
    expect(tierAtLeast(Tier.BUSINESS, LLM_GATEWAY_MIN_TIER)).toBe(true);
    expect(tierAtLeast(Tier.ENTERPRISE, LLM_GATEWAY_MIN_TIER)).toBe(true);
  });
});
