// Mirrors web utilsSS.ts (the UrlBuilder class only).
// The env/cookie-coupled helpers (buildUrl/buildClientUrl/fetchSS — they read
// HOST_URL/INTERNAL_URL + next/headers) stay in web. Here the base URL comes from
// ClientConfig.baseUrl, so the static fromInternalUrl/fromClientUrl factories are dropped.

export class UrlBuilder {
  private url: URL;

  constructor(baseUrl: string) {
    try {
      this.url = new URL(baseUrl);
    } catch {
      // Handle relative URLs by prepending a placeholder base.
      this.url = new URL(baseUrl, "http://placeholder.com");
    }
  }

  addParam(key: string, value: string | number | boolean): UrlBuilder {
    this.url.searchParams.set(key, String(value));
    return this;
  }

  addParams(params: Record<string, string | number | boolean>): UrlBuilder {
    Object.entries(params).forEach(([key, value]) => {
      this.url.searchParams.set(key, String(value));
    });
    return this;
  }

  toString(): string {
    // Extract just the path + query for relative URLs.
    if (this.url.origin === "http://placeholder.com") {
      return `${this.url.pathname}${this.url.search}`;
    }
    return this.url.toString();
  }
}
