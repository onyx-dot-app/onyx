import { redirect } from "next/navigation";
import type { Route } from "next";
import { unstable_noStore as noStore } from "next/cache";
import { requireAuth } from "@/lib/auth/requireAuth";
import { ProjectsProvider } from "@/providers/ProjectsContext";
import { VoiceModeProvider } from "@/providers/VoiceModeProvider";
import AppSidebar from "@/sections/sidebar/AppSidebar";

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
        <div className="flex flex-row w-full h-full">
          <AppSidebar />
          {/* `ob-content-bg` paints the grid + radial-glow only in
              the main-content column — the sidebar stays plain white
              per the design. The class itself lives in globals.css
              and uses ::before / ::after pseudo-elements so the
              backdrop sits behind the children of this wrapper. */}
          <div className="ob-content-bg flex-1 min-w-0 relative">
            {children}
          </div>
        </div>
      </VoiceModeProvider>
    </ProjectsProvider>
  );
}
