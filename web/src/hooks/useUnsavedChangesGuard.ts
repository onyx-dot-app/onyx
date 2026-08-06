"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useUnsavedChangesNavigation } from "@/providers/UnsavedChangesNavigationProvider";

interface UnsavedChangesGuardOptions {
  isDirty: boolean;
  onDiscard?: () => void;
}

export default function useUnsavedChangesGuard({
  isDirty,
  onDiscard,
}: UnsavedChangesGuardOptions) {
  const router = useRouter();
  const { registerGuard } = useUnsavedChangesNavigation();
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const pendingNavigation = useRef<(() => void) | null>(null);
  const onDiscardRef = useRef(onDiscard);
  onDiscardRef.current = onDiscard;

  const requestLeave = useCallback(
    (navigate: () => void) => {
      if (!isDirty) {
        navigate();
        return;
      }
      pendingNavigation.current = navigate;
      setConfirmationOpen(true);
    },
    [isDirty]
  );

  const cancelLeave = useCallback(() => {
    pendingNavigation.current = null;
    setConfirmationOpen(false);
  }, []);

  const discardAndLeave = useCallback(() => {
    const navigate = pendingNavigation.current;
    pendingNavigation.current = null;
    setConfirmationOpen(false);
    onDiscardRef.current?.();
    navigate?.();
  }, []);

  useEffect(() => {
    if (!isDirty) return;
    return registerGuard(requestLeave);
  }, [isDirty, registerGuard, requestLeave]);

  useEffect(() => {
    if (isDirty) return;
    pendingNavigation.current = null;
    setConfirmationOpen(false);
  }, [isDirty]);

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
        router.push(
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
  }, [isDirty, requestLeave, router]);

  return {
    confirmationOpen,
    requestLeave,
    cancelLeave,
    discardAndLeave,
  };
}
