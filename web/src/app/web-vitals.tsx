"use client";
import { useReportWebVitals } from "next/web-vitals";
import { usePostHog } from "posthog-js/react";

export function WebVitals() {
  const posthog = usePostHog();

  useReportWebVitals((metric) => {
    posthog.capture(metric.name, metric);
  });
  return <></>;
}
