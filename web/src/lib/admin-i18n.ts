import { useTranslation } from "react-i18next";
import type { AdminRouteEntry } from "@/lib/admin-routes";

export function adminRouteToI18nKey(path: string): string {
  return path.replace(/^\/admin\//, "").replace(/[/-]/g, "_");
}

/** Page header title — prefers `admin.page_titles.*`, then sidebar route label. */
export function useAdminPageTitle(route: AdminRouteEntry): string {
  const { t } = useTranslation();
  const key = adminRouteToI18nKey(route.path);
  return t(
    `admin.page_titles.${key}`,
    t(`admin.sidebar.routes.${key}`, route.title)
  );
}

export function useAdminSidebarRouteLabel(
  path: string,
  fallback: string
): string {
  const { t } = useTranslation();
  if (fallback === "Upgrade Plan") {
    return t("admin.sidebar.routes.upgrade_plan", fallback);
  }
  const key = adminRouteToI18nKey(path);
  return t(`admin.sidebar.routes.${key}`, fallback);
}
