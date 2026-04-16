import { redirect } from "next/navigation";
import type { Route } from "next";
import { unstable_noStore as noStore } from "next/cache";
import { requireAuth } from "@/lib/auth/requireAuth";
import { ProjectsProvider } from "@/providers/ProjectsContext";
import { VoiceModeProvider } from "@/providers/VoiceModeProvider";

export const metadata = {
  title: "Tutor | Onyx",
  description: "AI Tutor powered by Onyx",
};

interface LayoutProps {
  children: React.ReactNode;
}

/**
 * Minimal layout for the /tutor route.
 *
 * No sidebar, no navbar, no app shell chrome. Designed to work
 * inside a Canvas LMS iframe (via LTI launch) or as a standalone page.
 * Provides ProjectsProvider for file upload / project scoping and
 * VoiceModeProvider because AppInputBar depends on it.
 */
export default async function TutorLayout({ children }: LayoutProps) {
  noStore();

  const authResult = await requireAuth();

  if (authResult.redirect) {
    redirect(authResult.redirect as Route);
  }

  return (
    <ProjectsProvider>
      <VoiceModeProvider>
        <div className="h-screen w-screen overflow-hidden">{children}</div>
      </VoiceModeProvider>
    </ProjectsProvider>
  );
}
