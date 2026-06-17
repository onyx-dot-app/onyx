"use client";

import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "craft:showThinking";
const CHANGE_EVENT = "craft:showThinking:change";
const DEFAULT_ENABLED = false;

function readStorage(): boolean {
  if (typeof window === "undefined") return DEFAULT_ENABLED;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === null) return DEFAULT_ENABLED;
    return raw === "true";
  } catch {
    return DEFAULT_ENABLED;
  }
}

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return true;
  return target.isContentEditable;
}

interface UseShowThinkingResult {
  enabled: boolean;
  toggle: () => void;
}

/**
 * Global Craft preference for showing in-flight agent reasoning.
 * Toggle with Cmd+Shift+T (or Ctrl+Shift+T). Persists to localStorage,
 * suppressed while an editable element has focus.
 */
export function useShowThinking(): UseShowThinkingResult {
  const [enabled, setEnabled] = useState<boolean>(() => readStorage());

  const toggle = useCallback(() => {
    setEnabled((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(STORAGE_KEY, String(next));
      } catch {
        // Fall through — UI still updates from state.
      }
      window.dispatchEvent(
        new CustomEvent(CHANGE_EVENT, { detail: { enabled: next } })
      );
      return next;
    });
  }, []);

  // Cross-tab sync.
  useEffect(() => {
    const onChange = (e: Event) => {
      const detail = (e as CustomEvent<{ enabled: boolean }>).detail;
      if (detail) setEnabled(detail.enabled);
      else setEnabled(readStorage());
    };
    const onStorage = (e: StorageEvent) => {
      if (e.key === STORAGE_KEY) setEnabled(readStorage());
    };
    window.addEventListener(CHANGE_EVENT, onChange);
    window.addEventListener("storage", onStorage);
    return () => {
      window.removeEventListener(CHANGE_EVENT, onChange);
      window.removeEventListener("storage", onStorage);
    };
  }, []);

  // Cmd+Shift+T / Ctrl+Shift+T — preventDefault overrides the browser's
  // reopen-closed-tab in app contexts where the keyboard event reaches us.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const cmdLike = e.metaKey || e.ctrlKey;
      if (!cmdLike || !e.shiftKey) return;
      if (e.key !== "T" && e.key !== "t") return;
      if (isEditableTarget(e.target)) return;
      e.preventDefault();
      toggle();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle]);

  return { enabled, toggle };
}
