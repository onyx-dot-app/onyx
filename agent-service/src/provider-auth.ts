import type { Api, SimpleStreamOptions } from "@earendil-works/pi-ai";
import type { Start } from "./protocol";

/** Only deployment operators can permit shared workers to use their cloud identity. */
export function workloadIdentityAllowed(start: Start): boolean {
  return (
    start.allowWorkloadIdentity === true &&
    process.env.ONYX_AGENT_ALLOW_WORKLOAD_IDENTITY === "true"
  );
}

/** Translate normalized host options. Tenant configuration is never an environment. */
export function providerEnvironment(
  start: Start,
  provider: string,
): Record<string, string> {
  const env: Record<string, string> = {};
  const raw = start.options;
  const keys: Record<string, string> =
    provider === "amazon-bedrock"
      ? {
          aws_access_key_id: "AWS_ACCESS_KEY_ID",
          aws_secret_access_key: "AWS_SECRET_ACCESS_KEY",
          aws_session_token: "AWS_SESSION_TOKEN",
          aws_region_name: "AWS_REGION",
        }
      : provider === "google-vertex"
        ? {
            vertex_project: "GOOGLE_CLOUD_PROJECT",
            vertex_location: "GOOGLE_CLOUD_LOCATION",
          }
        : {};
  for (const [key, target] of Object.entries(keys)) {
    const value = raw[key];
    if (typeof value === "string" && value.trim()) env[target] = value;
  }
  if (provider === "amazon-bedrock") env.AWS_REGION ??= "us-east-1";
  if (provider === "google-vertex") env.GOOGLE_CLOUD_LOCATION ??= "global";
  if (provider === "azure-openai-responses") {
    if (start.config.api_version)
      env.AZURE_OPENAI_API_VERSION = start.config.api_version;
    if (start.config.api_base)
      env.AZURE_OPENAI_BASE_URL = start.config.api_base;
    if (start.config.deployment_name)
      env.AZURE_OPENAI_DEPLOYMENT_NAME = start.config.deployment_name;
  }
  return env;
}

/** Reject incomplete credentials before any SDK can consult a host identity. */
export function validateProviderAuth(
  start: Start,
  api: Api,
  options: SimpleStreamOptions,
): void {
  const apiKey = options.apiKey?.trim();
  if (
    api === "google-vertex" ||
    (["vertex_ai", "google-vertex"].includes(start.config.model_provider) &&
      !start.apiSurface)
  ) {
    // Google adapters construct and validate their own run-local auth clients.
    return;
  }
  if (api === "bedrock-converse-stream") {
    const env = options.env ?? {};
    const accessKey = env.AWS_ACCESS_KEY_ID;
    const secretKey = env.AWS_SECRET_ACCESS_KEY;
    const sessionToken = env.AWS_SESSION_TOKEN;
    if (
      Boolean(accessKey) !== Boolean(secretKey) ||
      (sessionToken && !accessKey)
    ) {
      throw new Error(
        "Bedrock requires a complete per-run AWS credential pair",
      );
    }
    if (apiKey || (accessKey && secretKey)) return;
    if (
      workloadIdentityAllowed(start) &&
      start.config.custom_config?.BEDROCK_AUTH_METHOD === "iam"
    )
      return;
    throw new Error(
      "Bedrock requires per-run credentials or explicitly enabled workload identity",
    );
  }
  const authHeaders =
    api === "anthropic-messages"
      ? ["authorization", "x-api-key", "cf-aig-authorization"]
      : ["authorization", "cf-aig-authorization"];
  const headerAuth = Object.entries(options.headers ?? {}).some(
    ([key, value]) =>
      authHeaders.includes(key.toLowerCase()) &&
      typeof value === "string" &&
      value.trim().length > 0,
  );
  if (!apiKey && !headerAuth)
    throw new Error("Provider requires explicit per-run authentication");
}
