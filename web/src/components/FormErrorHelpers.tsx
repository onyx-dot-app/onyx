"use client";

import { useEffect, useRef } from "react";
import { useFormikContext } from "formik";

// After a submit with errors, scroll + focus the first invalid field
export function FormErrorFocus() {
  const { submitCount, errors, isSubmitting } = useFormikContext<any>();
  const lastHandled = useRef(0);

  useEffect(() => {
    if (isSubmitting) return;
    if (submitCount <= 0 || submitCount === lastHandled.current) return;

    const keys = Object.keys(errors || {});
    if (keys.length === 0) return;

    const timer = setTimeout(() => {
      try {
        let target: HTMLElement | null = null;

        // 1) Try by id, then data-testid
        for (const key of keys) {
          target =
            (document.getElementById(key) as HTMLElement | null) ||
            (document.querySelector(
              `[data-testid="${key}"]`
            ) as HTMLElement | null);
          if (target) break;
        }

        // 2) Fallback: first element with matching name
        if (!target) {
          for (const key of keys) {
            const byName = document.getElementsByName(key);
            if (byName && byName.length > 0) {
              target = byName[0] as HTMLElement;
              break;
            }
          }
        }

        if (target) {
          target.scrollIntoView({ behavior: "smooth", block: "center" });
          if (typeof (target as any).focus === "function") {
            (target as any).focus({ preventScroll: true });
          }
        }
      } finally {
        lastHandled.current = submitCount;
      }
    }, 0);

    return () => clearTimeout(timer);
  }, [submitCount, errors, isSubmitting]);

  return null;
}
