import { redirect } from "next/navigation";
import type { Route } from "next";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

export default function Page() {
  redirect(ADMIN_ROUTES.CRAFT_ACCESS.path as Route);
}
