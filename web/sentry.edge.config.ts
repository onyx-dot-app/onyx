// This file configures the initialization of Sentry for edge features (middleware, edge routes, and so on).
// The config you add here will be used whenever one of the edge features is loaded.
// Note that this config is unrelated to the Vercel Edge Runtime and is also required when running locally.
// https://docs.sentry.io/platforms/javascript/guides/nextjs/

import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn: "https://f9db349b4cb5783fb7c93ba0e72c0669@o4509930383998976.ingest.us.sentry.io/4509958506938368",

  // Setting this option to true will print useful information to the console while you're setting up Sentry.
  debug: false,
});
