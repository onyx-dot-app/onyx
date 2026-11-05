"use client";

import { Badge, type BadgeProps } from "@opal/components";
import { useBetaTag, usePlans } from "@/lib/tiers/hooks";
import type { Tier } from "@/lib/tiers/types";

export interface PlanTagProps {
  plan: Tier;
  size?: BadgeProps["size"];
}

/** A plan's badge. */
export function PlanTag({ plan, size }: PlanTagProps) {
  const { tag } = usePlans()[plan];
  return <Badge {...tag} size={size} />;
}

export interface BetaTagProps {
  size?: BadgeProps["size"];
}

/** The badge every beta feature carries. */
export function BetaTag({ size }: BetaTagProps) {
  return <Badge {...useBetaTag()} size={size} />;
}
