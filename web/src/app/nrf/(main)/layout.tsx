import { unstable_noStore as noStore } from "next/cache";
import AppSidebar from "@/sections/sidebar/AppSidebar";
import { getCurrentUserSS } from "@/lib/userSS";

export interface LayoutProps {
  children: React.ReactNode;
}

/**
 * NRF Main (New Tab) Layout
 *
 * Shows the app sidebar when the user is authenticated.
 * This layout is NOT used by the side-panel route.
 */
export default async function Layout({ children }: LayoutProps) {
  noStore();

  const user = await getCurrentUserSS();

  return (
    <div className="flex flex-row w-full h-full">
      {user && <AppSidebar />}
      {children}
    </div>
  );
}
