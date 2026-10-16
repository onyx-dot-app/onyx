import { useCallback, useEffect, useState } from "react";
import { cn } from "@opal/utils";

/** The row whose popover is open in a list: it stays in front while the other rows step back. */
export function useFocusedRow<K extends string | number>(
  onFocusChange?: (focused: boolean) => void
) {
  const [openKey, setOpenKey] = useState<K | null>(null);
  useEffect(() => {
    onFocusChange?.(openKey !== null);
  }, [openKey, onFocusChange]);
  useEffect(() => () => onFocusChange?.(false), [onFocusChange]);

  const setOpen = useCallback((key: K, open: boolean) => {
    setOpenKey((current) => (open ? key : current === key ? null : current));
  }, []);

  return {
    focused: openKey !== null,
    isOpen: (key: K) => openKey === key,
    isDimmed: (key: K) => openKey !== null && openKey !== key,
    setOpen,
  };
}

/** Steps a row back to half opacity while another row holds the focus. */
export function focusDimClass(dimmed: boolean): string {
  return cn("transition-opacity", dimmed && "opacity-50");
}
