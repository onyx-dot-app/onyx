import type { TagColor } from "@opal/components";
import {
  SvgArrowLeftDot,
  SvgArrowRightDot,
  SvgCornerRightUpDot,
  SvgMinusCircle,
} from "@opal/icons";
import type { IconFunctionComponent, IconProps } from "@opal/types";

export type OpenApiMethodColor = Extract<
  TagColor,
  "green" | "blue" | "amber" | "red"
>;

/** The CSS color of each method color, matching its `Tag` text. */
const METHOD_CSS_COLORS: Record<OpenApiMethodColor, string> = {
  green: "var(--theme-green-05)",
  blue: "var(--theme-blue-05)",
  amber: "var(--theme-amber-05)",
  red: "var(--status-error-05)",
};

/**
 * An HTTP method's color: green for GET, blue for POST, red for DELETE, and
 * amber for the rest (PUT, PATCH, and rarer methods such as HEAD).
 */
export function openApiMethodColor(method: string): OpenApiMethodColor {
  const verb = method.toUpperCase();
  if (verb === "GET") return "green";
  if (verb === "POST") return "blue";
  if (verb === "DELETE") return "red";
  return "amber";
}

/**
 * An HTTP method's icon: in for GET, out for POST, minus for DELETE, and up
 * for the rest (PUT, PATCH, and rarer methods such as HEAD).
 */
export function openApiMethodIcon(method: string): IconFunctionComponent {
  const verb = method.toUpperCase();
  if (verb === "GET") return SvgArrowLeftDot;
  if (verb === "POST") return SvgArrowRightDot;
  if (verb === "DELETE") return SvgMinusCircle;
  return SvgCornerRightUpDot;
}

const coloredIcons = new Map<string, IconFunctionComponent>();

/**
 * An HTTP method's icon in its method color. Each method gets one stable
 * component, so it can be passed as an `icon` prop without remounting.
 */
export function openApiMethodColoredIcon(
  method: string
): IconFunctionComponent {
  const verb = method.toUpperCase();
  const cached = coloredIcons.get(verb);
  if (cached) return cached;
  const Icon = openApiMethodIcon(verb);
  const color = METHOD_CSS_COLORS[openApiMethodColor(verb)];
  function OpenApiMethodIcon(props: IconProps) {
    // An inline color, because Opal layouts color icons with unlayered CSS.
    return <Icon {...props} style={{ ...props.style, color }} />;
  }
  coloredIcons.set(verb, OpenApiMethodIcon);
  return OpenApiMethodIcon;
}

/** A method's sort group: GET, then POST, then the rest, then DELETE. */
function methodRank(method: string): number {
  const verb = method.toUpperCase();
  if (verb === "GET") return 0;
  if (verb === "POST") return 1;
  if (verb === "DELETE") return 3;
  return 2;
}

/**
 * Groups actions by HTTP method: GET, then POST, then PUT, PATCH and the
 * other methods, then DELETE. Order within a group is kept.
 */
export function sortByOpenApiMethod<T extends { method: string }>(
  actions: readonly T[]
): T[] {
  return [...actions].sort(
    (a, b) => methodRank(a.method) - methodRank(b.method)
  );
}
