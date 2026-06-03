// This file configures the initialization of Sentry on the server.
// The config you add here will be used whenever the server handles a request.
// https://docs.sentry.io/platforms/javascript/guides/nextjs/

import * as Sentry from "@sentry/nextjs";

if (process.env.NEXT_PUBLIC_SENTRY_DSN) {
  Sentry.init({
    dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
    release: process.env.SENTRY_RELEASE,

    // Setting this option to true will print useful information to the console while you're setting up Sentry.
    debug: false,

    // Disable performance monitoring and only capture errors
    tracesSampleRate: 0,
    profilesSampleRate: 0,

    // We don't use tracing (tracesSampleRate: 0), so the ESM loader hooks that
    // Sentry registers to auto-instrument libraries provide no value here. Skip
    // registering them to avoid the Node DEP0205 deprecation warning emitted by
    // @sentry/node-core's `module.register('import-in-the-middle/hook.mjs', ...)`
    // call (`module.register()` is deprecated in favor of `module.registerHooks()`).
    registerEsmLoaderHooks: false,
  });
}
