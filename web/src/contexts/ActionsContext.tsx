"use client";

/**
 * ActionsContext
 *
 * Minimal shared state for assistant tool usage:
 * - `toolMap`: Record<toolId, ToolState>
 * - `setToolStatus(toolId, state)`
 * - `setToolsStatus(toolIds, state)`
 *
 * `ToolState` prioritizes Forced > Disabled > Enabled when mapping.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  useEffect,
} from "react";
import type { ReactNode } from "react";
import useAgentPreferences from "@/hooks/useAgentPreferences";
import { useChatSessionContext } from "@/contexts/ChatSessionContext";

export enum ToolState {
  Enabled = "enabled",
  Disabled = "disabled",
  Forced = "forced",
}

interface ActionsContextValue {
  /** Map of toolId -> ToolState (Forced > Disabled > Enabled). */
  toolMap: Record<number, ToolState>;

  /** Forced tool IDs scoped to the active agent. */
  forcedToolIds: number[];

  /** Set a single tool's state for the current agent. */
  setToolStatus: (toolId: number, state: ToolState) => void;

  /** Set multiple tools' state for the current agent. */
  setToolsStatus: (toolIds: number[], state: ToolState) => void;
}

const ActionsContext = createContext<ActionsContextValue | undefined>(
  undefined
);

interface ActionsProviderProps {
  children: ReactNode;
}

export function ActionsProvider({ children }: ActionsProviderProps) {
  const { agentForCurrentChatSession } = useChatSessionContext();
  const { agentPreferences, setAgentPreference } = useAgentPreferences();

  const agentId = useMemo(
    () => agentForCurrentChatSession?.id ?? null,
    [agentForCurrentChatSession?.id]
  );
  const tools = useMemo(
    () => agentForCurrentChatSession?.tools ?? [],
    [agentForCurrentChatSession?.tools]
  );

  const disabledToolIds = useMemo(
    () => (agentId && agentPreferences?.[agentId]?.disabled_tool_ids) || [],
    [agentId, agentPreferences]
  );

  // Derive toolMap from tools and disabledToolIds - this is the source of truth from the server
  const baseToolMap = useMemo(() => {
    const map: Record<number, ToolState> = {};
    tools.forEach((tool) => {
      if (disabledToolIds.includes(tool.id)) {
        map[tool.id] = ToolState.Disabled;
      } else {
        map[tool.id] = ToolState.Enabled;
      }
    });
    return map;
  }, [tools, disabledToolIds]);

  // Local overrides for user actions (enabled/disabled/forced changes)
  const [localOverrides, setLocalOverrides] = useState<
    Record<number, ToolState>
  >({});

  // Track the previous agent ID to detect actual agent switches
  const [prevAgentId, setPrevAgentId] = useState<number | null>(agentId);

  // Reset local overrides when switching agents to prevent state leakage
  useEffect(() => {
    if (prevAgentId !== agentId) {
      setLocalOverrides({});
      setPrevAgentId(agentId);
    }
  }, [agentId, prevAgentId]);

  // Merge base map with local overrides
  const toolMap = useMemo(() => {
    return { ...baseToolMap, ...localOverrides };
  }, [baseToolMap, localOverrides]);

  function setToolStatus(toolId: number, state: ToolState) {
    setToolsStatus([toolId], state);
  }

  function setToolsStatus(toolIds: number[], state: ToolState) {
    if (toolIds.length === 0) return;

    if (state === ToolState.Forced) {
      const first = toolIds[0]!;
      setLocalOverrides((prev) => {
        const updated = { ...prev };
        Object.keys(toolMap).forEach((key) => {
          const toolId = Number.parseInt(key);
          if (toolId === first) {
            updated[toolId] = ToolState.Forced;
          } else if (prev[toolId] === ToolState.Forced) {
            // Remove the forced override, let it fall back to base
            delete updated[toolId];
          }
        });
        return updated;
      });
    } else {
      setLocalOverrides((prev) => {
        const updated = { ...prev };
        toolIds.forEach((toolId) => {
          if (!(toolId in toolMap)) return;
          updated[toolId] = state;
        });
        return updated;
      });
    }
  }

  const forcedToolIds = useMemo(
    () =>
      Object.entries(toolMap)
        .filter(([toolId, toolState]) => toolState === ToolState.Forced)
        .map(([toolId, _toolState]) => Number.parseInt(toolId)),
    [toolMap]
  );

  // Sync local overrides back to agentPreference
  useEffect(() => {
    if (agentId === null || Object.keys(localOverrides).length === 0) return;

    const updatedDisabledToolIds = Object.entries(toolMap)
      .filter(([_toolId, toolState]) => toolState === ToolState.Disabled)
      .map(([toolId, _toolState]) => Number.parseInt(toolId));

    // Only update if the disabled tools have actually changed
    const currentDisabled = new Set(disabledToolIds);
    const newDisabled = new Set(updatedDisabledToolIds);

    const hasChanged =
      currentDisabled.size !== newDisabled.size ||
      !updatedDisabledToolIds.every((id) => currentDisabled.has(id));

    if (hasChanged) {
      setAgentPreference(agentId, {
        disabled_tool_ids: updatedDisabledToolIds,
      });
    }
  }, [localOverrides, agentId, disabledToolIds, toolMap, setAgentPreference]);

  return (
    <ActionsContext.Provider
      value={{
        toolMap,
        forcedToolIds,
        setToolStatus,
        setToolsStatus,
      }}
    >
      {children}
    </ActionsContext.Provider>
  );
}

export function useActionsContext() {
  const ctx = useContext(ActionsContext);
  if (!ctx) {
    throw new Error("useActionsContext must be used within an ActionsProvider");
  }
  return ctx;
}
