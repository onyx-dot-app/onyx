import React from "react";

export function BlinkingDot({ addMargin = false }: { addMargin?: boolean }) {
  return (
    <div
      className={`animate-pulse flex-none bg-background-800 inline-block rounded-full h-3 w-3 ${
        addMargin ? "ml-2" : ""
      }`}
    />
  );
}
