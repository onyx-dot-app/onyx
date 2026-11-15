import { redirect } from "@opal/navigation";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

export default function ManageAppsPage() {
  redirect(ADMIN_ROUTES.CRAFT_APPS.path);
}
