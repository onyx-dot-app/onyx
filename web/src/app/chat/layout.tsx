import { redirect } from "next/navigation";
import { unstable_noStore as noStore } from "next/cache";
import { requireAuth } from "@/lib/auth/requireAuth";
import { ProjectsProvider } from "./projects/ProjectsContext";
import AvatarProviderWrapper from "./avatars/AvatarProviderWrapper";
import AppSidebar from "@/sections/sidebar/AppSidebar";

export interface LayoutProps {
  children: React.ReactNode;
}

export default async function Layout({ children }: LayoutProps) {
  noStore();

  // Only check authentication - data fetching is done client-side via SWR hooks
  const authResult = await requireAuth();

  if (authResult.redirect) {
    redirect(authResult.redirect);
  }

  return (
    <ProjectsProvider>
      <AvatarProviderWrapper>
        <div className="flex flex-row w-full h-full">
          <AppSidebar />
          {children}
        </div>
      </AvatarProviderWrapper>
    </ProjectsProvider>
  );
}
