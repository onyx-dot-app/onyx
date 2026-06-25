import type { TFunction } from "i18next";

// Hook point display name / description / fail-hard text come from the backend
// in English. Map them to localized strings keyed by hook point, falling back
// to the server-provided value for any hook point we don't have a key for.
export function localizeHookField(
  t: TFunction,
  hookPoint: string,
  field: "name" | "desc" | "fail",
  fallback?: string | null
): string {
  return t(`admin.hooks.point_${hookPoint}_${field}`, {
    defaultValue: fallback ?? "",
  });
}
