import { ProjectsProvider } from "@/lib/projects/providers";
import { VoiceModeProvider } from "@/providers/VoiceModeProvider";
import RequiredIntegrationGate from "@/sections/integrations/RequiredIntegrationGate";

export interface LayoutProps {
  children: React.ReactNode;
}

/**
 * NRF Root Layout - Shared by all NRF routes
 *
 * Provides ProjectsProvider (needed by NRFPage) without auth redirect.
 * Sidebar and chrome are handled by sub-layouts / individual pages.
 */
export default function Layout({ children }: LayoutProps) {
  return (
    <ProjectsProvider>
      <VoiceModeProvider>
        {children}
        <RequiredIntegrationGate />
      </VoiceModeProvider>
    </ProjectsProvider>
  );
}
