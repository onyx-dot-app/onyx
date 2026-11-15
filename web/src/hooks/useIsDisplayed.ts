"use client";

import { useEffect, useState } from "react";

/**
 * Whether an element is laid out, false while its own `display` is `none`, such as a panel a container query hides.
 * Pass the returned callback as the element's ref. Shown until measured.
 */
export default function useIsDisplayed<T extends HTMLElement>(): [
  (node: T | null) => void,
  boolean,
] {
  const [node, setNode] = useState<T | null>(null);
  const [displayed, setDisplayed] = useState(true);
  useEffect(() => {
    if (node === null) return;
    const measure = () =>
      setDisplayed(getComputedStyle(node).display !== "none");
    measure();
    // Turning `display: none` on or off resizes the box, so a query flipping it is caught here.
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [node]);
  return [setNode, displayed];
}
