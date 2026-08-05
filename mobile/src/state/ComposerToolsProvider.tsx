// State lives in a hook, not the provider: ChatSurface both hosts the provider and calls
// `resolveToolOptions()` at send time, and a component can't read a context it provides.
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { useWorkspaceSettings } from "@/api/settings";
import type { ChatToolOptions } from "@/api/chat/stream";
import type { MinimalAgent } from "@/chat/agents";
import {
  computeAllowedToolIds,
  displayableTools,
  hasSearchToolsAvailable,
  type ToolSnapshot,
} from "@/chat/tools";
import { useAgentPreferences } from "@/hooks/useAgentPreferences";
import { useDeepResearchToggle } from "@/hooks/useDeepResearchToggle";
import { useForcedTools } from "@/hooks/useForcedTools";

const NO_TOOLS: ToolSnapshot[] = [];
const NO_IDS: number[] = [];

export interface ComposerTools {
  showDeepResearch: boolean;
  deepResearchEnabled: boolean;
  toggleDeepResearch: () => void;
  // Filtered for display — not the agent's full tool list.
  actionTools: ToolSnapshot[];
  forcedToolId: number | null;
  toggleForcedTool: (toolId: number) => void;
  disabledToolIds: number[];
  toggleToolEnabled: (toolId: number) => void;
  // Report the agent a send used, once that send is known to have created the session. Carries
  // the agent rather than a flag because the selection can change while the create is in flight.
  notePendingSend: (agentForSend: MinimalAgent | null) => void;
  // Read at send time, never during render.
  resolveToolOptions: () => ChatToolOptions;
}

interface ComposerToolsInputs {
  chatSessionId: string | null;
  // null when ChatSurface can't prove which agent owns the conversation.
  agent: MinimalAgent | null;
  // Deep research is unsupported in projects (web hides it too — ENG-3818). Only the project
  // landing composer is detectable: a chat opened from a project has no project id on the wire.
  isProjectWorkflow: boolean;
  // Crossing this boundary releases a forced tool.
  projectId: number | null;
}

export function useComposerToolsState({
  chatSessionId,
  agent,
  isProjectWorkflow,
  projectId,
}: ComposerToolsInputs): ComposerTools {
  const { settings } = useWorkspaceSettings();
  const agentId = agent?.id;

  const { deepResearchEnabled, toggleDeepResearch } = useDeepResearchToggle({
    chatSessionId,
    agentId,
  });
  const { forcedToolId, toggleForcedTool, clearForcedTool } = useForcedTools({
    chatSessionId,
    agentId,
    projectId,
  });
  const { disabledToolIdsFor, toggleDisabledTool } = useAgentPreferences();

  /*
   * `agent` goes null for a beat after a send, before the new session reaches the sessions list.
   * Only our knowledge lapses, not the agent, so hold the last one — otherwise the menu vanishes
   * and the send re-allows tools the user switched off.
   *
   * The hold is stamped with the conversation it belongs to and is only honoured back in that
   * same conversation, so it can never describe a chat it was not captured in. It carries over to
   * a new session only when the host reports the send that created it, and then takes that send's
   * agent — picking a different agent while the create was in flight must not rewrite what the
   * finished session runs on. Adjusted during render, not in an effect, so the hold is right on
   * the first render that loses the agent; compared by id so a caller that rebuilds the object
   * each render can't loop.
   */
  const [pendingSend, setPendingSend] = useState<{
    agent: MinimalAgent | null;
  } | null>(null);
  const [held, setHeld] = useState<{
    agent: MinimalAgent | null;
    sessionId: string | null;
  }>({ agent, sessionId: chatSessionId });
  if (
    agent &&
    (held.agent?.id !== agent.id || held.sessionId !== chatSessionId)
  ) {
    setHeld({ agent, sessionId: chatSessionId });
  } else if (
    !agent &&
    pendingSend &&
    held.sessionId === null &&
    chatSessionId !== null
  ) {
    setHeld({ agent: pendingSend.agent, sessionId: chatSessionId });
    setPendingSend(null);
  }
  const effectiveAgent =
    agent ?? (held.sessionId === chatSessionId ? held.agent : null);
  const effectiveAgentId = effectiveAgent?.id;

  // No agent has ever resolved → leave the pill as the user set it rather than withdrawing a
  // control they just used.
  const canSearch = effectiveAgent
    ? hasSearchToolsAvailable(effectiveAgent.tools)
    : deepResearchEnabled;
  const showDeepResearch =
    !isProjectWorkflow && settings.deep_research_enabled && canSearch;

  const actionTools = useMemo(
    () => (effectiveAgent ? displayableTools(effectiveAgent.tools) : NO_TOOLS),
    [effectiveAgent],
  );

  const disabledToolIds = useMemo(
    () =>
      effectiveAgentId == null ? NO_IDS : disabledToolIdsFor(effectiveAgentId),
    [effectiveAgentId, disabledToolIdsFor],
  );

  const toggleToolEnabled = useCallback(
    (toolId: number) => {
      const agentId = effectiveAgentId;
      if (agentId == null) return;
      // The backend kills the turn when a forced tool isn't among the constructed ones
      // ("Forced tool … not found in tools"), so disabling it must release the force.
      if (!disabledToolIds.includes(toolId) && forcedToolId === toolId) {
        clearForcedTool();
      }
      void toggleDisabledTool(agentId, toolId);
    },
    [
      effectiveAgentId,
      clearForcedTool,
      disabledToolIds,
      forcedToolId,
      toggleDisabledTool,
    ],
  );

  const notePendingSend = useCallback(
    (agentForSend: MinimalAgent | null) =>
      setPendingSend({ agent: agentForSend }),
    [],
  );

  return useMemo(
    () => ({
      showDeepResearch,
      deepResearchEnabled,
      toggleDeepResearch,
      actionTools,
      forcedToolId,
      toggleForcedTool,
      disabledToolIds,
      toggleToolEnabled,
      notePendingSend,
      // Gated on `showDeepResearch` so a hidden control can never send `true` — e.g. the admin
      // disabled deep research while a toggle was left on.
      resolveToolOptions: () => {
        // The FULL tool list, not the displayed rows: omitting the ones the menu hides (File
        // Reader, MCP) strips them server-side as soon as any tool is off.
        const allowedToolIds = effectiveAgent
          ? computeAllowedToolIds(effectiveAgent.tools, disabledToolIds)
          : null;
        // A forced id the request filters out, or that belongs to another agent, fails the turn
        // mid-stream.
        const forcedIsSendable =
          forcedToolId != null &&
          !disabledToolIds.includes(forcedToolId) &&
          (effectiveAgent?.tools.some((tool) => tool.id === forcedToolId) ??
            false);

        return {
          deepResearch: showDeepResearch && deepResearchEnabled,
          allowedToolIds,
          forcedToolId: forcedIsSendable ? forcedToolId : null,
          internalSearchFilters: null,
        };
      },
    }),
    [
      effectiveAgent,
      showDeepResearch,
      deepResearchEnabled,
      toggleDeepResearch,
      actionTools,
      forcedToolId,
      toggleForcedTool,
      disabledToolIds,
      toggleToolEnabled,
      notePendingSend,
    ],
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
