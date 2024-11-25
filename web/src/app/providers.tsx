"use client";
import posthog from "posthog-js";
import { PostHogProvider } from "posthog-js/react";
import { useEffect } from "react";

const isPostHogEnabled = !!(
  process.env.NEXT_PUBLIC_POSTHOG_KEY && process.env.NEXT_PUBLIC_POSTHOG_HOST
);

export function PHProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    if (isPostHogEnabled) {
      posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY!, {
        api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST!,
        person_profiles: "identified_only",
        capture_pageview: false,
      });
    }
  }, []);

  if (!isPostHogEnabled) {
    return <>{children}</>;
  }

  return <PostHogProvider client={posthog}>{children}</PostHogProvider>;
}
