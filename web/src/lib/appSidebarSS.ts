import { cookies } from "next/headers";
import { SIDEBAR_TOGGLED_COOKIE_NAME } from "@/components/resizable/constants";
import { User } from "@/lib/types";

export interface AppSidebarMetadata {
  folded: boolean;
}

export async function fetchAppSidebarMetadata(
  user?: User | null
): Promise<AppSidebarMetadata> {
  const requestCookies = await cookies();
  const sidebarToggled = requestCookies.get(SIDEBAR_TOGGLED_COOKIE_NAME);

  const folded = !user?.is_anonymous_user && sidebarToggled?.value === "true";

  return {
    folded,
  };
}
