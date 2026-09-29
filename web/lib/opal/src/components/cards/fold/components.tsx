import "@opal/components/cards/shared.css";
import "@opal/components/cards/fold/styles.css";
import type { BorderVariants, StatusVariants } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * How tall the fold's body may grow, on Tailwind's spacing scale: `N` is
 * `N / 4` rem, so `80` is `20rem`. `"full"` sets no cap at all.
 */
type CardFoldHeight = 80 | "full";

interface CardFoldProps {
  /** Whether the fold is open. Visual only; the host card owns the state. */
  expanded: boolean;

  /** Border style, matched to the header the fold sits under. */
  border: BorderVariants;

  /** Bottom corner radius in rem, matched to the header's. */
  radius: string;

  /** Status border colour, for hosts that have one. */
  borderColor?: StatusVariants;

  /**
   * Max-height constraint on the body.
   * - `80`: caps at 20rem with vertical scroll.
   * - `"full"`: no cap; the body takes its natural height.
   *
   * @default 80
   */
  contentHeight?: CardFoldHeight;

  children?: React.ReactNode;
}

// ---------------------------------------------------------------------------
// CardFold
// ---------------------------------------------------------------------------

/**
 * The animating body of an expandable card, shared by `Card` and
 * `SelectCard`.
 *
 * A grid row moves between `0fr` and `1fr` with an opacity fade, so the fold
 * opens and closes on a pure CSS clock: no measured height, no state machine,
 * and the children are never unmounted.
 *
 * The fold carries the border and the bottom rounding that join it to the
 * header above it. It never paints a background, so the page shows through
 * and the two regions stay visually distinct.
 *
 * Closed, it is inert and hidden from assistive tech, so a form inside it
 * cannot be tabbed into while it is out of sight.
 */
function CardFold({
  expanded,
  border,
  radius,
  borderColor,
  contentHeight = 80,
  children,
}: CardFoldProps) {
  return (
    <div
      className="opal-card-fold"
      data-expanded={expanded ? "true" : "false"}
      // A closed fold is zero-height but still in the DOM, so without these
      // its children stay tabbable and readable to assistive tech.
      aria-hidden={!expanded || undefined}
      inert={!expanded || undefined}
    >
      <div className="opal-card-fold-inner">
        <div
          className="opal-card-fold-body"
          style={{
            borderBottomLeftRadius: radius,
            borderBottomRightRadius: radius,
          }}
          data-border={border}
          data-opal-status-border={borderColor}
          data-content-height={contentHeight}
        >
          {children}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { CardFold, type CardFoldProps, type CardFoldHeight };
