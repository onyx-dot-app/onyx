"use client";

import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";

interface AnimatedMessageBubbleProps {
  content: string;
  startRect: DOMRect;
  targetRect: DOMRect | null;
  onAnimationComplete: () => void;
  targetRef?: React.RefObject<HTMLDivElement | null>;
}

export default function AnimatedMessageBubble({
  content,
  startRect,
  targetRect: initialTargetRect,
  onAnimationComplete,
  targetRef,
}: AnimatedMessageBubbleProps) {
  const bubbleRef = useRef<HTMLDivElement>(null);
  const [liveTargetRect, setLiveTargetRect] = useState<DOMRect | null>(
    initialTargetRect
  );
  const [animationStarted, setAnimationStarted] = useState(false);
  const [animationDurationS, setAnimationDurationS] = useState(0.3);
  const [neutralBg, setNeutralBg] = useState<string>(
    "var(--background-neutral-00)"
  );
  const [tintBg, setTintBg] = useState<string>("var(--background-tint-02)");
  const prevTargetRectRef = useRef<DOMRect | null>(null);

  const handleAnimationComplete = React.useCallback(() => {
    if (targetRef?.current && bubbleRef.current) {
      const finalRect = targetRef.current.getBoundingClientRect();
      const finalDeltaX = finalRect.left - startRect.left;
      const finalDeltaY = finalRect.top - startRect.top;
      bubbleRef.current.style.transform = `translate(${finalDeltaX}px, ${finalDeltaY}px)`;
      bubbleRef.current.style.width = `${finalRect.width}px`;
      bubbleRef.current.style.height = `${finalRect.height}px`;
    }
    onAnimationComplete();
  }, [onAnimationComplete, startRect.left, startRect.top, targetRef]);

  // Read the CSS variable so styling controls duration.
  useLayoutEffect(() => {
    if (!bubbleRef.current) return;
    const raw = getComputedStyle(bubbleRef.current).getPropertyValue(
      "--message-send-duration"
    );
    const parsed = raw.trim().toLowerCase();
    let seconds = parseFloat(parsed);
    if (parsed.endsWith("ms")) seconds = seconds / 1000;
    if (Number.isNaN(seconds) || seconds <= 0) return;
    setAnimationDurationS(seconds);
  }, []);

  // Resolve CSS color variables to concrete values for Framer Motion to tween.
  useLayoutEffect(() => {
    const rootStyles = getComputedStyle(document.documentElement);
    const neutral = rootStyles
      .getPropertyValue("--background-neutral-00")
      .trim();
    const tint = rootStyles.getPropertyValue("--background-tint-02").trim();
    if (neutral) setNeutralBg(neutral);
    if (tint) setTintBg(tint);
  }, []);

  // Continuously track the latest target rect so the animation follows scroll/resize
  useLayoutEffect(() => {
    if (!targetRef?.current) return;

    let frameId: number;
    const updateRect = () => {
      if (!targetRef?.current) return;
      const nextRect = targetRef.current.getBoundingClientRect();
      const prevRect = prevTargetRectRef.current;
      const changed =
        !prevRect ||
        Math.abs(prevRect.left - nextRect.left) > 0.01 ||
        Math.abs(prevRect.top - nextRect.top) > 0.01 ||
        Math.abs(prevRect.width - nextRect.width) > 0.01 ||
        Math.abs(prevRect.height - nextRect.height) > 0.01;

      if (changed) {
        prevTargetRectRef.current = nextRect;
        setLiveTargetRect(nextRect);
      }

      frameId = requestAnimationFrame(updateRect);
    };

    // Set initial rect immediately
    const initialRect = targetRef.current.getBoundingClientRect();
    prevTargetRectRef.current = initialRect;
    setLiveTargetRect(initialRect);
    frameId = requestAnimationFrame(updateRect);

    return () => cancelAnimationFrame(frameId);
  }, [targetRef]);

  useEffect(() => {
    if ((liveTargetRect || initialTargetRect) && !animationStarted) {
      setAnimationStarted(true);
    }
  }, [animationStarted, initialTargetRect, liveTargetRect]);

  const targetRect = liveTargetRect ?? initialTargetRect;
  const targetWidth = targetRect?.width ?? startRect.width;
  const targetHeight = targetRect?.height ?? startRect.height;
  const targetLeft = targetRect?.left ?? startRect.left;
  const targetTop = targetRect?.top ?? startRect.top;

  return (
    <motion.div
      ref={bubbleRef}
      className={cn(
        "fixed pointer-events-none z-[9999] whitespace-break-spaces rounded-t-16 rounded-bl-16 py-2 px-3 text-user-text overflow-hidden animated-message-bubble box-border"
      )}
      style={{
        willChange: "transform, width, height, background-color",
        boxSizing: "border-box",
      }}
      initial={{
        left: startRect.left,
        top: startRect.top,
        width: startRect.width,
        height: startRect.height,
        backgroundColor: neutralBg,
      }}
      animate={{
        left: targetLeft,
        top: targetTop,
        width: targetWidth,
        height: targetHeight,
        backgroundColor: tintBg,
      }}
      transition={{
        duration: animationDurationS,
        ease: [0.25, 0.1, 0.25, 1],
        backgroundColor: { duration: animationDurationS },
      }}
      onAnimationComplete={handleAnimationComplete}
    >
      <Text mainContentBody>{content}</Text>
    </motion.div>
  );
}
