// The state lives in a hook rather than inside the provider because ChatSurface both hosts the
// provider and calls `resolveToolOptions()` at send time — a component can't read a context it
// provides.
import { createContext, useContext, useMemo, type ReactNode } from "react";

import { useWorkspaceSettings } from "@/api/settings";
import type { ChatToolOptions } from "@/api/chat/stream";
import type { MinimalAgent } from "@/chat/agents";
import { hasSearchToolsAvailable } from "@/chat/tools";
import { useDeepResearchToggle } from "@/hooks/useDeepResearchToggle";

export interface ComposerTools {
  showDeepResearch: boolean;
  deepResearchEnabled: boolean;
  toggleDeepResearch: () => void;
  // Read at send time, never during render.
  resolveToolOptions: () => ChatToolOptions;
}

interface ComposerToolsInputs {
  chatSessionId: string | null;
  // null while the conversation's agent isn't knowable yet.
  agent: MinimalAgent | null;
  // Deep research is unsupported in projects (web hides it too — ENG-3818). Only the project
  // landing composer is detectable: a chat opened from a project has no project id on the wire.
  isProjectWorkflow: boolean;
}

export function useComposerToolsState({
  chatSessionId,
  agent,
  isProjectWorkflow,
}: ComposerToolsInputs): ComposerTools {
  const { settings } = useWorkspaceSettings();
  const { deepResearchEnabled, toggleDeepResearch } = useDeepResearchToggle({
    chatSessionId,
    agentId: agent?.id,
  });

  // Agent unknown → hold the pill as the user left it. Re-gating on the placeholder agent would
  // either withdraw a control the user just used or offer deep research to an agent that can't
  // search.
  const canSearch = agent
    ? hasSearchToolsAvailable(agent.tools)
    : deepResearchEnabled;
  const showDeepResearch =
    !isProjectWorkflow && settings.deep_research_enabled && canSearch;

  return useMemo(
    () => ({
      showDeepResearch,
      deepResearchEnabled,
      toggleDeepResearch,
      // Gated on `showDeepResearch` so a hidden control can never send `true` — e.g. the admin
      // disabled deep research while a toggle was left on.
      resolveToolOptions: () => ({
        deepResearch: showDeepResearch && deepResearchEnabled,
        allowedToolIds: null,
        forcedToolId: null,
        internalSearchFilters: null,
      }),
    }),
    [showDeepResearch, deepResearchEnabled, toggleDeepResearch],
  );
}

const ComposerToolsContext = createContext<ComposerTools | undefined>(
  undefined,
);

interface ComposerToolsProviderProps {
  value: ComposerTools;
  children: ReactNode;
}

export function ComposerToolsProvider({
  value,
  children,
}: ComposerToolsProviderProps) {
  return (
    <ComposerToolsContext.Provider value={value}>
      {children}
    </ComposerToolsContext.Provider>
  );
}

export function useComposerTools(): ComposerTools {
  const tools = useContext(ComposerToolsContext);
  if (!tools) {
    throw new Error(
      "useComposerTools must be used within a ComposerToolsProvider",
    );
  }
  return tools;
}
