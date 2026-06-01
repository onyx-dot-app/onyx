// Onyx mobile API client (mobile-owned). Mirrors web's lib/fetcher + utilsSS.
//
// The ClientConfig seam injects the fetch impl + auth headers; on mobile this is
// expo/fetch + a bearer PAT. Web keeps its own copy — the two are independent so
// they can scale separately.

export type { ClientConfig } from "./config";
export { FetchError, RedirectError } from "./errors";
export { errorHandlingFetcher, errorHandlingFetcherVoid } from "./fetcher";
export { UrlBuilder } from "./url-builder";
export { handleSSEStream } from "./stream";
export { SWR_KEYS } from "./endpoints";
export {
  uploadChatFiles,
  fetchFileStatuses,
  chatFileUrl,
  type UploadableFile,
} from "./files";
