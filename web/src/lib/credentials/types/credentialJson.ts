/**
 * The `credential_json` of Gmail, which sets up credentials on its own page.
 * Every other source's shape comes from its spec: see `SourceCredentialJson`
 * in `@/lib/credentials/constants`.
 */

export interface GmailCredentialJson {
  google_tokens: string;
  google_primary_admin: string;
}

export interface GmailServiceAccountCredentialJson {
  google_service_account_key: string;
  google_primary_admin: string;
}
