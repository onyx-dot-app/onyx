"use client";

import { Tag, type TagProps } from "@opal/components";
import { usePlans } from "@/lib/tiers/hooks";
import type { Plan } from "@/lib/tiers/types";

export interface PlanTagProps {
  plan: Plan;
  size?: TagProps["size"];
}

/** A plan's badge. */
export function PlanTag({ plan, size }: PlanTagProps) {
  const { tag } = usePlans()[plan];
  return <Tag {...tag} size={size} />;
}
