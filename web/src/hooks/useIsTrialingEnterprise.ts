"use client";

import { Tier } from "@/interfaces/settings";
import { BillingStatus, hasActiveSubscription } from "@/lib/billing/interfaces";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { useBillingInformation } from "@/hooks/useBillingInformation";

/**
 * True when the current tenant is on a Business subscription but is being
 * shown Enterprise features for the duration of their trial.
 *
 * `settings.tier` already reflects the promoted ENTERPRISE tier (the backend
 * applies the trial-business → enterprise rule at read time), so this hook
 * is for *messaging only* — it tells the UI to say "you're trialing
 * Enterprise" rather than "you're on Enterprise". Do NOT use it for feature
 * gating; use `useTierAtLeast` instead.
 */
export function useIsTrialingEnterprise(): boolean {
  const settings = useSettingsContext();
  const { data } = useBillingInformation();

  if (settings?.settings.tier !== Tier.ENTERPRISE) return false;
  if (!data || !hasActiveSubscription(data)) return false;
  return data.status === BillingStatus.TRIALING;
}
