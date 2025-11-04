import { useState, useEffect, useCallback, useMemo, useRef } from "react";

interface DropdownPosition {
  top: number;
  left: number;
  width: number;
  flipped: boolean;
}

// Utility: Debounce function for performance optimization
function debounce<T extends (...args: any[]) => any>(
  func: T,
  wait: number
): T & { cancel: () => void } {
  let timeout: NodeJS.Timeout | null = null;

  const debounced = function (this: any, ...args: Parameters<T>) {
    if (timeout) clearTimeout(timeout);
    timeout = setTimeout(() => func.apply(this, args), wait);
  } as T & { cancel: () => void };

  debounced.cancel = () => {
    if (timeout) clearTimeout(timeout);
  };

  return debounced;
}

interface UseDropdownPositionProps {
  isOpen: boolean;
}

/**
 * Manages dropdown positioning with collision detection
 * Handles scroll and resize events with debouncing for performance
 */
export function useDropdownPosition({ isOpen }: UseDropdownPositionProps) {
  const [dropdownPosition, setDropdownPosition] =
    useState<DropdownPosition | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // Calculate dropdown position with collision detection
  const updatePosition = useCallback(() => {
    if (containerRef.current && isOpen) {
      const rect = containerRef.current.getBoundingClientRect();
      const dropdownHeight = 240; // max-h-60 = 15rem = 240px
      const gap = 4; // margin between input and dropdown
      const viewportPadding = 8; // minimum distance from viewport edge

      // Calculate available space
      const spaceBelow = window.innerHeight - rect.bottom;
      const spaceAbove = rect.top;

      // Determine if dropdown should flip above the input
      const shouldFlipUp =
        spaceBelow < dropdownHeight && spaceAbove > spaceBelow;

      // Calculate vertical position
      const top = shouldFlipUp
        ? rect.top + window.scrollY - dropdownHeight - gap
        : rect.bottom + window.scrollY + gap;

      // Calculate horizontal position with boundary constraints
      const left = Math.max(
        viewportPadding,
        Math.min(
          rect.left + window.scrollX,
          window.innerWidth - rect.width - viewportPadding
        )
      );

      setDropdownPosition({
        top,
        left,
        width: rect.width,
        flipped: shouldFlipUp,
      });
    }
  }, [isOpen]);

  // Memoize debounced position updater
  const debouncedUpdatePosition = useMemo(
    () => debounce(updatePosition, 16), // ~60fps
    [updatePosition]
  );

  // Position calculation with debouncing for scroll/resize
  useEffect(() => {
    if (isOpen) {
      updatePosition(); // Immediate on open
      window.addEventListener("scroll", debouncedUpdatePosition, true);
      window.addEventListener("resize", debouncedUpdatePosition);

      return () => {
        debouncedUpdatePosition.cancel();
        window.removeEventListener("scroll", debouncedUpdatePosition, true);
        window.removeEventListener("resize", debouncedUpdatePosition);
      };
    }
  }, [isOpen, updatePosition, debouncedUpdatePosition]);

  return { dropdownPosition, containerRef };
}
