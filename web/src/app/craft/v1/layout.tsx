"use client";

import { BuildProvider } from "@/app/craft/contexts/BuildContext";
import { BuildOnboardingProvider } from "@/app/craft/onboarding/BuildOnboardingProvider";
import BuildSidebar from "@/app/craft/components/SideBar";
// hljs theme for fenced code blocks rendered by the shared CodeBlock (via
// MinimalMarkdown). CodeBlock expects this CSS to be present; we load it from
// the craft layout so it's reliably themed on /craft without importing it
// eagerly elsewhere or editing any component outside /craft.
import "@/app/app/message/custom-code-styles.css";

/**
 * Build V1 Layout - Skeleton pattern with 3-panel layout
 *
 * Wraps with BuildProvider. ChatPanel owns its upload draft.
 * Includes BuildSidebar on the left.
 * Pre-provisioning is handled by useBuildSessionController.
 * The page component provides the center (chat) and right (output) panels.
 */
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <BuildProvider>
      <BuildOnboardingProvider>
        <div className="flex h-full min-h-0 w-full flex-row overflow-hidden contain-layout">
          <BuildSidebar />
          {children}
        </div>
      </BuildOnboardingProvider>
    </BuildProvider>
  );
}
