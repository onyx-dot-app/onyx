import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import type { TagProps } from "@opal/components";
import { SvgOrganization, SvgUsers } from "@opal/icons";
import type { IconFunctionComponent, RichStr } from "@opal/types";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/**
 * Wraps strings for inline markdown parsing by `Text` and other Opal components.
 *
 * Multiple arguments are joined with newlines, so each string renders on its own line:
 * ```tsx
 * markdown("Line one", "Line two", "Line three")
 * ```
 */
export function markdown(...lines: string[]): RichStr {
  return { __brand: "RichStr", raw: lines.join("\n") };
}

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
