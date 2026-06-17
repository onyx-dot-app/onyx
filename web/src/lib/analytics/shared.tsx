"use client";

/**
 * Shared analytics components.
 *
 * All components here are invisible (return `null`) and exist purely for their
 * side effects. Drop them into the root layout and forget about them.
 */

import { usePathname, useSearchParams } from "next/navigation";
import { useEffect, useRef, Suspense, type ReactElement } from "react";
import { usePostHog } from "posthog-js/react";
import { useReportWebVitals } from "next/web-vitals";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useSettings } from "@/lib/settings/hooks";
import { EE_ENABLED } from "@/lib/constants";

// ─── WebVitals ─────────────────────────────────────────────────────────────

/**
 * Captures Core Web Vitals (LCP, FID, CLS, INP, TTFB) as PostHog events.
 *
 * Only rendered when `NEXT_PUBLIC_POSTHOG_KEY` is set — callers are
 * responsible for that guard so this component is never mounted in
 * self-hosted / MIT installs where PostHog is absent.
 */
export function WebVitals(): null {
  const posthog = usePostHog();
  useReportWebVitals((metric) => posthog.capture(metric.name, metric));
  return null;
}

// ─── PostHogPageTracker ───────────────────────────────────────────────────────────

/**
 * Fires a PostHog `$pageview` event on every client-side route change.
 *
 * PostHog's automatic pageview capture is disabled in the provider config
 * (`capture_pageview: false`) because Next.js App Router navigation does not
 * trigger full page loads, which PostHog cannot detect on its own.
 *
 * Manages its own `<Suspense>` boundary (required by `useSearchParams()` in
 * Next.js), so callers can drop it in directly without wrapping it themselves.
 */
function PostHogPageTrackerInner(): null {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const posthog = usePostHog();

  useEffect(() => {
    if (!posthog) return;

    if (pathname) {
      let url = window.origin + pathname;
      if (searchParams?.toString()) {
        url = url + `?${searchParams.toString()}`;
      }
      posthog.capture("$pageview", {
        $current_url: url,
      });
    }
  }, [pathname, searchParams, posthog]);

  return null;
}
export function PostHogPageTracker(): ReactElement {
  return (
    <Suspense fallback={null}>
      <PostHogPageTrackerInner />
    </Suspense>
  );
}

// ─── CustomAnalyticsScript ─────────────────────────────────────────────────

/**
 * Fetches the admin-configured custom analytics script string.
 *
 * Self-gated on EE availability. Returns `null` when EE is disabled or no
 * script is configured.
 */
export function useCustomAnalyticsScript(): string | null {
  const { isLoading, error, ee_features_enabled } = useSettings();
  const shouldFetch =
    EE_ENABLED || (!isLoading && !error && ee_features_enabled !== false);

  const { data } = useSWR<string>(
    shouldFetch ? SWR_KEYS.customAnalyticsScript : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      revalidateIfStale: false,
      dedupingInterval: 60_000,
    }
  );
  return data ?? null;
}

/**
 * Injects an admin-configured JS analytics snippet into `document.head`.
 *
 * Enterprise Edition feature. Reads a raw JavaScript string stored server-side
 * and appends it as a `<script>` tag once on mount. This gives EE customers a
 * bring-your-own analytics escape hatch (e.g. Segment, Heap, Mixpanel)
 * without requiring a code change or redeployment.
 *
 * The injection is guarded by a ref so it only runs once, even if the value
 * identity changes across re-renders.
 */
export function CustomAnalyticsScript(): null {
  const customAnalyticsScript = useCustomAnalyticsScript();
  const injectedRef = useRef(false);

  useEffect(() => {
    if (!customAnalyticsScript || injectedRef.current) return;
    injectedRef.current = true;

    const script = document.createElement("script");
    script.type = "text/javascript";
    script.textContent = customAnalyticsScript;
    document.head.appendChild(script);
  }, [customAnalyticsScript]);

  return null;
}
