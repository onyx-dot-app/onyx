import { JWT, OAuth2Client } from "google-auth-library";
import { z } from "zod";
import type { Start } from "./protocol";
import { workloadIdentityAllowed } from "./provider-auth";

const scope = "https://www.googleapis.com/auth/cloud-platform";
const serviceAccount = z.object({
  type: z.literal("service_account"),
  project_id: z.string().min(1).optional(),
  client_email: z.string().email(),
  private_key: z.string().min(1).max(32768),
});

/** Explicit endpoints prevent SDK environment defaults from redirecting run credentials. */
export function vertexBaseUrl(location: string): string {
  if (location === "global") return "https://aiplatform.googleapis.com";
  if (location === "us" || location === "eu")
    return `https://aiplatform.${location}.rep.googleapis.com`;
  return `https://${location}-aiplatform.googleapis.com`;
}

/** Accept key material, never SDK credential configs that can read files or URLs. */
export function googleAuthentication(start: Start) {
  const raw = start.options;
  let project =
    typeof raw.vertex_project === "string" ? raw.vertex_project : undefined;
  const location =
    typeof raw.vertex_location === "string" ? raw.vertex_location : "global";
  let authClient: OAuth2Client | undefined;
  if (raw.vertex_credentials !== undefined && raw.vertex_credentials !== null) {
    let parsed: z.infer<typeof serviceAccount>;
    try {
      parsed = serviceAccount.parse(
        JSON.parse(z.string().max(65536).parse(raw.vertex_credentials)),
      );
    } catch {
      // Parser errors can include private keys. Do not propagate their input values.
      throw new Error(
        "Vertex credentials must contain a valid service-account email and private key",
      );
    }
    project ??= parsed.project_id;
    authClient = new JWT({
      email: parsed.client_email,
      key: parsed.private_key,
      scopes: [scope],
    });
  } else if (
    typeof raw.vertex_access_token === "string" &&
    raw.vertex_access_token.trim()
  ) {
    authClient = new OAuth2Client();
    authClient.setCredentials({ access_token: raw.vertex_access_token });
  } else if (!(
    workloadIdentityAllowed(start) &&
    start.config.custom_config?.vertex_auth_method === "workload_identity"
  )) {
    throw new Error(
      "Vertex requires per-run credentials or explicitly enabled workload identity",
    );
  }
  if (
    !project ||
    !/^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$/.test(project) ||
    !/^[a-z0-9-]{1,64}$/.test(location)
  ) {
    throw new Error("Vertex requires an explicit valid project and location");
  }
  return { authClient, project, location, scopes: [scope] };
}
