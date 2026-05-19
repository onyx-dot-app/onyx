import type { TagProps } from "@opal/components";
import { SvgOrganization, SvgUsers } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";

export type Plan = "business" | "enterprise";

export const PLAN_CONFIG: Record<
  Plan,
  { color: "blue" | "amber"; icon: IconFunctionComponent; title: string }
> = {
  business: { color: "blue", icon: SvgUsers, title: "Business Plan" },
  enterprise: {
    color: "amber",
    icon: SvgOrganization,
    title: "Enterprise Plan",
  },
};

/**
 * Returns the `TagProps` that render a subscription-tier badge. Pair with
 * any `Tag`-accepting slot (e.g. `Content.tag`, `ContentMd.tag`). To use a
 * non-default size, spread and override: `{ ...planTagProps("enterprise"), size: "sm" }`.
 */
export function planTagProps(plan: Plan): TagProps {
  const { color, icon, title } = PLAN_CONFIG[plan];
  return { color, icon, title };
}
