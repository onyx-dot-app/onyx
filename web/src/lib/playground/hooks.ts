"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { markdown } from "@opal/utils";
import type { RichStr } from "@opal/types";
import { CONTACT_SALES_URL } from "@/lib/constants";
import {
  PLAYGROUND_FEATURE_REASON,
  PlaygroundRestrictionReason,
  type PlaygroundRestrictedFeature,
} from "@/lib/playground/types";
import { useSettings } from "@/lib/settings/hooks";

/** The features the playground restricts. Empty off the playground. */
export function usePlaygroundRestrictions(): ReadonlySet<PlaygroundRestrictedFeature> {
  const { playground_restrictions } = useSettings();
  return useMemo(
    () => new Set(playground_restrictions ?? []),
    [playground_restrictions]
  );
}

export interface PlaygroundRestriction {
  /** True while the settings load: whether the feature is restricted is not known yet. */
  loading: boolean;
  /** True when the feature is restricted on this deployment. */
  restricted: boolean;
  /** Why, which picks the description. Absent for a surface without a feature key. */
  reason: PlaygroundRestrictionReason | undefined;
  title: string;
  description: RichStr;
  tooltip: string;
}

/**
 * Whether `featureKey` is restricted here, with the copy every restricted
 * surface shows: a short title, the one-line reason for that feature with the
 * sales link, and a tooltip for a disabled control.
 *
 *   const { restricted, description } = usePlaygroundRestriction(PlaygroundRestrictedFeature.SSO);
 *
 * Pass `undefined` for a surface without a feature key: it is never restricted.
 */
export function usePlaygroundRestriction(
  featureKey: PlaygroundRestrictedFeature | undefined
): PlaygroundRestriction {
  const t = useTranslations("common.playground");
  const restrictions = usePlaygroundRestrictions();
  const { isLoading: loading } = useSettings();
  const restricted = featureKey !== undefined && restrictions.has(featureKey);
  const reason =
    featureKey !== undefined
      ? PLAYGROUND_FEATURE_REASON[featureKey]
      : undefined;
  return useMemo(() => {
    const args = { salesUrl: CONTACT_SALES_URL };
    // Literal keys, so the message ids stay statically checkable.
    const description =
      reason === PlaygroundRestrictionReason.OWN_KEYS
        ? t("restricted.ownKeys.description", args)
        : reason === PlaygroundRestrictionReason.SWITCHED_OFF
          ? t("restricted.switchedOff.description", args)
          : t("restricted.enterprise.description", args);
    return {
      loading,
      restricted,
      reason,
      title: t("restricted.title"),
      description: markdown(description),
      tooltip: t("restricted.tooltip"),
    };
  }, [loading, restricted, reason, t]);
}
