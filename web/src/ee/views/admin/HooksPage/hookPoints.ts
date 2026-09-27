import type { useTranslations } from "next-intl";
import type { HookPointMeta } from "@/ee/views/admin/HooksPage/interfaces";

export type HooksTranslate = ReturnType<typeof useTranslations<"admin.hooks">>;

// Backend hook_point ids and their "admin.hooks.points" catalog entries. An id
// this build does not know (a newer backend) falls back to the API's English.
const HOOK_POINT_KEYS = {
  document_ingestion: "documentIngestion",
  document_push: "documentPush",
  query_processing: "queryProcessing",
} as const;

type HookPointKey = (typeof HOOK_POINT_KEYS)[keyof typeof HOOK_POINT_KEYS];

function hookPointKey(hookPoint: string): HookPointKey | undefined {
  if (!Object.prototype.hasOwnProperty.call(HOOK_POINT_KEYS, hookPoint)) {
    return undefined;
  }
  // SAFETY: the own-property check above proves hookPoint is a key of the map.
  return HOOK_POINT_KEYS[hookPoint as keyof typeof HOOK_POINT_KEYS];
}

export function hookPointName(
  spec: Pick<HookPointMeta, "hook_point" | "display_name">,
  t: HooksTranslate
): string {
  const key = hookPointKey(spec.hook_point);
  return key ? t(`points.${key}.name`) : spec.display_name;
}

export function hookPointDescription(
  spec: Pick<HookPointMeta, "hook_point" | "description">,
  t: HooksTranslate
): string {
  const key = hookPointKey(spec.hook_point);
  return key ? t(`points.${key}.description`) : spec.description;
}
