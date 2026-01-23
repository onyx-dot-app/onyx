"use client";

import { useState, useEffect, useRef } from "react";

const messages = [
  "Punching wood...",
  "Gathering resources...",
  "Placing blocks...",
  "Crafting your workspace...",
  "Mining for dependencies...",
  "Smelting the code...",
  "Enchanting with magic...",
  "World generation complete...",
  "/gamemode 1",
];

const MESSAGE_COUNT = messages.length;
const TYPE_DELAY = 40;
const LINE_PAUSE = 800;
const RESET_DELAY = 2000;

export default function CraftingLoader() {
  const [display, setDisplay] = useState({
    lines: [] as string[],
    currentText: "",
  });

  const lineIndexRef = useRef(0);
  const charIndexRef = useRef(0);
  const lastUpdateRef = useRef(0);
  const timeoutRef = useRef<NodeJS.Timeout | undefined>(undefined);
  const rafRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    let isActive = true;

    const update = (now: number) => {
      if (!isActive) return;

      const lineIdx = lineIndexRef.current;
      const charIdx = charIndexRef.current;

      if (lineIdx >= MESSAGE_COUNT) {
        timeoutRef.current = setTimeout(() => {
          if (!isActive) return;
          lineIndexRef.current = 0;
          charIndexRef.current = 0;
          setDisplay({ lines: [], currentText: "" });
          lastUpdateRef.current = performance.now();
          rafRef.current = requestAnimationFrame(update);
        }, RESET_DELAY);
        return;
      }

      const msg = messages[lineIdx];
      if (!msg) return;

      const elapsed = now - lastUpdateRef.current;

      if (charIdx < msg.length) {
        if (elapsed >= TYPE_DELAY) {
          charIndexRef.current = charIdx + 1;
          setDisplay((prev) => ({
            lines: prev.lines,
            currentText: msg.substring(0, charIdx + 1),
          }));
          lastUpdateRef.current = now;
        }
      } else if (elapsed >= LINE_PAUSE) {
        setDisplay((prev) => ({
          lines: [...prev.lines, msg],
          currentText: "",
        }));
        lineIndexRef.current = lineIdx + 1;
        charIndexRef.current = 0;
        lastUpdateRef.current = now;
      }

      rafRef.current = requestAnimationFrame(update);
    };

    lastUpdateRef.current = performance.now();
    rafRef.current = requestAnimationFrame(update);

    return () => {
      isActive = false;
      if (rafRef.current !== undefined) cancelAnimationFrame(rafRef.current);
      if (timeoutRef.current !== undefined) clearTimeout(timeoutRef.current);
    };
  }, []);

  const { lines, currentText } = display;
  const hasCurrentText = currentText.length > 0;

  return (
    <div className="min-h-screen bg-gradient-to-br from-neutral-950 via-neutral-900 to-neutral-950 flex flex-col items-center justify-center p-4">
      <div className="w-full max-w-md rounded-sm overflow-hidden shadow-2xl border-2 border-neutral-700">
        <div className="bg-neutral-800 px-4 py-3 flex items-center gap-2 border-b-2 border-neutral-700">
          <div className="w-3 h-3 rounded-none bg-red-500" />
          <div className="w-3 h-3 rounded-none bg-yellow-500" />
          <div className="w-3 h-3 rounded-none bg-green-500" />
          <span className="ml-4 text-neutral-500 text-sm font-mono">
            crafting_table
          </span>
        </div>

        <div className="bg-neutral-900 p-6 min-h-[250px] font-mono text-sm">
          {lines.map((line, i) => (
            <div key={i} className="flex items-center text-neutral-300">
              <span className="text-emerald-500 mr-2">/&gt;</span>
              <span>{line}</span>
            </div>
          ))}
          {hasCurrentText && (
            <div className="flex items-center text-neutral-300">
              <span className="text-emerald-500 mr-2">/&gt;</span>
              <span>{currentText}</span>
            </div>
          )}
          <div className="flex items-center text-neutral-300">
            <span className="text-emerald-500 mr-2">/&gt;</span>
            <span className="w-2 h-5 bg-emerald-500 animate-pulse" />
          </div>
        </div>
      </div>

      <p className="mt-6 text-neutral-500 text-sm font-mono">
        Crafting your next great idea...
      </p>
    </div>
  );
}
