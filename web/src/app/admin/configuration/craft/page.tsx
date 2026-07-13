import { redirect } from "next/navigation";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

// Craft administration moved into its own sidebar section.
export default function Page() {
  redirect(ADMIN_ROUTES.CRAFT_ACCESS.path);
}
