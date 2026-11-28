import type { IconFunctionComponent, IconProps } from "@opal/types";
import { cn } from "@opal/utils";

export const ICON_TINTS = [
  "blue",
  "green",
  "purple",
  "amber",
  "cyan",
  "magenta",
  "orange",
  "sky",
] as const;

export type IconTint = (typeof ICON_TINTS)[number];

/** Theme strokes, half mixed with the neutral icon colour so they stay quiet.
 * The `!` wins over an interactive row's icon colour. */
const TINT_CLASSES: Record<IconTint, string> = {
  blue: "stroke-[color-mix(in_srgb,var(--theme-blue-05)_45%,var(--text-03))]!",
  green:
    "stroke-[color-mix(in_srgb,var(--theme-green-05)_45%,var(--text-03))]!",
  purple:
    "stroke-[color-mix(in_srgb,var(--theme-purple-05)_45%,var(--text-03))]!",
  amber:
    "stroke-[color-mix(in_srgb,var(--theme-amber-05)_45%,var(--text-03))]!",
  cyan: "stroke-[color-mix(in_srgb,var(--theme-cyan-05)_45%,var(--text-03))]!",
  magenta:
    "stroke-[color-mix(in_srgb,var(--theme-magenta-05)_45%,var(--text-03))]!",
  orange:
    "stroke-[color-mix(in_srgb,var(--theme-orange-05)_45%,var(--text-03))]!",
  sky: "stroke-[color-mix(in_srgb,var(--theme-sky-05)_45%,var(--text-03))]!",
};

const cache = new Map<
  IconFunctionComponent,
  Map<IconTint, IconFunctionComponent>
>();

/** `Icon` drawn in a quiet theme colour. The same icon and tint give the same
 * component, so React keeps it mounted across renders. */
export function tintedIcon(
  Icon: IconFunctionComponent,
  tint: IconTint
): IconFunctionComponent {
  const byTint = cache.get(Icon) ?? new Map<IconTint, IconFunctionComponent>();
  cache.set(Icon, byTint);
  const cached = byTint.get(tint);
  if (cached) return cached;
  function TintedIcon({ className, ...props }: IconProps) {
    return <Icon {...props} className={cn(className, TINT_CLASSES[tint])} />;
  }
  byTint.set(tint, TintedIcon);
  return TintedIcon;
}
