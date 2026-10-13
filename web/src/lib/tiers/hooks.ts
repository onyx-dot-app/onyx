"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { SvgOrganization, SvgUsers } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { markdown } from "@opal/utils";
import type { Plan, PlanColor, PlanMetadata } from "@/lib/tiers/types";
import { Tier } from "@/lib/settings/types";
import { tierAtLeast } from "@/lib/tiers/utils";
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

const PLAN_STYLES: Record<
  Plan,
  { color: PlanColor; icon: IconFunctionComponent | undefined }
> = {
  free: { color: "gray", icon: undefined },
  business: { color: "green", icon: SvgUsers },
  enterprise: { color: "amber", icon: SvgOrganization },
};

/**
 * The app's plan badges and their copy, by plan. Use these wherever a
 * feature is limited to a plan, so every such feature reads the same.
 */
export function usePlans(): Record<Plan, PlanMetadata> {
  const t = useTranslations("common.plans");
  return useMemo(() => {
    const metadata = (plan: Plan): PlanMetadata => {
      const { color, icon } = PLAN_STYLES[plan];
      const title: string = t(`${plan}.title`);
      return {
        title,
        icon,
        color,
        tag: { title, color, icon },
        tooltip: markdown(t(`${plan}.tooltip`)),
      };
    };
    return {
      free: metadata("free"),
      business: metadata("business"),
      enterprise: metadata("enterprise"),
    };
  }, [t]);
}
