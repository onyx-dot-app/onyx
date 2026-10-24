"use client";

import { Tag, type TagProps } from "@opal/components";
import { useBetaTag, usePlans } from "@/lib/tiers/hooks";
import type { Tier } from "@/lib/tiers/types";

export interface PlanTagProps {
  plan: Tier;
  size?: TagProps["size"];
}

/** A plan's badge. */
export function PlanTag({ plan, size }: PlanTagProps) {
  const { tag } = usePlans()[plan];
  return <Tag {...tag} size={size} />;
}

export interface BetaTagProps {
  size?: TagProps["size"];
}

/** The badge every beta feature carries. */
export function BetaTag({ size }: BetaTagProps) {
  return <Tag {...useBetaTag()} size={size} />;
}
