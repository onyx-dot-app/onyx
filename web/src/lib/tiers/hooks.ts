"use client";

import { useCallback, useMemo } from "react";
import { useTranslations } from "next-intl";
import type { SelectOption, SelectOptions } from "@opal/components";
import { SvgArrowUpCircle, SvgOrganization, SvgUsers } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { markdown } from "@opal/utils";
import type { PlanColor, PlanMetadata } from "@/lib/tiers/types";
import { Tier } from "@/lib/tiers/types";
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
  Tier,
  {
    color: PlanColor;
    icon: IconFunctionComponent | undefined;
    // The tier's key under `common.plans`; the UI calls COMMUNITY "Free".
    copyKey: "free" | "business" | "enterprise";
  }
> = {
  [Tier.COMMUNITY]: { color: "gray", icon: undefined, copyKey: "free" },
  [Tier.BUSINESS]: { color: "green", icon: SvgUsers, copyKey: "business" },
  [Tier.ENTERPRISE]: {
    color: "amber",
    icon: SvgOrganization,
    copyKey: "enterprise",
  },
};

/**
 * The app's plan badges and their copy, by tier. Use these wherever a
 * feature is limited to a tier, so every such feature reads the same.
 */
export function usePlans(): Record<Tier, PlanMetadata> {
  const t = useTranslations("common.plans");
  return useMemo(() => {
    const metadata = (tier: Tier): PlanMetadata => {
      const { color, icon, copyKey } = PLAN_STYLES[tier];
      const title: string = t(`${copyKey}.title`);
      return {
        title,
        icon,
        color,
        tag: { title, color, icon },
        tooltip: markdown(t(`${copyKey}.tooltip`)),
      };
    };
    return {
      [Tier.COMMUNITY]: metadata(Tier.COMMUNITY),
      [Tier.BUSINESS]: metadata(Tier.BUSINESS),
      [Tier.ENTERPRISE]: metadata(Tier.ENTERPRISE),
    };
  }, [t]);
}

// The value of the "Upgrade Plan" row. It is a link, so it is never picked.
const UPGRADE_PLAN_VALUE = "upgrade-plan";

/**
 * Lays out a select's options that need `required`. Below that tier: an
 * "Upgrade Plan" row linking to billing, then the options, disabled, under an
 * "Available for {Plan}" divider. At or above it: the options as they are.
 *
 *   const lockForBusiness = useTierLockedOptions(Tier.BUSINESS);
 *   options={[...everyTier, ...lockForBusiness(businessOnly)]}
 */
export function useTierLockedOptions(
  required: Tier
): (options: SelectOption[]) => SelectOptions {
  const t = useTranslations("common.plans");
  const plans = usePlans();
  const locked: boolean = !useTierAtLeast(required);
  return useCallback(
    (options: SelectOption[]): SelectOptions =>
      locked
        ? [
            {
              options: [
                {
                  value: UPGRADE_PLAN_VALUE,
                  title: t("upgrade.label"),
                  icon: SvgArrowUpCircle,
                  href: "/admin/billing",
                },
              ],
            },
            {
              title: t("availableFor", { plan: plans[required].title }),
              options: options.map((option) => ({ ...option, disabled: true })),
            },
          ]
        : options,
    [locked, t, plans, required]
  );
}
