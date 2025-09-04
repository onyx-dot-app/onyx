// This file configures the initialization of Sentry on the server.
// The config you add here will be used whenever the server handles a request.
// https://docs.sentry.io/platforms/javascript/guides/nextjs/

import * as Sentry from "@sentry/nextjs";

Sentry.init({
  dsn: "https://f9db349b4cb5783fb7c93ba0e72c0669@o4509930383998976.ingest.us.sentry.io/4509958506938368",

  // Setting this option to true will print useful information to the console while you're setting up Sentry.
  debug: false,
});
