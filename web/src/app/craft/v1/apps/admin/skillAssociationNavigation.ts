import type { Route } from "next";
import type { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";

interface ExternalAppContext {
  externalAppId?: number;
  externalAppName?: string;
}

interface ExternalAppSearchParams {
  externalAppId?: string | string[];
  externalAppName?: string | string[];
}

function externalAppParams(app: ExternalAppAdminResponse): URLSearchParams {
  return new URLSearchParams({
    externalAppId: String(app.id),
    externalAppName: app.name,
  });
}

export function externalAppContextFromSearchParams({
  externalAppId,
  externalAppName,
}: ExternalAppSearchParams): ExternalAppContext {
  const parsedAppId =
    typeof externalAppId === "string" ? Number(externalAppId) : undefined;
  return {
    ...(Number.isInteger(parsedAppId) &&
    parsedAppId !== undefined &&
    parsedAppId > 0
      ? { externalAppId: parsedAppId }
      : {}),
    ...(typeof externalAppName === "string" ? { externalAppName } : {}),
  };
}

export function externalAppAdminUrl(externalAppId: number): Route {
  return `/admin/craft/apps?editAppId=${externalAppId}` as Route;
}

export function skillEditorUrlForApp(
  app: ExternalAppAdminResponse,
  draftId?: string
): Route {
  const params = externalAppParams(app);
  if (draftId) params.set("draft", draftId);
  return `/craft/v1/skills/new?${params.toString()}` as Route;
}

export function skillEditUrlForApp(
  skillId: string,
  app: ExternalAppAdminResponse
): Route {
  return `/craft/v1/skills/edit/${skillId}?${externalAppParams(app).toString()}` as Route;
}
