"use client";

import { Tier } from "@/lib/settings/types";
import { tierAtLeast } from "@/lib/tiers";
import { useSettings } from "@/lib/settings/hooks";

/**
 * True when the current tenant's tier is `required` or higher.
 *
 *   useTierAtLeast(Tier.BUSINESS)   // BUSINESS or ENTERPRISE
 *   useTierAtLeast(Tier.ENTERPRISE) // ENTERPRISE only
 *
 * Returns false when the tier is undefined (loading, no license).
 */
export function useTierAtLeast(required: Tier): boolean {
  const settings = useSettings();
  return tierAtLeast(settings.tier, required);
}
