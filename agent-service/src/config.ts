/** Validate deployment trust settings before connecting to Redis or sending credentials. */
export function validateWorkerConnection(config: {
  apiUrl: string;
  token: string;
  allowInsecureHttp?: boolean;
}): void {
  if (config.token.trim().length < 32 || /\s/.test(config.token))
    throw new Error(
      "ONYX_AGENT_SERVICE_TOKEN must be a random secret of at least 32 characters without whitespace",
    );
  let url: URL;
  try {
    url = new URL(config.apiUrl);
  } catch {
    throw new Error("ONYX_AGENT_API_URL must be a valid HTTP(S) URL");
  }
  if (url.username || url.password || url.search || url.hash)
    throw new Error(
      "ONYX_AGENT_API_URL must not contain credentials, a query, or a fragment",
    );
  if (
    url.protocol !== "https:" &&
    !(url.protocol === "http:" && config.allowInsecureHttp)
  )
    throw new Error(
      "ONYX_AGENT_API_URL requires HTTPS; allow HTTP explicitly only for development or independently protected transport",
    );
}
