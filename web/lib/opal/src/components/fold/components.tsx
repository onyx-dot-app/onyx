"use client";

import "@opal/components/fold/styles.css";
import { useEffect, useState } from "react";

/** Matches the transition in `styles.css`. */
const FOLD_DURATION_MS = 200;

interface FoldProps {
  /** Whether the fold is open. */
  open: boolean;
  children?: React.ReactNode;
}

/**
 * Content that opens and closes by animating its height, with a fade. A grid
 * row moves between `0fr` and `1fr`, so the fold animates on a pure CSS clock:
 * no measured height, no state machine. It paints nothing of its own, so the
 * content stays part of whatever surrounds it.
 *
 * A closed fold takes no space and holds nothing: children stay through the
 * closing animation, so it has something to collapse, then drop. While closed
 * or closing it is inert and hidden from assistive tech.
 */
function Fold({ open, children }: FoldProps) {
  // True from the moment the fold opens until its closing animation ends,
  // the window where the children must stay mounted though `open` is false.
  const [closing, setClosing] = useState(false);
  const mounted = open || closing;

  useEffect(() => {
    if (open) {
      setClosing(true);
      return;
    }
    const timeout = setTimeout(() => setClosing(false), FOLD_DURATION_MS);
    return () => clearTimeout(timeout);
  }, [open]);

  return (
    <div
      className="opal-fold"
      data-open={open ? "true" : "false"}
      aria-hidden={!open || undefined}
      inert={!open || undefined}
    >
      <div className="opal-fold-inner">{mounted ? children : null}</div>
    </div>
  );
}

export { Fold, type FoldProps };
