/**
 * The `credential_json` of the Google sources, which set up credentials on
 * their own pages. Every other source's shape comes from its spec: see
 * `SourceCredentialJson` in `@/lib/credentials/specs`.
 */

export interface GmailCredentialJson {
  google_tokens: string;
  google_primary_admin: string;
}

export interface GoogleDriveCredentialJson {
  google_tokens: string;
  google_primary_admin: string;
  authentication_method?: string;
}

export interface GmailServiceAccountCredentialJson {
  google_service_account_key: string;
  google_primary_admin: string;
}

export interface GoogleDriveServiceAccountCredentialJson {
  google_service_account_key: string;
  google_primary_admin: string;
  authentication_method?: string;
}
