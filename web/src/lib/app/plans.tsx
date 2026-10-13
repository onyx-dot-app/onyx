"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import { Tag, type TagProps } from "@opal/components";
import { SvgOrganization, SvgUsers } from "@opal/icons";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { markdown } from "@opal/utils";

/** The plans a feature can be limited to, lowest first. */
export type Plan = "free" | "business" | "enterprise";

type PlanColor = NonNullable<TagProps["color"]>;

const PLAN_STYLES: Record<
  Plan,
  { color: PlanColor; icon: IconFunctionComponent | undefined }
> = {
  free: { color: "gray", icon: undefined },
  business: { color: "green", icon: SvgUsers },
  enterprise: { color: "amber", icon: SvgOrganization },
};

/** Everything that marks a feature as limited to a plan. */
export interface PlanMetadata {
  title: string;
  icon: IconFunctionComponent | undefined;
  color: PlanColor;
  /** For a `tag` slot, such as `Content`'s or an option's. */
  tag: TagProps;
  /** Why the feature is off below this plan, linking to billing. */
  tooltip: RichStr;
}

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

export interface PlanTagProps {
  plan: Plan;
  size?: TagProps["size"];
}

/** A plan's badge. */
export function PlanTag({ plan, size }: PlanTagProps) {
  const { tag } = usePlans()[plan];
  return <Tag {...tag} size={size} />;
}
