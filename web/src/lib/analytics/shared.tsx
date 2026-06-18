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
import { useCustomAnalyticsScript } from "@/lib/analytics/hooks";
import { useSettings } from "@/lib/settings/hooks";
import { initPostHog } from "@/app/providers";

// ─── PostHogRuntimeInitializer ──────────────────────────────────────────────

/**
 * Initializes PostHog from the runtime key in `/api/settings`, for deployments
 * that don't bake one into the web image. Must render inside the settings
 * provider. No-ops if a build-time key already initialized PostHog.
 */
export function PostHogRuntimeInitializer(): null {
  const { posthog_key, posthog_host } = useSettings();

  useEffect(() => {
    if (posthog_key) {
      initPostHog(posthog_key, posthog_host);
    }
  }, [posthog_key, posthog_host]);

  return null;
}

// ─── WebVitals ─────────────────────────────────────────────────────────────

/**
 * Captures Core Web Vitals (LCP, FID, CLS, INP, TTFB) as PostHog events.
 * Self-guards on PostHog being initialized, so it's safe to mount always.
 */
export function WebVitals(): null {
  const posthog = usePostHog();
  useReportWebVitals((metric) => {
    if (posthog.__loaded) {
      posthog.capture(metric.name, metric);
    }
  });
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
