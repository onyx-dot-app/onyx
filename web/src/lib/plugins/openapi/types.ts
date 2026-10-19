import type { KeyValue } from "@opal/components";
import type { OAuthConfigFields } from "@/lib/oauth/config";

/** How an OpenAPI plugin authenticates its calls. */
export type AuthMethod = "oauth" | "custom-header" | "pt-oauth" | "none";

export interface OpenAPIAuthFormValues extends OAuthConfigFields {
  authMethod: AuthMethod;
  headers: KeyValue[];
}

/** The one form behind the OpenAPI plugin modal, for add and edit. */
export interface OpenAPIPluginFormValues {
  name: string;
  description: string;
  /** The schema as the admin typed it. */
  definition: string;
  /** On for the whole workspace. */
  enabled: boolean;
  auth: OpenAPIAuthFormValues;
}
