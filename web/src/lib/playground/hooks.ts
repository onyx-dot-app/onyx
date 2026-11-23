"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { markdown } from "@opal/utils";
import type { RichStr } from "@opal/types";
import { CONTACT_SALES_URL } from "@/lib/constants";
import {
  PLAYGROUND_FEATURE_PLAN,
  type PlaygroundRestrictedFeature,
} from "@/lib/playground/types";
import { useSettings } from "@/lib/settings/hooks";
import type { Tier } from "@/lib/tiers/types";

/** The features the playground restricts. Empty off the playground. */
export function usePlaygroundRestrictions(): ReadonlySet<PlaygroundRestrictedFeature> {
  const { playground_restrictions } = useSettings();
  return useMemo(
    () => new Set(playground_restrictions ?? []),
    [playground_restrictions]
  );
}

export interface PlaygroundRestriction {
  /** True when the feature is restricted on this deployment. */
  restricted: boolean;
  /** The plan that includes the feature, for a badge. Absent for a feature that is simply off. */
  plan: Tier | undefined;
  title: string;
  description: RichStr;
  tooltip: string;
}

/**
 * Whether `featureKey` is restricted here, with the copy every restricted
 * surface shows: a short title, the one-line reason with the sales link, and a
 * tooltip for a disabled control.
 *
 *   const { restricted, plan } = usePlaygroundRestriction("sso");
 *
 * Pass `undefined` for a surface without a feature key: it is never restricted.
 */
export function usePlaygroundRestriction(
  featureKey: PlaygroundRestrictedFeature | undefined
): PlaygroundRestriction {
  const t = useTranslations("common.playground");
  const restrictions = usePlaygroundRestrictions();
  const restricted = featureKey !== undefined && restrictions.has(featureKey);
  const plan: Tier | undefined =
    featureKey !== undefined
      ? (PLAYGROUND_FEATURE_PLAN[featureKey] ?? undefined)
      : undefined;
  return useMemo(
    () => ({
      restricted,
      plan,
      title: t("restricted.title"),
      description: markdown(
        t("restricted.description", { salesUrl: CONTACT_SALES_URL })
      ),
      tooltip: t("restricted.tooltip"),
    }),
    [restricted, plan, t]
  );
}
