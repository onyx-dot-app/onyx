/**
 * Built-in external-app provider registry. Each entry is the preset
 * the admin POSTs to the backend when enabling a built-in provider —
 * frontend-owned so admins don't have to type out auth_template
 * details a typical user can't be expected to know.
 */

import { SvgSlack, SvgLinear } from "@opal/logos";
import { SvgCalendar } from "@opal/icons";
import { IconFunctionComponent } from "@opal/types";

export type BuiltInProviderKey = "slack" | "googleCalendar" | "linear";

// Mirrors `onyx.db.enums.ExternalAppType` on the backend.
export type ExternalAppType = "SLACK" | "GOOGLE_CALENDAR" | "LINEAR" | "CUSTOM";

export interface OrgCredentialField {
  key: string;
  label: string;
  description: string;
  /** Renders as a password input when true. */
  secret: boolean;
}

export interface BuiltInProviderPreset {
  /** Must match the backend `OAuth.app_name` so dispatch lines up. */
  name: string;
  /** Discriminator the backend keys OAuth dispatch off. */
  app_type: ExternalAppType;
  description: string;
  upstream_url_patterns: string[];
  auth_template: Record<string, string>;
  required_org_credential_fields: OrgCredentialField[];
  setup_instructions: string;
  logo: IconFunctionComponent;
  /** True if connection is via OAuth (vs static-token entry). */
  oauth: boolean;
}

export const BUILT_IN_PROVIDER_REGISTRY: Record<
  BuiltInProviderKey,
  BuiltInProviderPreset
> = {
  slack: {
    name: "Slack",
    app_type: "SLACK",
    description:
      "Read your Slack messages and channels as context inside Onyx Craft.",
    upstream_url_patterns: ["https://slack\\.com/api/.*"],
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
    app_type: "GOOGLE_CALENDAR",
    description:
      "Read and create events on your Google Calendar from inside Onyx Craft.",
    upstream_url_patterns: ["https://www\\.googleapis\\.com/calendar/.*"],
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
    app_type: "LINEAR",
    description:
      "Read and create issues, projects, and comments in Linear on the user's behalf.",
    upstream_url_patterns: ["https://api\\.linear\\.app/.*"],
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

// Keep in sync with backend Pydantic models in
// `server/features/build/api/models.py`.

export interface ExternalAppAdminResponse {
  id: number;
  name: string;
  description: string;
  app_type: ExternalAppType;
  upstream_url_patterns: string[];
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

export function findAppForProvider(
  apps: ExternalAppAdminResponse[],
  providerKey: BuiltInProviderKey
): ExternalAppAdminResponse | null {
  const preset = BUILT_IN_PROVIDER_REGISTRY[providerKey];
  return apps.find((a) => a.app_type === preset.app_type) ?? null;
}

export function findUserAppForProvider(
  apps: ExternalAppUserResponse[],
  providerKey: BuiltInProviderKey
): ExternalAppUserResponse | null {
  const preset = BUILT_IN_PROVIDER_REGISTRY[providerKey];
  return apps.find((a) => a.name === preset.name) ?? null;
}
