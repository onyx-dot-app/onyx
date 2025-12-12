"use client";

import React, { useEffect, useRef, useState } from "react";
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
  const [liveTargetRect, setLiveTargetRect] = useState<DOMRect | null>(null);
  const [animationStarted, setAnimationStarted] = useState(false);
  const [animationDurationS, setAnimationDurationS] = useState(0.3);

  // Read the CSS variable so styling controls duration.
  useEffect(() => {
    if (!bubbleRef.current) return;
    const raw = getComputedStyle(bubbleRef.current).getPropertyValue(
      "--message-send-duration"
    );
    const parsed = raw.trim().toLowerCase();
    let seconds = parseFloat(parsed);
    if (Number.isNaN(seconds) || seconds <= 0) return;
    setAnimationDurationS(seconds);
  }, []);

  // Continuously track the latest target rect so the animation follows scroll/resize
  useEffect(() => {
    if (!targetRef?.current) return;

    let frameId: number;
    const updateRect = () => {
      if (!targetRef?.current) return;
      setLiveTargetRect(targetRef.current.getBoundingClientRect());
      frameId = requestAnimationFrame(updateRect);
    };

    // Set initial rect immediately
    setLiveTargetRect(targetRef.current.getBoundingClientRect());
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
  const deltaX = targetRect ? targetRect.left - startRect.left : 0;
  const deltaY = targetRect ? targetRect.top - startRect.top : 0;

  return (
    <motion.div
      ref={bubbleRef}
      className={cn(
        "fixed pointer-events-none z-[9999] whitespace-break-spaces rounded-t-16 rounded-bl-16 py-2 px-3 text-user-text overflow-hidden animated-message-bubble",
        animationStarted && "animated-message-bubble--target"
      )}
      style={{
        left: startRect.left,
        top: startRect.top,
      }}
      initial={{
        x: 0,
        y: 0,
        width: startRect.width,
        height: startRect.height,
        backgroundColor: "var(--background-neutral-00)",
      }}
      animate={{
        x: deltaX,
        y: deltaY,
        width: targetWidth,
        height: targetHeight,
        backgroundColor: "var(--background-tint-02)",
      }}
      transition={{
        duration: animationDurationS,
        ease: [0.25, 0.1, 0.25, 1],
        backgroundColor: { duration: animationDurationS },
      }}
      onAnimationComplete={onAnimationComplete}
    >
      <Text mainContentBody>{content}</Text>
    </motion.div>
  );
}
