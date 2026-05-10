"use client";

import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/interfaces/settings";

/**
 * @deprecated Use `useTierAtLeast(Tier.BUSINESS)` (any paid tier) or
 * `useTierAtLeast(Tier.ENTERPRISE)` (ENTERPRISE only) directly. This
 * hook is kept as an alias of `useTierAtLeast(Tier.BUSINESS)` so
 * existing call sites compile and behave identically.
 */
export function usePaidEnterpriseFeaturesEnabled(): boolean {
  return useTierAtLeast(Tier.BUSINESS);
}
