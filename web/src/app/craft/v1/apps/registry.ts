/**
 * Built-in external-app provider registry.
 *
 * Each entry is the canonical "preset" the admin POSTs to the backend
 * when enabling a built-in provider. The frontend owns this rather
 * than the backend so the admin doesn't have to type out auth template
 * details that a typical user couldn't be expected to know.
 *
 * Adding a new provider: add an entry here, give it a unique key, fill
 * in the OAuth handler on the backend (currently Slack-specific in
 * `external_apps_oauth_api.py`), and the admin/user pages pick it up
 * automatically.
 */

import { SvgSlack, SvgLinear } from "@opal/logos";
import { SvgCalendar } from "@opal/icons";
import { IconFunctionComponent } from "@opal/types";

export type BuiltInProviderKey = "slack" | "googleCalendar" | "linear";

/** A credential field the admin must fill in when configuring a provider. */
export interface OrgCredentialField {
  /** Key inside `organization_credentials` JSONB. */
  key: string;
  /** Label rendered in the admin form. */
  label: string;
  /** Short helper text under the input. */
  description: string;
  /** If true, render as a password input. */
  secret: boolean;
}

export interface BuiltInProviderPreset {
  /**
   * Display name. Doubles as the backend marker that the OAuth
   * dispatch route looks at, so it must match a `_PROVIDERS` key in
   * `external_apps_oauth_api.py`.
   */
  name: string;
  description: string;
  upstream_urls: string[];
  auth_template: Record<string, string>;
  /**
   * Credential fields the admin must enter when configuring this
   * provider (e.g. OAuth client_id and client_secret). Their values
   * become entries in `organization_credentials` on the
   * external_app row.
   */
  required_org_credential_fields: OrgCredentialField[];
  /** Short instructions shown above the credential form. */
  setup_instructions: string;
  logo: IconFunctionComponent;
  /**
   * True if this provider's credentials are acquired via OAuth (so the
   * user-facing page shows a "Connect" button) vs filled in directly.
   */
  oauth: boolean;
}

export const BUILT_IN_PROVIDER_REGISTRY: Record<
  BuiltInProviderKey,
  BuiltInProviderPreset
> = {
  slack: {
    name: "Slack",
    description:
      "Read your Slack messages and channels as context inside Onyx Craft.",
    upstream_urls: ["https://slack\\.com/api/.*"],
    auth_template: {
      Authorization: "Bearer {access_token}",
    },
    required_org_credential_fields: [
      {
        key: "client_id",
        label: "Client ID",
        description:
          "Found under your Slack app's Basic Information → App Credentials.",
        secret: false,
      },
      {
        key: "client_secret",
        label: "Client Secret",
        description:
          "Found under your Slack app's Basic Information → App Credentials. Treat this like a password.",
        secret: true,
      },
    ],
    setup_instructions:
      "Create a Slack app at api.slack.com/apps. Under OAuth & Permissions, add this Onyx " +
      "instance's callback URL (/craft/v1/apps/oauth/callback) to Redirect URLs, and add the " +
      "User Token Scopes you want the agent to use (e.g. chat:write, channels:history, " +
      "channels:read, im:history, users:read). No bot user is required. Then paste the app's " +
      "Client ID and Client Secret below.",
    logo: SvgSlack,
    oauth: true,
  },
  googleCalendar: {
    name: "Google Calendar",
    description:
      "Read and create events on your Google Calendar from inside Onyx Craft.",
    upstream_urls: ["https://www\\.googleapis\\.com/calendar/.*"],
    auth_template: {
      Authorization: "Bearer {access_token}",
    },
    required_org_credential_fields: [
      {
        key: "client_id",
        label: "Client ID",
        description:
          "Found in Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client IDs.",
        secret: false,
      },
      {
        key: "client_secret",
        label: "Client Secret",
        description:
          "Found alongside the Client ID. Treat this like a password.",
        secret: true,
      },
    ],
    setup_instructions:
      "In Google Cloud Console: create a project (or pick one), enable the Google Calendar " +
      "API under APIs & Services → Library, configure the OAuth consent screen (External for " +
      "personal Google accounts, Internal for Workspace), then under APIs & Services → " +
      "Credentials create an OAuth 2.0 Client ID of type Web application. Add this Onyx " +
      "instance's callback URL (/craft/v1/apps/oauth/callback) to Authorized redirect URIs. " +
      "Then paste the Client ID and Client Secret below.",
    logo: SvgCalendar,
    oauth: true,
  },
  linear: {
    name: "Linear",
    description:
      "Read and create issues, projects, and comments in Linear on the user's behalf.",
    upstream_urls: ["https://api\\.linear\\.app/.*"],
    auth_template: {
      Authorization: "Bearer {access_token}",
    },
    required_org_credential_fields: [
      {
        key: "client_id",
        label: "Client ID",
        description:
          "Found in Linear → Settings → API → OAuth applications → your app.",
        secret: false,
      },
      {
        key: "client_secret",
        label: "Client Secret",
        description:
          "Found alongside the Client ID. Treat this like a password.",
        secret: true,
      },
    ],
    setup_instructions:
      "In Linear: Settings → API → OAuth applications → New OAuth application. Fill in name, " +
      "developer email, and description. Add this Onyx instance's callback URL " +
      "(/craft/v1/apps/oauth/callback) to Callback URLs. Save. Then paste the Client ID and " +
      "Client Secret below. The agent will be granted read+write access to issues, projects, " +
      "and comments.",
    logo: SvgLinear,
    oauth: true,
  },
};

// ── API response shapes (kept in sync with backend Pydantic models) ──

export interface ExternalAppAdminResponse {
  id: number;
  name: string;
  description: string;
  upstream_urls: string[];
  auth_template: Record<string, string>;
  organization_credentials: Record<string, string>;
  enabled: boolean;
}

export interface ExternalAppUserResponse {
  id: number;
  name: string;
  description: string;
  credential_keys: string[];
  credential_values: Record<string, string>;
  authenticated: boolean;
}

// ── Helpers ──

export function findAppForProvider(
  apps: ExternalAppAdminResponse[],
  providerKey: BuiltInProviderKey
): ExternalAppAdminResponse | null {
  const preset = BUILT_IN_PROVIDER_REGISTRY[providerKey];
  return apps.find((a) => a.name === preset.name) ?? null;
}

export function findUserAppForProvider(
  apps: ExternalAppUserResponse[],
  providerKey: BuiltInProviderKey
): ExternalAppUserResponse | null {
  const preset = BUILT_IN_PROVIDER_REGISTRY[providerKey];
  return apps.find((a) => a.name === preset.name) ?? null;
}
