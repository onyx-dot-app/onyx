"use client";

import { useEffect, useState } from "react";

/** Whether a drag carries files (not text or a link dragged in the page). */
function carriesFiles(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes("Files");
}

/**
 * True while files are dragged anywhere over the window, so a drop target can
 * show itself before the pointer reaches it. Ends on a drop, a cancelled drag
 * or the pointer leaving the window.
 *
 *   const filesDragged = useWindowFileDrag(!disabled);
 */
export default function useWindowFileDrag(enabled: boolean = true): boolean {
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    if (!enabled) {
      setDragging(false);
      return;
    }
    // dragenter and dragleave fire for every element crossed, so a count of
    // the open enters says whether the drag is still inside the window.
    let depth = 0;
    const onEnter = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      depth += 1;
      setDragging(true);
    };
    const onLeave = (event: DragEvent) => {
      if (!carriesFiles(event)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setDragging(false);
    };
    const onEnd = () => {
      depth = 0;
      setDragging(false);
    };
    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragleave", onLeave);
    window.addEventListener("drop", onEnd);
    window.addEventListener("dragend", onEnd);
    return () => {
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragleave", onLeave);
      window.removeEventListener("drop", onEnd);
      window.removeEventListener("dragend", onEnd);
    };
  }, [enabled]);

  return dragging;
}
