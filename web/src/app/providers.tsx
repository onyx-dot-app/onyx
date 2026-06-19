"use client";
import posthog from "posthog-js";
import { PostHogProvider } from "posthog-js/react";
import { useEffect } from "react";

/**
 * Initialize PostHog. Idempotent, so the build-time path (PHProvider) and the
 * runtime path (PostHogRuntimeInitializer) can both call it safely.
 */
export function initPostHog(key: string, host?: string | null): void {
  if (posthog.__loaded) return;
  posthog.init(key, {
    api_host: "/ph_ingest",
    ui_host: host || "https://us.posthog.com",
    person_profiles: "identified_only",
    capture_pageview: false,
    session_recording: {
      // Sensitive inputs should use data-ph-no-capture attribute
      maskAllInputs: false,
    },
  });
}

interface PHProviderProps {
  children: React.ReactNode;
}

export function PHProvider({ children }: PHProviderProps) {
  useEffect(() => {
    // Build-time key (Onyx Cloud); otherwise PostHogRuntimeInitializer handles it.
    const buildTimeKey = process.env.NEXT_PUBLIC_POSTHOG_KEY;
    if (buildTimeKey) {
      initPostHog(buildTimeKey, process.env.NEXT_PUBLIC_POSTHOG_HOST);
    }
  }, []);

  return <PostHogProvider client={posthog}>{children}</PostHogProvider>;
}
