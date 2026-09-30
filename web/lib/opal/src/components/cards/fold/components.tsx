import "@opal/components/cards/shared.css";
import "@opal/components/cards/fold/styles.css";
import { useEffect, useState } from "react";
import type { BorderVariants, StatusVariants } from "@opal/types";

/** Matches the fold transition in `styles.css`. */
const FOLD_DURATION_MS = 200;

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

 *
 * The fold carries the border and the bottom rounding that join it to the
 * header above it. It never paints a background, so the page shows through
 * and the two regions stay visually distinct.
 *
 * A closed fold holds nothing. Children linger through the closing
 * animation, so it has something to collapse, and are dropped once it
 * finishes. Anything else leaves a hidden copy of the content on the page:
 * still fetching, still matching a query by test id or by field name, and
 * still counted by anything that walks the DOM rather than the
 * accessibility tree.
 */
function CardFold({
  expanded,
  border,
  radius,
  borderColor,
  contentHeight = 80,
  children,
}: CardFoldProps) {
  // True from the moment the fold opens until its closing animation ends,
  // which is the window where the children must stay mounted even though
  // `expanded` has already gone false.
  const [closing, setClosing] = useState(false);
  const mounted = expanded || closing;

  useEffect(() => {
    if (expanded) {
      setClosing(true);
      return;
    }
    const timeout = setTimeout(() => setClosing(false), FOLD_DURATION_MS);
    return () => clearTimeout(timeout);
  }, [expanded]);

  return (
    <div
      className="opal-card-fold"
      data-expanded={expanded ? "true" : "false"}
      // The fold itself stays, so the grid row has something to animate.
      // While it closes it must not be reachable either.
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
          {mounted ? children : null}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Exports
// ---------------------------------------------------------------------------

export { CardFold, type CardFoldProps, type CardFoldHeight };
