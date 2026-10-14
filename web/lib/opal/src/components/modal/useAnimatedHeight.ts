"use client";

import React from "react";

/** Measure natural content without coupling animation frames to React renders. */
export default function useAnimatedHeight(
  contentRef: React.RefObject<HTMLDivElement | null>,
  enabled: boolean
) {
  React.useLayoutEffect(() => {
    const section = contentRef.current;
    const body = section?.parentElement;
    if (!enabled || !section || !body) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let previousHeight: number | null = null;
    let settleFrame: number | undefined;
    const restoreScrolling = () => body.removeAttribute("data-resizing");
    const restoreIfSettled = () => {
      const transitioning = body
        .getAnimations()
        .some(
          (animation) =>
            "transitionProperty" in animation &&
            animation.transitionProperty === "flex-basis" &&
            (animation.playState === "running" || animation.pending)
        );
      if (!transitioning) restoreScrolling();
    };
    const checkAfterLayout = () => {
      if (settleFrame !== undefined) cancelAnimationFrame(settleFrame);
      settleFrame = requestAnimationFrame(restoreIfSettled);
    };
    const measure = () => {
      const nextHeight = section.getBoundingClientRect().height;
      if (nextHeight === previousHeight) return;
      if (
        previousHeight !== null &&
        Math.abs(nextHeight - previousHeight) > 0.5 &&
        !reducedMotion.matches
      ) {
        // ResizeObserver runs before paint; do not defer overflow changes to React.
        body.setAttribute("data-resizing", "true");
      }
      previousHeight = nextHeight;
      body.style.flexBasis = `${nextHeight}px`;
      if (reducedMotion.matches) restoreScrolling();
      else if (body.hasAttribute("data-resizing")) checkAfterLayout();
    };
    const handleTransitionEnd = (event: TransitionEvent) => {
      if (event.target === body && event.propertyName === "flex-basis") {
        checkAfterLayout();
      }
    };
    const handleMotionChange = () => {
      if (reducedMotion.matches) restoreScrolling();
    };
    body.addEventListener("transitionend", handleTransitionEnd);
    body.addEventListener("transitioncancel", handleTransitionEnd);
    reducedMotion.addEventListener("change", handleMotionChange);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(section, { box: "border-box" });
    // Tab swaps mutate before ResizeObserver runs; suppress overflow in that same turn.
    const mutations = new MutationObserver(measure);
    mutations.observe(section, {
      attributes: true,
      attributeFilter: ["class", "style", "hidden", "open"],
      childList: true,
      characterData: true,
      subtree: true,
    });
    return () => {
      observer.disconnect();
      mutations.disconnect();
      body.removeEventListener("transitionend", handleTransitionEnd);
      body.removeEventListener("transitioncancel", handleTransitionEnd);
      if (settleFrame !== undefined) cancelAnimationFrame(settleFrame);
      reducedMotion.removeEventListener("change", handleMotionChange);
      restoreScrolling();
      body.style.flexBasis = "";
    };
  }, [contentRef, enabled]);
}
