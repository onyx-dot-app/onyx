"use client";

import { useEffect } from "react";

/**
 * Development-only stats.js overlay showing FPS, MS, and memory usage.
 * Enable by running `npm run dev:profile` or setting NEXT_PUBLIC_ENABLE_STATS=true.
 * Shows FPS and MB panels (memory is Chrome only).
 *
 * Uses dynamic import to prevent stats.js from being bundled in production.
 */
export default function StatsOverlay() {
  useEffect(() => {
    let animationFrameId: number;
    let container: HTMLDivElement | null = null;
    let isMounted = true;

    // Dynamic import to avoid bundling in production
    import("stats.js").then((StatsModule) => {
      // Guard against unmount during async import
      if (!isMounted) return;

      const Stats = StatsModule.default;

      // Create Stats instances for FPS and MB
      const panels = [0, 2].map((panel) => {
        const stats = new Stats();
        stats.showPanel(panel);
        return stats;
      });

      // Create container for all panels
      container = document.createElement("div");
      container.style.position = "fixed";
      container.style.top = "0";
      container.style.left = "50%";
      container.style.transform = "translateX(-50%)";
      container.style.zIndex = "99999";
      container.style.display = "flex";

      panels.forEach((stats) => {
        stats.dom.style.position = "relative";
        container!.appendChild(stats.dom);
      });

      document.body.appendChild(container);

      const animate = () => {
        panels.forEach((stats) => {
          stats.begin();
          stats.end();
        });
        animationFrameId = requestAnimationFrame(animate);
      };

      animationFrameId = requestAnimationFrame(animate);
    });

    return () => {
      isMounted = false;
      cancelAnimationFrame(animationFrameId);
      if (container?.parentNode) {
        container.parentNode.removeChild(container);
      }
    };
  }, []);

  return null;
}
