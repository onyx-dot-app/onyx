import type { ValidSources } from "@/lib/types";
import type { TypedFile } from "../fileTypes";

export interface OAuthAdditionalKwargDescription {
  name: string;
  display_name: string;
  description: string;
}

export interface OAuthDetails {
  oauth_enabled: boolean;
  supports_manual_credentials: boolean;
  additional_kwargs: OAuthAdditionalKwargDescription[];
}
export interface AuthMethodOption<TFields> {
  value: string;
  label: string;
  fields: TFields;
  description?: string;
  // UI-only: if true, hide/disable the "Auto Sync Permissions" access type when this auth is used
  disablePermSync?: boolean;
}
export interface CredentialTemplateWithAuth<TFields> {
  authentication_method?: string;
  authMethods?: AuthMethodOption<Partial<TFields>>[];
}

export interface CredentialBase<T> {
  credential_json: T;
  admin_public: boolean;
  source: ValidSources;
  name?: string;
  groups?: number[];
}

export interface CredentialWithPrivateKey<T> extends CredentialBase<T> {
  private_key: TypedFile;
}

export interface Credential<T> extends CredentialBase<T> {
  id: number;
  user_id: string | null;
  user_email: string | null;
  time_created: string;
  time_updated: string;
}
