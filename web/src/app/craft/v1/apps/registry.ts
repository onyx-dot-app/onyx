import {
  SvgSlack,
  SvgLinear,
  SvgGmail,
  SvgGitHub,
  SvgGoogleCalendar,
  SvgGoogleDrive,
  SvgHubSpot,
  SvgNotion,
  SvgZendesk,
} from "@opal/logos";
import { SvgPlug } from "@opal/icons";
import { IconFunctionComponent } from "@opal/types";

// Mirrors `onyx.db.enums.ExternalAppType` on the backend.
export const EXTERNAL_APP_TYPES = [
  "SLACK",
  "GOOGLE_CALENDAR",
  "GOOGLE_DRIVE",
  "GMAIL",
  "LINEAR",
  "GITHUB",
  "HUBSPOT",
  "NOTION",
  "ZENDESK",
  "CUSTOM",
] as const;

export type ExternalAppType = (typeof EXTERNAL_APP_TYPES)[number];

const _BUILT_IN_LOGOS: Partial<Record<ExternalAppType, IconFunctionComponent>> =
  {
    SLACK: SvgSlack,
    GOOGLE_CALENDAR: SvgGoogleCalendar,
    GOOGLE_DRIVE: SvgGoogleDrive,
    GMAIL: SvgGmail,
    LINEAR: SvgLinear,
    GITHUB: SvgGitHub,
    HUBSPOT: SvgHubSpot,
    NOTION: SvgNotion,
    ZENDESK: SvgZendesk,
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

// Mirrors `onyx.db.enums.ActionPolicy` on the backend.
export type ActionPolicy = "ALWAYS" | "ASK" | "DENY";
