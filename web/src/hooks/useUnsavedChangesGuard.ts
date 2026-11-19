"use client";

import { useNavigation } from "@opal/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Route } from "next";
import { useUnsavedChangesNavigation } from "@/providers/UnsavedChangesNavigationProvider";

interface UnsavedChangesGuardOptions {
  isDirty: boolean;
  onDiscard?: () => void;
}

export default function useUnsavedChangesGuard({
  isDirty,
  onDiscard,
}: UnsavedChangesGuardOptions) {
  const navigation = useNavigation();
  const { registerGuard } = useUnsavedChangesNavigation();
  const [pendingLeave, setPendingLeave] = useState<{
    navigate: () => void;
  } | null>(null);
  const onDiscardRef = useRef(onDiscard);

  // oxlint-disable-next-line anti-slop/no-unreasoned-state-sync -- keeps the latest onDiscard in a ref for discardAndLeave
  useEffect(() => {
    onDiscardRef.current = onDiscard;
  }, [onDiscard]);

  const requestLeave = useCallback(
    (navigate: () => void) => {
      if (!isDirty) {
        navigate();
        return;
      }
      setPendingLeave({ navigate });
    },
    [isDirty]
  );

  const cancelLeave = useCallback(() => {
    setPendingLeave(null);
  }, []);

  const discardAndLeave = useCallback(() => {
    setPendingLeave(null);
    onDiscardRef.current?.();
    pendingLeave?.navigate();
  }, [pendingLeave]);

  // oxlint-disable-next-line anti-slop/no-unreasoned-state-sync -- registers the leave guard with the navigation provider while dirty
  useEffect(() => {
    if (!isDirty) return;
    return registerGuard(requestLeave);
  }, [isDirty, registerGuard, requestLeave]);

  // Saving or reverting the changes drops a pending leave.
  if (!isDirty && pendingLeave !== null) setPendingLeave(null);

  // oxlint-disable-next-line anti-slop/no-unreasoned-state-sync -- beforeunload and capture click listeners that guard leaving while dirty
  useEffect(() => {
    if (!isDirty) return;

    function warnBeforeUnload(event: BeforeUnloadEvent) {
      event.preventDefault();
    }

    function guardInternalLink(event: MouseEvent) {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      ) {
        return;
      }
      const target = event.target;
      if (!(target instanceof Element)) return;
      const anchor = target.closest<HTMLAnchorElement>("a[href]");
      if (!anchor || anchor.target || anchor.hasAttribute("download")) return;

      const destination = new URL(anchor.href, window.location.href);
      const current = new URL(window.location.href);
      if (
        destination.origin !== current.origin ||
        (destination.pathname === current.pathname &&
          destination.search === current.search)
      ) {
        return;
      }

      event.preventDefault();
      requestLeave(() =>
        navigation.go(
          `${destination.pathname}${destination.search}${destination.hash}` as Route
        )
      );
    }

    window.addEventListener("beforeunload", warnBeforeUnload);
    document.addEventListener("click", guardInternalLink, true);
    return () => {
      window.removeEventListener("beforeunload", warnBeforeUnload);
      document.removeEventListener("click", guardInternalLink, true);
    };
  }, [isDirty, requestLeave, navigation]);

  return {
    confirmationOpen: pendingLeave !== null,
    requestLeave,
    cancelLeave,
    discardAndLeave,
  };
}
