"use client";

import { useState, useEffect, useRef, memo } from "react";

interface TypewriterTextProps {
  /** The text to display with typewriter animation */
  text: string;
  /** Speed of each character animation in ms (default: 30) */
  charSpeed?: number;
  /** Whether to animate on initial render (default: false) */
  animateOnMount?: boolean;
  /** Class name for the text container */
  className?: string;
  /** Callback when animation completes */
  onAnimationComplete?: () => void;
}

/**
 * TypewriterText - Animates text changes with a delete-then-type effect.
 *
 * When text changes:
 * 1. Old text is deleted character by character (from end to start)
 * 2. New text is typed character by character (from start to end)
 *
 * This creates a smooth "rename" animation effect for session titles.
 */
function TypewriterText({
  text,
  charSpeed = 30,
  animateOnMount = false,
  className = "",
  onAnimationComplete,
}: TypewriterTextProps) {
  // Track the currently displayed text
  const [displayedText, setDisplayedText] = useState(
    animateOnMount ? "" : text
  );
  // Track whether we're in the "deleting" or "typing" phase
  const [isDeleting, setIsDeleting] = useState(false);
  // Store the target text we're animating towards
  const targetTextRef = useRef(text);
  // Store the previous text for comparison
  // When animateOnMount is true, initialize to empty so animation triggers
  const prevTextRef = useRef(animateOnMount ? "" : text);
  // Track if this is the first render
  const isFirstRender = useRef(true);
  // Animation frame ID for cleanup
  const animationRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    // Skip animation on first render unless animateOnMount is true
    if (isFirstRender.current) {
      isFirstRender.current = false;
      if (!animateOnMount) {
        setDisplayedText(text);
        prevTextRef.current = text;
        targetTextRef.current = text;
        return;
      }
      // When animateOnMount is true, we want to animate from empty to text
      // So we skip the delete phase and go straight to typing
      // Set prevTextRef to empty so subsequent renders don't trigger delete phase
      prevTextRef.current = "";
      targetTextRef.current = text;
      setIsDeleting(false); // Start in typing phase
      return;
    }

    // If text hasn't changed, no animation needed
    if (text === prevTextRef.current) {
      return;
    }

    // If we're currently animating from empty (animateOnMount case), don't restart
    // This happens when prevTextRef is "" (from animateOnMount) and we're typing
    if (
      prevTextRef.current === "" &&
      displayedText.length < targetTextRef.current.length &&
      !isDeleting
    ) {
      // We're in the middle of typing from animateOnMount, don't interrupt
      return;
    }

    // Clear any existing animation
    if (animationRef.current) {
      clearTimeout(animationRef.current);
    }

    // Update target and start deleting phase
    targetTextRef.current = text;
    setIsDeleting(true);

    return () => {
      if (animationRef.current) {
        clearTimeout(animationRef.current);
      }
    };
  }, [text, animateOnMount]);

  useEffect(() => {
    // Handle the animation loop
    if (isDeleting) {
      // Deleting phase: remove characters from the end
      if (displayedText.length > 0) {
        animationRef.current = setTimeout(() => {
          setDisplayedText((prev) => prev.slice(0, -1));
        }, charSpeed);
      } else {
        // Done deleting, switch to typing phase
        setIsDeleting(false);
        prevTextRef.current = targetTextRef.current;
      }
    } else {
      // Typing phase: add characters from the target
      const target = targetTextRef.current;
      if (displayedText.length < target.length) {
        animationRef.current = setTimeout(() => {
          setDisplayedText(target.slice(0, displayedText.length + 1));
        }, charSpeed);
      } else if (
        displayedText.length === target.length &&
        displayedText === target
      ) {
        // Animation complete - update prevTextRef so future changes are detected
        prevTextRef.current = target;
        onAnimationComplete?.();
      }
    }

    return () => {
      if (animationRef.current) {
        clearTimeout(animationRef.current);
      }
    };
  }, [displayedText, isDeleting, charSpeed, onAnimationComplete]);

  return <span className={className}>{displayedText}</span>;
}

export default memo(TypewriterText);
