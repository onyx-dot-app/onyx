import * as Sentry from "@sentry/nextjs";

if (process.env.NEXT_PUBLIC_SENTRY_DSN) {
  Sentry.init({
    dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
    // Only capture unhandled exceptions
    tracesSampleRate: 0,
    enableTracing: false,
    autoSessionTracking: false,
  });
}
