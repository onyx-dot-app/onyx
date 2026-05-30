// Onyx mobile API client (mobile-owned). Ported from web and de-Next-ified.
// See docs/plans/2026-05-30-mobile-app/02-shared-packages.md
//
// The ClientConfig seam injects the fetch impl + auth headers; on mobile this is
// expo/fetch + a bearer PAT (wired in doc 07). Web keeps its own copy — the two are
// independent so they can scale separately.
//
// Next: domain types + streaming models live in `mobile/src/lib/types` (next increment),
// at which point `handleSSEStream`'s generic can be re-constrained to `PacketType`.

export type { ClientConfig } from "./config";
export { FetchError, RedirectError } from "./errors";
export { errorHandlingFetcher } from "./fetcher";
export { UrlBuilder } from "./url-builder";
export { handleSSEStream } from "./stream";
export { SWR_KEYS } from "./endpoints";
