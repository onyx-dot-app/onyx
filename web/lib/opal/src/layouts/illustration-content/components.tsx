import type { IconFunctionComponent, RichStr } from "@opal/types";
import { Text, type TextFont } from "@opal/components";
import { cn } from "@opal/utils";

// Line weights scale with the drawn size, so each size hands its pixel size to the illustration.
const ILLUSTRATION_PX = { sm: 64, md: 120, lg: 120 } as const satisfies Record<
  NonNullable<IllustrationContentProps["size"]>,
  number
>;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface IllustrationContentProps {
  /** `sm` for a narrow panel (4rem art, muted title), `md` for compact placeholders, `lg` for spacious content panels. */
  size?: "sm" | "md" | "lg";

  /** Optional illustration rendered at 7.5rem × 7.5rem (120px), 4rem (64px) at `sm`, centered. */
  illustration?: IconFunctionComponent;

  /** Main title text, center-aligned. Uses `font-main-content-emphasis`, `font-main-ui-muted` at `sm`. */
  title: string | RichStr;

  /** Optional description below the title, center-aligned. Uses `font-secondary-body`. */
  description?: string | RichStr;
}

// ---------------------------------------------------------------------------
// IllustrationContent
// ---------------------------------------------------------------------------

function titleFont(size: "sm" | "md" | "lg"): TextFont {
  if (size === "lg") return "heading-section";
  return size === "sm" ? "main-ui-muted" : "main-content-emphasis";
}

/**
 * A vertically-stacked, center-aligned layout for empty states, error pages,
 * and informational placeholders.
 *
 * Renders an optional illustration on top, followed by a title and an optional
 * description — all center-aligned with consistent spacing.
 *
 * **Layout structure:**
 *
 * ```
 * ┌─────────────────────────────────┐
 * │          (1.25rem pad)          │
 * │     ┌───────────────────┐       │
 * │     │   illustration    │       │
 * │     │   7.5rem × 7.5rem │       │
 * │     └───────────────────┘       │
 * │         (0.75rem gap)           │
 * │          title (center)         │
 * │      description (center)       │
 * │          (1.25rem pad)          │
 * └─────────────────────────────────┘
 * ```
 *
 * @example
 * ```tsx
 * import { IllustrationContent } from "@opal/layouts";
 * import SvgNoResult from "@opal/illustrations/no-result";
 *
 * <IllustrationContent
 *   illustration={SvgNoResult}
 *   title="No results found"
 *   description="Try adjusting your search or filters."
 * />
 * ```
 */
function IllustrationContent({
  illustration: Illustration,
  title,
  description,
  size = "md",
}: IllustrationContentProps) {
  const small = size === "sm";
  return (
    <div className="flex flex-col items-center gap-3 p-5 text-center">
      {Illustration && (
        <Illustration
          aria-hidden="true"
          size={ILLUSTRATION_PX[size]}
          className={cn("shrink-0", small ? "w-16 h-16" : "w-30 h-30")}
        />
      )}
      <div
        className={cn(
          "flex flex-col items-center text-center",
          size === "lg" && "gap-2"
        )}
      >
        <Text
          font={titleFont(size)}
          color={small ? "text-03" : "text-04"}
          as="p"
        >
          {title}
        </Text>
        {description && (
          <Text
            font={size === "lg" ? "main-content-body" : "secondary-body"}
            color="text-03"
            as="p"
          >
            {description}
          </Text>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { IllustrationContent, type IllustrationContentProps };
