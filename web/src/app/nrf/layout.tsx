import { unstable_noStore as noStore } from "next/cache";
import { ProjectsProvider } from "@/providers/ProjectsContext";
import AppSidebar from "@/sections/sidebar/AppSidebar";
import { getCurrentUserSS } from "@/lib/userSS";

export interface LayoutProps {
  children: React.ReactNode;
}

/**
 * NRF Layout - Optional Auth
 *
 * Mirrors the /app/app/ layout but does NOT redirect when unauthenticated.
 * Shows the sidebar only when the user is logged in.
 */
export default async function Layout({ children }: LayoutProps) {
  noStore();

  const user = await getCurrentUserSS();

  return (
    <ProjectsProvider>
      <div className="flex flex-row w-full h-full">
        {user && <AppSidebar />}
        {children}
      </div>
    </ProjectsProvider>
  );
}
