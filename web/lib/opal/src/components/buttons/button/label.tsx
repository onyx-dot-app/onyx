"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Text, type TextFont } from "@opal/components/text/components";
import type { RichStr } from "@opal/types";
import { cn } from "@opal/utils";

interface ButtonLabelProps {
  children: string | RichStr;
  font: TextFont;
  /** Hide the label below the `md` breakpoint. */
  responsiveHide: boolean;
}

/** idle → out → resize → in → idle */
type LabelPhase = "idle" | "out" | "resize" | "in";

const STEP_MS = 150;
// Each step waits for `transitionend`; this is the fallback if it never fires.
const FALLBACK_MS = STEP_MS + 100;

function textOf(label: string | RichStr): string {
  return typeof label === "string" ? label : label.raw;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

/**
 * The button's label. When its text changes, the old text fades out, the
 * width adjusts to the new text, then the new text fades in. Labels that never
 * change cost nothing: no observer, no measuring.
 */
function ButtonLabel({ children, font, responsiveHide }: ButtonLabelProps) {
  const ref = useRef<HTMLSpanElement>(null);
  // The label on screen: the old text until it has faded out.
  const [shown, setShown] = useState(children);
  const [phase, setPhase] = useState<LabelPhase>("idle");
  // The old text's width, where the resize starts.
  const [fromWidth, setFromWidth] = useState(0);
  // The newest label, for steps that finish after a later render.
  const latestRef = useRef(children);
  useLayoutEffect(() => {
    latestRef.current = children;
  });

  const changed = textOf(children) !== textOf(shown);
  if (changed && (phase === "idle" || phase === "in")) {
    // The DOM still shows the old text. No layout (hidden, or tests) or
    // reduced motion changes the text at once.
    const width = ref.current?.getBoundingClientRect().width ?? 0;
    if (width > 0 && !prefersReducedMotion()) {
      setFromWidth(width);
      setPhase("out");
    } else {
      setShown(children);
    }
  } else if (changed && phase === "resize") {
    // A newer label mid-resize: resize to it instead.
    setShown(children);
  }

  // Resize: hold the old width, then transition to the new text's width.
  useLayoutEffect(() => {
    const label = ref.current;
    if (phase !== "resize" || !label) return;
    label.style.width = "";
    const toWidth = label.getBoundingClientRect().width;
    if (toWidth === fromWidth) {
      setPhase("in");
      return;
    }
    label.style.width = `${fromWidth}px`;
    // The read commits the start width before the transition is set.
    label.getBoundingClientRect();
    label.style.transition = `width ${STEP_MS}ms ease-out`;
    label.style.width = `${toWidth}px`;
    return () => {
      label.style.transition = "";
      label.style.width = "";
    };
  }, [phase, shown, fromWidth]);

  function advance(from: LabelPhase) {
    if (from === "out") {
      setShown(latestRef.current);
      setPhase("resize");
    } else if (from === "resize") {
      setPhase("in");
    } else if (from === "in") {
      setPhase("idle");
    }
  }

  // No step stalls when `transitionend` does not arrive.
  const advanceRef = useRef(advance);
  useLayoutEffect(() => {
    advanceRef.current = advance;
  });
  useEffect(() => {
    if (phase === "idle") return;
    const fallback = window.setTimeout(
      () => advanceRef.current(phase),
      FALLBACK_MS
    );
    return () => window.clearTimeout(fallback);
  }, [phase]);

  return (
    <span
      ref={ref}
      className={cn(
        "overflow-x-clip whitespace-nowrap transition-opacity duration-150 ease-out motion-reduce:transition-none",
        responsiveHide ? "hidden md:inline-block" : "inline-block",
        (phase === "out" || phase === "resize") && "opacity-0"
      )}
      onTransitionEnd={(event) => {
        if (event.target !== event.currentTarget) return;
        const step =
          event.propertyName === "opacity"
            ? phase === "out" || phase === "in"
            : event.propertyName === "width" && phase === "resize";
        if (step) advance(phase);
      }}
    >
      <Text font={font} color="inherit" wordWrap="whitespace-nowrap">
        {shown}
      </Text>
    </span>
  );
}

export { ButtonLabel, type ButtonLabelProps };
