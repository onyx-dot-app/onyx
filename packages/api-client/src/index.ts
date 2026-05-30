// @onyx-ai/api-client — transport-neutral Onyx API client shared by web + mobile.
//
// Contents are owned by: docs/plans/2026-05-30-mobile-app/02-shared-packages.md
// The client takes an INJECTED `fetch` impl and an async header provider (a ClientConfig
// seam), so web supplies browser fetch + cookies and mobile supplies expo/fetch + a bearer PAT.
//
// Port from:
//   web/src/lib/fetcher.ts          (FetchError, RedirectError, errorHandlingFetcher)
//   web/src/lib/swr-keys.ts         (SWR_KEYS endpoint registry)
//   web/src/lib/utilsSS.ts          (UrlBuilder, minus next/headers)
//   web/src/lib/search/streamingUtils.ts (handleSSEStream — the NDJSON line-buffered reader;
//                                         note: the stream is NDJSON mislabeled text/event-stream,
//                                         so never use an EventSource/SSE client). See doc 07.
//
// Source-only internal package: consumers import TS directly via the workspace symlink.

export {};
