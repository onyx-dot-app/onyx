"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";

/**
 * Tracks the on-screen box of the main content container so a fixed-position
 * banner can align to it (rather than the full viewport) as the sidebar opens
 * and closes. Falls back to the full window width when no
 * `[data-main-container]` element is present.
 */
export function useMainContainerOffset(): { left: number; width: number } {
  const pathname = usePathname();
  const [bounds, setBounds] = useState<{ left: number; width: number }>({
    left: 0,
    width: 0,
  });

  useEffect(() => {
    if (typeof window === "undefined") return;
    let target: HTMLElement | null = null;
    let frame = 0;

    function update() {
      const el = document.querySelector<HTMLElement>("[data-main-container]");
      if (el) {
        const rect = el.getBoundingClientRect();
        setBounds({ left: rect.left, width: rect.width });
        if (target !== el) {
          ro.disconnect();
          ro.observe(el);
          target = el;
        }
      } else {
        setBounds({ left: 0, width: window.innerWidth });
        target = null;
      }
    }

    const ro = new ResizeObserver(update);
    const mo = new MutationObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(update);
    });

    update();
    mo.observe(document.body, { childList: true, subtree: true });
    window.addEventListener("resize", update);

    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
      mo.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [pathname]);

  return bounds;
}
