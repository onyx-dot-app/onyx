import { redirect } from "next/navigation";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  withPluginSearchParams,
  type PluginSearchParams,
} from "@/lib/plugins/routes";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<PluginSearchParams>;
}) {
  redirect(
    withPluginSearchParams(
      ADMIN_ROUTES.PLUGINS.path,
      await searchParams,
      "add=mcp"
    )
  );
}
