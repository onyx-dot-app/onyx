/**
 * The agent's cursor over the browser view.
 *
 * Ported from T3 Code (apps/web/src/components/preview/AgentBrowserCursor.tsx).
 * Copyright (c) 2026 T3 Tools Inc. Licensed under the MIT License.
 */
"use client";

import { useEffect, useState } from "react";
import { SvgMousePointer } from "@opal/icons";
import type { BrowserPointer } from "@/lib/chat/browser/types";

// How long the cursor stays fully shown after each move or click
const CURSOR_ACTIVE_MS = 700;

interface AgentBrowserCursorProps {
  phase: BrowserPointer["phase"];
  sequence: number;
  // CSS px from the view's top start corner
  left: number;
  top: number;
}

/** Glides to each agent pointer, ripples on a click, then fades. */
export function AgentBrowserCursor({
  phase,
  sequence,
  left,
  top,
}: AgentBrowserCursorProps) {
  const [inactiveSequence, setInactiveSequence] = useState<number | null>(null);
  const active = inactiveSequence !== sequence;

  useEffect(() => {
    const timeout = window.setTimeout(
      () => setInactiveSequence(sequence),
      CURSOR_ACTIVE_MS
    );
    return () => window.clearTimeout(timeout);
  }, [sequence]);

  return (
    <div
      // The page's coordinates run left to right in any reading direction
      className="pointer-events-none absolute left-0 top-0 z-20 transition-[opacity,transform] duration-150 ease-out motion-reduce:transition-none"
      style={{
        opacity: active ? 1 : 0.35,
        transform: `translate3d(${left}px, ${top}px, 0)`,
      }}
      aria-hidden="true"
      data-agent-browser-cursor
    >
      {phase === "click" && (
        <span
          key={sequence}
          className="absolute -left-1 -top-1 size-4 rounded-full bg-theme-primary-05 opacity-25 animate-ping motion-reduce:animate-none"
        />
      )}
      <SvgMousePointer
        size={20}
        className="relative -translate-x-0.5 -translate-y-0.5 fill-background-neutral-00 stroke-theme-primary-05 drop-shadow-sm"
      />
    </div>
  );
}
