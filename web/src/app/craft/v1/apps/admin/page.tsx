import { redirect } from "next/navigation";
import type { Route } from "next";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

export default function ExternalAppsAdminRedirect() {
  redirect(ADMIN_ROUTES.CRAFT_APPS.path as Route);
}
