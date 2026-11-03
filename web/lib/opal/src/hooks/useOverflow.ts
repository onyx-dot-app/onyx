"use client";

import { useLayoutEffect, useState } from "react";

function overflows(element: HTMLElement): boolean {
  return (
    element.scrollWidth > element.clientWidth ||
    element.scrollHeight > element.clientHeight
  );
}

/**
 * Whether `element`'s content overflows its box, as with a title clamped to
 * one line with an ellipsis. Re-measures whenever the element resizes, when
 * its content changes, and when a webfont finishes loading: new text or a late
 * font can widen the content without resizing the clamped box.
 *
 * Takes the element rather than a ref so the caller can hand over one it
 * found after mount (e.g. by querying inside a component it does not own);
 * `null` reads as not overflowing.
 */
export default function useOverflow(element: HTMLElement | null): boolean {
  const [isOverflowing, setIsOverflowing] = useState(false);

  useLayoutEffect(() => {
    if (!element) {
      setIsOverflowing(false);
      return;
    }
    const measure = () => setIsOverflowing(overflows(element));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    const mutations = new MutationObserver(measure);
    mutations.observe(element, {
      childList: true,
      characterData: true,
      subtree: true,
    });
    // Absent without the Font Loading API (e.g. jsdom in tests); the
    // resize observer still measures.
    const fonts: FontFaceSet | undefined = document.fonts;
    fonts?.addEventListener("loadingdone", measure);
    return () => {
      observer.disconnect();
      mutations.disconnect();
      fonts?.removeEventListener("loadingdone", measure);
    };
  }, [element]);

  return isOverflowing;
}
