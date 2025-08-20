import React from "react";

export function BlinkingDot() {
  return (
    <span className="inline-flex items-center">
      <span className="animate-pulse text-text-600 dark:text-text-400">●</span>
    </span>
  );
}
