// Onyx mobile API client. Mirrors web's lib/fetcher + utilsSS. The ClientConfig
// seam injects the fetch impl + auth headers (mobile: expo/fetch + bearer PAT).

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
