import { redirect } from "next/navigation";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

// Org app configuration moved to the admin panel's Craft section.
export default function ManageAppsPage() {
  redirect(ADMIN_ROUTES.CRAFT_APPS.path);
}
