import { redirect } from "@opal/navigation";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

/** An old plugin or action URL. Its id is not an integration id, so it opens
 * the integration list. */
export default function Page() {
  redirect(ADMIN_ROUTES.INTEGRATIONS.path);
}
