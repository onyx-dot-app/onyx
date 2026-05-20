"use client";

import { Tier } from "@/interfaces/settings";
import { tierAtLeast } from "@/lib/tiers";
import { useSettingsContext } from "@/providers/SettingsProvider";

/**
 * True when the current tenant's tier is `required` or higher.
 *
 *   useTierAtLeast(Tier.BUSINESS)   // BUSINESS or ENTERPRISE
 *   useTierAtLeast(Tier.ENTERPRISE) // ENTERPRISE only
 *
 * Returns false when the tier is undefined (loading, no license).
 */
export function useTierAtLeast(required: Tier): boolean {
  const settings = useSettingsContext();
  return tierAtLeast(settings?.settings.tier, required);
}
