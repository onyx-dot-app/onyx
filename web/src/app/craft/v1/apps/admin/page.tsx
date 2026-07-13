import { redirect } from "next/navigation";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

// Old admin apps path; management now lives in the admin panel's Craft section.
export default function ExternalAppsAdminRedirect() {
  redirect(ADMIN_ROUTES.CRAFT_APPS.path);
}
