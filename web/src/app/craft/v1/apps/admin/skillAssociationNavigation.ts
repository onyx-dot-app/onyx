import type { Route } from "next";
import type { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";

export function skillEditorUrlForApp(
  app: ExternalAppAdminResponse,
  draftId?: string
): Route {
  const params = new URLSearchParams({
    externalAppId: String(app.id),
    externalAppName: app.name,
  });
  if (draftId) params.set("draft", draftId);
  return `/craft/v1/skills/new?${params.toString()}` as Route;
}

export function skillEditUrlForApp(
  skillId: string,
  app: ExternalAppAdminResponse
): Route {
  const params = new URLSearchParams({
    externalAppId: String(app.id),
    externalAppName: app.name,
  });
  return `/craft/v1/skills/edit/${skillId}?${params.toString()}` as Route;
}
