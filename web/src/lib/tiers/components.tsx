"use client";

import {
  LifecycleBadge,
  PlanBadge,
  type PlanBadgeProps,
} from "@/lib/badges/components";

export type PlanTagProps = PlanBadgeProps;

/** A plan's badge. */
export function PlanTag(props: PlanTagProps) {
  return <PlanBadge {...props} />;
}

/** The badge every beta feature carries. */
export function BetaTag() {
  return <LifecycleBadge lifecycle="beta" />;
}
