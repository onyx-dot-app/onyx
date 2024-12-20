declare module "favicon-fetch" {
  interface FaviconFetchOptions {
    uri: string;
  }

  function faviconFetch(options: FaviconFetchOptions): string | null;

  export default faviconFetch;
}
