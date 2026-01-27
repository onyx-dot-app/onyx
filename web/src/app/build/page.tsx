"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

/**
 * Build Page - Redirects to the new Build V1 page
 *
 * The new Build experience is at /build/v1
 * This page exists for backwards compatibility.
 */
export default function BuildPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/build/v1");
  }, [router]);

  return (
    <div className="flex items-center justify-center h-screen">
      <div className="animate-pulse text-text-03">Redirecting...</div>
    </div>
  );
}
