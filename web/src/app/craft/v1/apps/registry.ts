import { SvgSlack, SvgLinear, SvgGmail, SvgGithub } from "@opal/logos";
import { SvgCalendar, SvgPlug } from "@opal/icons";
import { IconFunctionComponent } from "@opal/types";

// Mirrors `onyx.db.enums.ExternalAppType` on the backend.
export type ExternalAppType =
  | "SLACK"
  | "GOOGLE_CALENDAR"
  | "GMAIL"
  | "LINEAR"
  | "GITHUB"
  | "CUSTOM";

const _BUILT_IN_LOGOS: Partial<Record<ExternalAppType, IconFunctionComponent>> =
  {
    SLACK: SvgSlack,
    GOOGLE_CALENDAR: SvgCalendar,
    GMAIL: SvgGmail,
    LINEAR: SvgLinear,
    GITHUB: SvgGithub,
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
// `server/features/build/api/models.py`.

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
  // True for Onyx-managed built-in apps (cloud): credentials + gateway config
  // are owned by Onyx (and blanked in this response). The admin may only
  // enable/disable and set policies — not edit credentials/config or delete.
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
}

export function findAppForType(
  apps: ExternalAppAdminResponse[],
  app_type: ExternalAppType
): ExternalAppAdminResponse | null {
  return apps.find((a) => a.app_type === app_type) ?? null;
}

export function findUserAppByName(
  apps: ExternalAppUserResponse[],
  name: string
): ExternalAppUserResponse | null {
  return apps.find((a) => a.name === name) ?? null;
}
