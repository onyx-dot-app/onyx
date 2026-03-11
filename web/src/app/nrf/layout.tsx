import { ProjectsProvider } from "@/providers/ProjectsContext";

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
  return <ProjectsProvider>{children}</ProjectsProvider>;
}
