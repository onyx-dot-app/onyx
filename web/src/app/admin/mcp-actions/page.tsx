import { redirect } from "next/navigation";
import {
  legacyMcpListHref,
  type PluginSearchParams,
} from "@/lib/plugins/routes";

export default async function Page({
  searchParams,
}: {
  searchParams: Promise<PluginSearchParams>;
}) {
  redirect(legacyMcpListHref(await searchParams));
}
