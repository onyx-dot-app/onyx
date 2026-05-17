import { Tier } from "@/interfaces/settings";

export const TIER_RANK: Record<Tier, number> = {
  [Tier.COMMUNITY]: 0,
  [Tier.BUSINESS]: 1,
  [Tier.ENTERPRISE]: 2,
};

export function tierAtLeast(
  current: Tier | undefined,
  required: Tier
): boolean {
  if (current === undefined) return false;
  return TIER_RANK[current] >= TIER_RANK[required];
}
