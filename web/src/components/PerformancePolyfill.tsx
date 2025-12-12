"use client";

import { useEffect } from "react";

/**
 * Polyfill to fix Performance API issues in Chrome extension iframes.
 * Next.js (especially with Turbopack) uses performance.measure() which can fail
 * in iframe contexts where timing origins differ, causing:
 * "Failed to execute 'measure' on 'Performance': '​NotFound' cannot have a negative time stamp"
 */
export function PerformancePolyfill() {
  useEffect(() => {
    if (typeof window === "undefined" || !window.performance) return;

    const originalMeasure = window.performance.measure.bind(window.performance);
    const originalMark = window.performance.mark.bind(window.performance);

    // Track marks we've created to avoid "mark not found" errors
    const marks = new Set<string>();

    window.performance.mark = function (
      markName: string,
      markOptions?: PerformanceMarkOptions
    ): PerformanceMark {
      try {
        marks.add(markName);
        return originalMark(markName, markOptions);
      } catch {
        // Return a minimal PerformanceMark-like object if marking fails
        return {
          name: markName,
          entryType: "mark",
          startTime: performance.now(),
          duration: 0,
          detail: markOptions?.detail ?? null,
          toJSON: () => ({}),
        } as PerformanceMark;
      }
    };

    window.performance.measure = function (
      measureName: string,
      startOrMeasureOptions?: string | PerformanceMeasureOptions,
      endMark?: string
    ): PerformanceMeasure {
      try {
        // If using string markers, check they exist
        if (
          typeof startOrMeasureOptions === "string" &&
          !marks.has(startOrMeasureOptions)
        ) {
          throw new Error("Start mark not found");
        }
        if (endMark && !marks.has(endMark)) {
          throw new Error("End mark not found");
        }
        return originalMeasure(measureName, startOrMeasureOptions, endMark);
      } catch {
        // Return a minimal PerformanceMeasure-like object if measurement fails
        return {
          name: measureName,
          entryType: "measure",
          startTime: performance.now(),
          duration: 0,
          detail: null,
          toJSON: () => ({}),
        } as PerformanceMeasure;
      }
    };

    // Cleanup on unmount
    return () => {
      window.performance.measure = originalMeasure;
      window.performance.mark = originalMark;
    };
  }, []);

  return null;
}
