"use client";
import posthog from "posthog-js";
import { PostHogProvider } from "posthog-js/react";
import { useEffect, useState } from "react";

const isPostHogEnabled = !!(
  process.env.NEXT_PUBLIC_POSTHOG_KEY && process.env.NEXT_PUBLIC_POSTHOG_HOST
);

type PHProviderProps = { children: React.ReactNode };

export function PHProvider({ children }: PHProviderProps) {
  const [posthogReady, setPosthogReady] = useState(false);

  useEffect(() => {
    if (isPostHogEnabled && !posthog.__loaded) {
      posthog.init(process.env.NEXT_PUBLIC_POSTHOG_KEY!, {
        api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST!,
        person_profiles: "identified_only",
        capture_pageview: false,
        loaded: (posthog) => {
          setPosthogReady(true);
        },
      });
    } else if (isPostHogEnabled && posthog.__loaded) {
      setPosthogReady(true);
    } else {
      setPosthogReady(true); // Not enabled, but ready to render children
    }
  }, []);

  if (!isPostHogEnabled) {
    return <>{children}</>;
  }

  // Wait for PostHog to be initialized before rendering the provider
  if (!posthogReady) {
    return <>{children}</>; // Or a loading state if preferred
  }

  return <PostHogProvider client={posthog}>{children}</PostHogProvider>;
}
