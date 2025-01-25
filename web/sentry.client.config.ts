import * as Sentry from "@sentry/nextjs";

if (process.env.NEXT_PUBLIC_SENTRY_DSN) {
  Sentry.init({
    dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,

    // Capture unhandled exceptions and performance data
    enableTracing: false,
    integrations: [],
    tracesSampleRate: 0.1,
  });
}
