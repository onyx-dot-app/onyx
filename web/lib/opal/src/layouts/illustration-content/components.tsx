import type { IconFunctionComponent, RichStr } from "@opal/types";
import { resolveStr } from "@opal/components/text/InlineMarkdown";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface IllustrationContentProps {
  /** Optional illustration rendered at 7.5rem × 7.5rem (120px), centered. */
  illustration?: IconFunctionComponent;

  /** Main title text, center-aligned. Uses `font-main-content-emphasis`. */
  title: string | RichStr;

  /** Optional description below the title, center-aligned. Uses `font-secondary-body`. */
  description?: string | RichStr;
}

// ---------------------------------------------------------------------------
// IllustrationContent
// ---------------------------------------------------------------------------

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
}: IllustrationContentProps) {
  return (
    <div className="flex flex-col items-center gap-3 p-5 text-center">
      {Illustration && (
        <Illustration
          aria-hidden="true"
          className="shrink-0 w-[7.5rem] h-[7.5rem]"
        />
      )}
      <div className="flex flex-col items-center text-center">
        <p className="font-main-content-emphasis text-text-04">
          {resolveStr(title)}
        </p>
        {description && (
          <p className="font-secondary-body text-text-03">
            {resolveStr(description)}
          </p>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { IllustrationContent, type IllustrationContentProps };
