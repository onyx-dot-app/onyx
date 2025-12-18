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
import { useChatSessionContext } from "./ChatSessionContext";

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

  /** Override forced tool selection for the current agent. */
  setForcedToolIds: (toolIds: number[]) => void;
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

  const agentId = agentForCurrentChatSession?.id;
  const tools = agentForCurrentChatSession?.tools ?? [];

  const [forcedToolIds, setForcedToolIdsState] = useState<number[]>([]);

  const disabledToolIds =
    (agentId && agentPreferences?.[agentId]?.disabled_tool_ids) || [];

  // Keep forcedToolIds cleared when agent changes
  useEffect(() => {
    setForcedToolIdsState([]);
  }, [agentId]);

  const updateDisabledTools = useCallback(
    (updater: (current: number[]) => number[]) => {
      if (!agentId) return;
      const next = updater(disabledToolIds);
      setAgentPreference(agentId, {
        disabled_tool_ids: next,
      });
    },
    [agentId, disabledToolIds, setAgentPreference]
  );

  const setForcedToolIds = useCallback(
    (toolIds: number[]) => {
      const forcedId = toolIds.length > 0 ? toolIds[0] : null;
      const next = forcedId != null ? [forcedId] : [];
      setForcedToolIdsState(next);
      if (!agentId) return;
      if (forcedId != null) {
        updateDisabledTools((current) =>
          current.filter((id) => id !== forcedId)
        );
      }
    },
    [agentId, updateDisabledTools]
  );

  const setToolStatus = useCallback(
    (toolId: number, state: ToolState) => {
      if (!agentId) return;
      if (state === ToolState.Forced) {
        setForcedToolIds([toolId]);
        return;
      }

      const nextForced = forcedToolIds.filter((id) => id !== toolId);
      if (nextForced.length !== forcedToolIds.length) {
        setForcedToolIdsState(nextForced);
      }

      if (state === ToolState.Disabled) {
        updateDisabledTools((current) =>
          current.includes(toolId) ? current : [...current, toolId]
        );
      } else {
        updateDisabledTools((current) => current.filter((id) => id !== toolId));
      }
    },
    [agentId, forcedToolIds, setForcedToolIds, updateDisabledTools]
  );

  const setToolsStatus = useCallback(
    (toolIds: number[], state: ToolState) => {
      if (!agentId) return;
      if (state === ToolState.Forced) {
        setForcedToolIds(toolIds);
        updateDisabledTools((current) =>
          current.filter((id) => !toolIds.includes(id))
        );
        return;
      }

      const nextForced = forcedToolIds.filter((id) => !toolIds.includes(id));
      if (nextForced.length !== forcedToolIds.length) {
        setForcedToolIdsState(nextForced);
      }

      if (state === ToolState.Disabled) {
        updateDisabledTools((current) => {
          const merged = new Set([...current, ...toolIds]);
          return Array.from(merged);
        });
      } else {
        updateDisabledTools((current) =>
          current.filter((id) => !toolIds.includes(id))
        );
      }
    },
    [agentId, forcedToolIds, setForcedToolIds, updateDisabledTools]
  );

  const toolMap = useMemo(() => {
    const map: Record<number, ToolState> = {};
    tools.forEach((tool) => {
      if (forcedToolIds.includes(tool.id)) {
        map[tool.id] = ToolState.Forced;
      } else if (disabledToolIds.includes(tool.id)) {
        map[tool.id] = ToolState.Disabled;
      } else {
        map[tool.id] = ToolState.Enabled;
      }
    });
    return map;
  }, [tools, forcedToolIds, disabledToolIds]);

  console.log(toolMap);

  return (
    <ActionsContext.Provider
      value={{
        toolMap,
        forcedToolIds,
        setToolStatus,
        setToolsStatus,
        setForcedToolIds,
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
