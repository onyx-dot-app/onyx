import {
  SvgSlack,
  SvgLinear,
  SvgGmail,
  SvgGithub,
  SvgGoogleCalendar,
  SvgGoogleDrive,
  SvgHubspot,
} from "@opal/logos";
import { SvgPlug } from "@opal/icons";
import { IconFunctionComponent } from "@opal/types";

// Mirrors `onyx.db.enums.ExternalAppType` on the backend.
export type ExternalAppType =
  | "SLACK"
  | "GOOGLE_CALENDAR"
  | "GOOGLE_DRIVE"
  | "GMAIL"
  | "LINEAR"
  | "GITHUB"
  | "HUBSPOT"
  | "CUSTOM";

const _BUILT_IN_LOGOS: Partial<Record<ExternalAppType, IconFunctionComponent>> =
  {
    SLACK: SvgSlack,
    GOOGLE_CALENDAR: SvgGoogleCalendar,
    GOOGLE_DRIVE: SvgGoogleDrive,
    GMAIL: SvgGmail,
    LINEAR: SvgLinear,
    GITHUB: SvgGithub,
    HUBSPOT: SvgHubspot,
  };

/** Logo for a known `app_type`, with a generic fallback for CUSTOM /
 * unknown types so the UI never breaks on a new backend provider the
 * frontend hasn't been redeployed for. */
export function getAppTypeLogo(
  app_type: ExternalAppType
): IconFunctionComponent {
  return _BUILT_IN_LOGOS[app_type] ?? SvgPlug;
}

// Keep in sync with backend Pydantic models in
// `server/features/build/external_apps/models.py`.

export interface OrgCredentialFieldDescriptor {
  key: string;
  label: string;
  description: string;
  secret: boolean;
}

// Mirrors `onyx.db.enums.EndpointPolicy` on the backend.
export type EndpointPolicy = "ALWAYS" | "ASK" | "DENY";

export interface EndpointDescriptor {
  action_id: string;
  normalised_name: string;
  description: string;
  // Policy a newly-created app seeds this action's selector with (admin can
  // override). Mirrors `EndpointSpec.default_policy` on the backend.
  default_policy: EndpointPolicy;
}

export interface ActionPolicyView {
  action_id: string;
  normalised_name: string;
  description: string;
  state: EndpointPolicy;
}

export interface BuiltInExternalAppDescriptor {
  app_type: ExternalAppType;
  name: string;
  description: string;
  upstream_url_patterns: string[];
  auth_template: Record<string, string>;
  required_org_credential_fields: OrgCredentialFieldDescriptor[];
  setup_instructions: string;
  actions: EndpointDescriptor[];
}

export interface ExternalAppAdminResponse {
  id: number;
  name: string;
  description: string;
  app_type: ExternalAppType;
  upstream_url_patterns: string[];
  auth_template: Record<string, string>;
  organization_credentials: Record<string, string>;
  enabled: boolean;
  actions: ActionPolicyView[];
  // Onyx-managed built-in (cloud): creds/config Onyx-owned and blanked here; the
  // admin may only enable/disable + set policies (the UI hides the rest).
  is_onyx_managed: boolean;
}

export interface ExternalAppUserResponse {
  id: number;
  name: string;
  description: string;
  slug: string;
  app_type: ExternalAppType;
  credential_keys: string[];
  credential_values: Record<string, string>;
  authenticated: boolean;
  // OAuth apps connect via a popup; others via the credential form.
  supports_oauth: boolean;
}

/**
 * Built-in descriptors still available to add. Only one app per `app_type` is
 * allowed (server-enforced via the built-in skill's unique slug), so configured
 * types are dropped to avoid a duplicate-resource error. Cloud managed built-ins
 * are pre-provisioned (always configured) and never show here. CUSTOM apps have
 * no descriptor, so they never match and are left untouched.
 */
export function availableBuiltInDescriptors(
  descriptors: BuiltInExternalAppDescriptor[],
  configuredApps: ExternalAppAdminResponse[]
): BuiltInExternalAppDescriptor[] {
  const configuredAppTypes = new Set(configuredApps.map((app) => app.app_type));
  return descriptors.filter((d) => !configuredAppTypes.has(d.app_type));
}
