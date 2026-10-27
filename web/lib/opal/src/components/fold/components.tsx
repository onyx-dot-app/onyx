"use client";

import "@opal/components/fold/styles.css";
import { useEffect, useState } from "react";

/** The whole close in `styles.css`: the fade, then the collapse. */
const FOLD_CLOSE_MS: number = 250;

type FoldProps = {
  /** Whether the fold is open. */
  open: boolean;
  /**
   * Keep the children while closed, e.g. so form fields inside keep their
   * state. Off, a closed fold drops them once it finishes closing.
   */
  keepMounted?: boolean;
  /** The fold's id, for a control that points at it with `aria-controls`. */
  id?: string;
  /**
   * Wraps the fold in a frame, such as a bordered box. The frame's height
   * follows the animation, so its edges move with it, and it stays visible;
   * only the content inside fades. A fully closed fold's frame has no height,
   * and should show no edge then (see `data-visible` on the root).
   */
  frame?: (content: React.ReactNode) => React.ReactNode;
  children?: React.ReactNode;
};

/**
 * Content that opens and closes by animating its height, with a fade. A grid
 * row moves between `0fr` and `1fr`, so the fold animates on a pure CSS clock:
 * no measured height, no state machine. It paints nothing of its own, so the
 * content stays part of whatever surrounds it.
 *
 * A closed fold takes no space. Its children stay through the closing
 * animation, so it has something to collapse, then drop, unless
 * `keepMounted`. While closed or closing it is inert and hidden from
 * assistive tech.
 */
function Fold({ open, keepMounted = false, id, frame, children }: FoldProps) {
  // True from the moment the fold opens until its closing animation ends,
  // the window where the children must stay mounted though `open` is false.
  const [closing, setClosing] = useState<boolean>(false);
  const mounted: boolean = keepMounted || open || closing;

  useEffect(() => {
    if (open) {
      setClosing(true);
      return;
    }
    const timeout: ReturnType<typeof setTimeout> = setTimeout(
      () => setClosing(false),
      FOLD_CLOSE_MS
    );
    return () => clearTimeout(timeout);
  }, [open]);

  // Whether the content shows. A transition runs only on an element that
  // already exists, so opening mounts the content hidden and shows it a frame
  // later, which lets it fade in after the height. Open from the start, it
  // shows at once, with no fade on page load.
  const [shown, setShown] = useState<boolean>(open);
  useEffect(() => {
    if (!open) {
      setShown(false);
      return;
    }
    let second: number = 0;
    const first: number = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => setShown(true));
    });
    return () => {
      cancelAnimationFrame(first);
      cancelAnimationFrame(second);
    };
  }, [open]);

  // The fade is on the content alone, so a frame around it stays visible.
  const content = (
    <div
      className="opal-fold-content"
      data-open={open && shown ? "true" : "false"}
    >
      {children}
    </div>
  );

  // The grid animates the height. A frame wraps the grid rather than sitting
  // inside its clip, so the frame's own height follows the animation and its
  // bottom edge, border and all, rides the moving edge.
  const grid = (
    <div className="opal-fold-grid" data-open={open ? "true" : "false"}>
      <div className="opal-fold-inner">{mounted ? content : null}</div>
    </div>
  );

  return (
    <div
      id={id}
      className="opal-fold"
      data-open={open ? "true" : "false"}
      // Fully closed: nothing inside, unless `keepMounted`.
      data-mounted={mounted ? "true" : "false"}
      // Open or closing: the fold has height. Unlike `data-mounted`, false
      // once closed even when `keepMounted` keeps the children.
      data-visible={open || closing ? "true" : "false"}
      aria-hidden={!open || undefined}
      inert={!open || undefined}
    >
      {frame ? frame(grid) : grid}
    </div>
  );
}

export { Fold, type FoldProps };
