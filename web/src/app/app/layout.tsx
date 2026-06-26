import { redirect } from "next/navigation";
import type { Metadata } from "next";
import type { Route } from "next";
import { unstable_noStore as noStore } from "next/cache";
import { requireAuth } from "@/lib/auth/requireAuth";
import { ProjectsProvider } from "@/providers/ProjectsContext";
import { VoiceModeProvider } from "@/providers/VoiceModeProvider";
import AppSidebar from "@/sections/sidebar/AppSidebar";
import { RootLayout } from "@opal/layouts";
import AppChrome from "@/layouts/chromes/AppChrome";
import { generateAppNameMetadata } from "@/lib/app/svcSS";

export async function generateMetadata(): Promise<Metadata> {
  return { title: await generateAppNameMetadata() };
}

export interface LayoutProps {
  children: React.ReactNode;
}

export default async function Layout({ children }: LayoutProps) {
  noStore();

  // Only check authentication - data fetching is done client-side via SWR hooks
  const authResult = await requireAuth();

  if (authResult.redirect) {
    redirect(authResult.redirect as Route);
  }

  return (
    <ProjectsProvider>
      {/* VoiceModeProvider wraps the full app layout so TTS playback state
          persists across page navigations (e.g., sidebar clicks during playback).
          It only activates WebSocket connections when TTS is actually triggered. */}
      <VoiceModeProvider>
        <RootLayout.Root>
          <AppSidebar />
          <AppChrome>{children}</AppChrome>
        </RootLayout.Root>
      </VoiceModeProvider>
    </ProjectsProvider>
  );
}
