"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback } from "react";
import type { AppPosition } from "@/lib/app/hooks";

/**
 * Navigates to a position.
 *
 * The caller names where the user should end up; {@link AppPosition.href}
 * knows what URL that is. Nothing here assembles one, so the pathname and
 * parameter names stay in the one place that also reads them back.
 */
export function useAppRouter() {
  const router = useRouter();
  return useCallback(
    (position: AppPosition) => router.push(position.href()),
    [router]
  );
}

export function useAppParams() {
  const searchParams = useSearchParams();
  return useCallback((name: string) => searchParams.get(name), [searchParams]);
}
