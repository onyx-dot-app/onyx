import type { KeyValue } from "@opal/components";
import type { OAuthConfigFields } from "@/lib/oauth/config";

/** How an OpenAPI plugin authenticates its calls. */
export type AuthMethod = "oauth" | "custom-header" | "pt-oauth" | "none";

export interface OpenAPIAuthFormValues extends OAuthConfigFields {
  authMethod: AuthMethod;
  headers: KeyValue[];
}
