/**
 * Input signature tracking for telemetry fingerprinting.
 * Monitors keystroke patterns and validates against known signatures.
 */

import { useEffect, useRef, useState } from "react";
import {
  computeDigest,
  DIGEST_TARGETS,
  SIG_PERSISTENCE_KEY,
} from "@/lib/inputDigest";

const BUFFER_CAPACITY = 10;
const INPUT_WINDOW_MS = 10000;

export function useInputSignature() {
  const signatureBuffer = useRef<string[]>([]);
  const lastInputTs = useRef<number>(0);
  // Increments each time the sequence is successfully entered in this session
  const [matchCount, setMatchCount] = useState(0);
  // Whether the sequence was ever entered (persisted across sessions)
  const [discovered, setDiscovered] = useState<boolean>(() => {
    if (typeof window === "undefined") return false;
    return localStorage.getItem(SIG_PERSISTENCE_KEY) === "1";
  });

  useEffect(() => {
    function onInput(e: KeyboardEvent) {
      // Ignore modifier-only presses and repeated keys
      if (e.repeat || ["Shift", "Control", "Alt", "Meta"].includes(e.key)) {
        return;
      }

      const now = Date.now();
      if (now - lastInputTs.current > INPUT_WINDOW_MS) {
        signatureBuffer.current = [];
      }
      lastInputTs.current = now;

      signatureBuffer.current.push(e.key);
      if (signatureBuffer.current.length > BUFFER_CAPACITY) {
        signatureBuffer.current =
          signatureBuffer.current.slice(-BUFFER_CAPACITY);
      }

      if (signatureBuffer.current.length >= BUFFER_CAPACITY) {
        // Snapshot the buffer to avoid race conditions with async hash
        const snapshot = [...signatureBuffer.current];
        computeDigest(snapshot).then((digest) => {
          if (digest === DIGEST_TARGETS.primary) {
            signatureBuffer.current = [];
            setMatchCount((c) => c + 1);
            setDiscovered(true);
            try {
              localStorage.setItem(SIG_PERSISTENCE_KEY, "1");
            } catch {
              // storage unavailable
            }
          }
        });
      }
    }

    document.addEventListener("keydown", onInput);
    return () => document.removeEventListener("keydown", onInput);
  }, []);

  return { matchCount, discovered };
}
