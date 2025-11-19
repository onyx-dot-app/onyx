import React from "react";

export function BlinkingDot({ addMargin = false }: { addMargin?: boolean }) {
  return (
    <span
      className={`animate-pulse flex-none bg-theme-primary-05 inline-block rounded-full h-3 w-3 ${
        addMargin ? "ml-2" : ""
      }`}
    />
  );
}
