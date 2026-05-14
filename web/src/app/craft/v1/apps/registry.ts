import { SvgSlack, SvgLinear } from "@opal/logos";
import { SvgCalendar, SvgPlug } from "@opal/icons";
import { IconFunctionComponent } from "@opal/types";

// Mirrors `onyx.db.enums.ExternalAppType` on the backend.
export type ExternalAppType = "SLACK" | "GOOGLE_CALENDAR" | "LINEAR" | "CUSTOM";

const _BUILT_IN_LOGOS: Partial<Record<ExternalAppType, IconFunctionComponent>> =
  {
    SLACK: SvgSlack,
    GOOGLE_CALENDAR: SvgCalendar,
    LINEAR: SvgLinear,
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

export interface BuiltInExternalAppDescriptor {
  app_type: ExternalAppType;
  name: string;
  description: string;
  upstream_url_patterns: string[];
  auth_template: Record<string, string>;
  required_org_credential_fields: OrgCredentialFieldDescriptor[];
  setup_instructions: string;
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
}

export interface ExternalAppUserResponse {
  id: number;
  name: string;
  description: string;
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
