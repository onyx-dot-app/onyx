import { redirect } from "@opal/navigation";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

export default function ExternalAppsAdminRedirect() {
  redirect(ADMIN_ROUTES.CRAFT_APPS.path);
}
