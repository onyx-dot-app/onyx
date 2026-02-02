import { useRef, useState, useEffect, useCallback, useMemo } from "react";
import { PacketType } from "@/app/app/services/streamingModels";
import { GroupedPacket } from "./packetProcessor";
import { TurnGroup, TransformedStep } from "../transformers";

// Delay between different packet types (ms)
const PACING_DELAY_MS = 200;

/**
 * Tool START packet types used for categorizing steps
 * These determine the "type" of a step for pacing purposes
 */
const TOOL_START_PACKET_TYPES = new Set<PacketType>([
  PacketType.SEARCH_TOOL_START,
  PacketType.FETCH_TOOL_START,
  PacketType.PYTHON_TOOL_START,
  PacketType.CUSTOM_TOOL_START,
  PacketType.REASONING_START,
  PacketType.IMAGE_GENERATION_TOOL_START,
  PacketType.DEEP_RESEARCH_PLAN_START,
  PacketType.RESEARCH_AGENT_START,
]);

/**
 * Get the primary packet type from a step's packets (first START packet)
 * Used to determine if a type transition occurred
 */
function getStepPacketType(step: TransformedStep): PacketType | null {
  for (const packet of step.packets) {
    if (TOOL_START_PACKET_TYPES.has(packet.obj.type as PacketType)) {
      return packet.obj.type as PacketType;
    }
  }
  return null;
}

/**
 * Internal pacing state stored in ref (not triggering re-renders)
 */
interface PacingState {
  // Tracking revealed content
  revealedStepKeys: Set<string>;
  lastRevealedPacketType: PacketType | null;

  // Queued content
  pendingSteps: TransformedStep[];

  // Timer
  pacingTimer: ReturnType<typeof setTimeout> | null;

  // Flags
  toolPacingComplete: boolean;
  stopPacketSeen: boolean;

  // Track nodeId for reset detection
  nodeId: string | null;
}

function createInitialPacingState(): PacingState {
  return {
    revealedStepKeys: new Set(),
    lastRevealedPacketType: null,
    pendingSteps: [],
    pacingTimer: null,
    toolPacingComplete: false,
    stopPacketSeen: false,
    nodeId: null,
  };
}

/**
 * Hook that adds pacing delays when packet types change during streaming.
 * Creates visual breathing room between different agent activities.
 *
 * Architecture:
 * - Pacing state in ref: no re-renders for internal tracking
 * - useState only for revealTrigger: forces re-render when content should update
 * - Timer-based delays: 200ms between different packet types
 *
 * @param toolTurnGroups - Turn groups from packet processor
 * @param displayGroups - Display content groups (MESSAGE_START/DELTA)
 * @param stopPacketSeen - Whether STOP packet has been received
 * @param nodeId - Message node ID for reset detection
 * @param finalAnswerComing - Whether message content is streaming
 */
export function usePacedTurnGroups(
  toolTurnGroups: TurnGroup[],
  displayGroups: GroupedPacket[],
  stopPacketSeen: boolean,
  nodeId: number,
  finalAnswerComing: boolean
): {
  pacedTurnGroups: TurnGroup[];
  pacedDisplayGroups: GroupedPacket[];
  pacedFinalAnswerComing: boolean;
} {
  // Ref-based pacing state (no re-renders)
  const stateRef = useRef<PacingState>(createInitialPacingState());

  // Track previous finalAnswerComing to detect tool-after-message transitions
  const prevFinalAnswerComingRef = useRef(finalAnswerComing);

  // Trigger re-render when content should update
  // Used in useMemo dependencies since state.revealedStepKeys is stored in a ref
  const [revealTrigger, setRevealTrigger] = useState(0);

  // Stable nodeId string for comparison
  const nodeIdStr = String(nodeId);

  // Reset on nodeId change
  if (stateRef.current.nodeId !== nodeIdStr) {
    if (stateRef.current.pacingTimer) {
      clearTimeout(stateRef.current.pacingTimer);
    }
    stateRef.current = createInitialPacingState();
    stateRef.current.nodeId = nodeIdStr;
  }

  const state = stateRef.current;

  // Bypass pacing for completed messages (old messages loaded from history)
  // If stopPacketSeen is true on first render, return everything immediately
  const shouldBypassPacing =
    stopPacketSeen &&
    state.revealedStepKeys.size === 0 &&
    toolTurnGroups.length > 0;

  // Handle revealing the next pending step
  // Uses a while loop to reveal all consecutive steps of the same type in a single pass
  const revealNextPendingStep = useCallback(() => {
    const state = stateRef.current;

    // Reveal all consecutive steps of the same type in a single pass
    while (state.pendingSteps.length > 0) {
      const stepToReveal = state.pendingSteps.shift()!;
      state.revealedStepKeys.add(stepToReveal.key);
      state.lastRevealedPacketType = getStepPacketType(stepToReveal);

      // Check if next step has different type - if so, schedule delay and exit
      if (state.pendingSteps.length > 0) {
        const nextType = getStepPacketType(state.pendingSteps[0]!);
        if (nextType !== state.lastRevealedPacketType) {
          state.pacingTimer = setTimeout(
            revealNextPendingStep,
            PACING_DELAY_MS
          );
          setRevealTrigger((t) => t + 1);
          return;
        }
        // Same type - continue loop to reveal next immediately
      }
    }

    // No more pending steps - pacing complete
    state.toolPacingComplete = true;
    state.pacingTimer = null;
    setRevealTrigger((t) => t + 1);
  }, []);

  // Process incoming turn groups
  useEffect(() => {
    // Skip processing when bypassing pacing
    if (shouldBypassPacing) return;

    const state = stateRef.current;

    // Detect tool-after-message transition: message was showing, now tools are starting
    // Reset toolPacingComplete to hide display until new tools finish pacing
    if (prevFinalAnswerComingRef.current && !finalAnswerComing) {
      state.toolPacingComplete = false;
    }
    prevFinalAnswerComingRef.current = finalAnswerComing;

    // Handle STOP packet - flush everything immediately
    if (stopPacketSeen && !state.stopPacketSeen) {
      state.stopPacketSeen = true;

      // Clear any pending timer
      if (state.pacingTimer) {
        clearTimeout(state.pacingTimer);
        state.pacingTimer = null;
      }

      // Reveal all pending steps immediately
      for (const step of state.pendingSteps) {
        state.revealedStepKeys.add(step.key);
      }
      state.pendingSteps = [];
      state.toolPacingComplete = true;

      setRevealTrigger((t) => t + 1);
      return;
    }

    // Collect all steps from turn groups
    const allSteps: TransformedStep[] = [];
    for (const turnGroup of toolTurnGroups) {
      for (const step of turnGroup.steps) {
        allSteps.push(step);
      }
    }

    // Find new steps (not yet revealed or pending)
    const newSteps: TransformedStep[] = [];
    const pendingKeys = new Set(state.pendingSteps.map((s) => s.key));

    for (const step of allSteps) {
      if (!state.revealedStepKeys.has(step.key) && !pendingKeys.has(step.key)) {
        newSteps.push(step);
      }
    }

    if (newSteps.length === 0) {
      // If there are no tool steps at all, mark pacing complete immediately
      // This allows tool-less responses to render their displayGroups
      if (allSteps.length === 0 && !state.toolPacingComplete) {
        state.toolPacingComplete = true;
        setRevealTrigger((t) => t + 1);
        return;
      }

      // Check if all steps are revealed (no pending, no new)
      if (
        state.pendingSteps.length === 0 &&
        !state.pacingTimer &&
        allSteps.length > 0
      ) {
        const allRevealed = allSteps.every((s) =>
          state.revealedStepKeys.has(s.key)
        );
        if (allRevealed && !state.toolPacingComplete) {
          state.toolPacingComplete = true;
          setRevealTrigger((t) => t + 1);
        }
      }
      return;
    }

    // Process new steps
    for (const step of newSteps) {
      const stepType = getStepPacketType(step);

      // First step ever - reveal immediately
      if (
        state.revealedStepKeys.size === 0 &&
        state.pendingSteps.length === 0
      ) {
        state.revealedStepKeys.add(step.key);
        state.lastRevealedPacketType = stepType;
        setRevealTrigger((t) => t + 1);
        continue;
      }

      // Same type as last revealed (or pending) - handle based on current state
      const effectiveLastType =
        state.pendingSteps.length > 0
          ? getStepPacketType(
              state.pendingSteps[state.pendingSteps.length - 1]!
            )
          : state.lastRevealedPacketType;

      if (stepType === effectiveLastType) {
        // Same type
        if (state.pendingSteps.length === 0 && !state.pacingTimer) {
          // Nothing pending, no timer - reveal immediately
          state.revealedStepKeys.add(step.key);
          state.lastRevealedPacketType = stepType;
          setRevealTrigger((t) => t + 1);
        } else {
          // Add to pending queue (will be revealed when timer fires or queue processes)
          state.pendingSteps.push(step);
        }
      } else {
        // Different type - queue for paced reveal
        state.pendingSteps.push(step);

        // Start timer if not already running
        if (!state.pacingTimer && state.pendingSteps.length === 1) {
          state.pacingTimer = setTimeout(
            revealNextPendingStep,
            PACING_DELAY_MS
          );
        }
      }
    }

    // Mark pacing incomplete while we have pending steps or timer
    if (state.pendingSteps.length > 0 || state.pacingTimer) {
      state.toolPacingComplete = false;
    }
  }, [
    toolTurnGroups,
    stopPacketSeen,
    finalAnswerComing,
    revealNextPendingStep,
    shouldBypassPacing,
  ]);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (stateRef.current.pacingTimer) {
        clearTimeout(stateRef.current.pacingTimer);
      }
    };
  }, []);

  // Build paced turn groups from revealed step keys
  // Memoized to prevent unnecessary re-renders in downstream components
  // revealTrigger is included because state.revealedStepKeys is stored in a ref
  const pacedTurnGroups = useMemo(() => {
    // Bypass: return all turn groups immediately
    if (shouldBypassPacing) return toolTurnGroups;

    const result: TurnGroup[] = [];
    for (const turnGroup of toolTurnGroups) {
      const revealedSteps = turnGroup.steps.filter((step) =>
        state.revealedStepKeys.has(step.key)
      );
      if (revealedSteps.length > 0) {
        result.push({
          turnIndex: turnGroup.turnIndex,
          steps: revealedSteps,
          isParallel: revealedSteps.length > 1,
        });
      }
    }
    return result;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toolTurnGroups, revealTrigger, shouldBypassPacing]);

  // Only return display groups when tool pacing is complete (or bypassing)
  const pacedDisplayGroups = useMemo(
    () => (shouldBypassPacing || state.toolPacingComplete ? displayGroups : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.toolPacingComplete, displayGroups, revealTrigger, shouldBypassPacing]
  );

  // Paced signals for header state consistency
  // Only signal finalAnswerComing when tool pacing is complete (or bypassing)
  const pacedFinalAnswerComing = useMemo(
    () => (shouldBypassPacing || state.toolPacingComplete) && finalAnswerComing,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [
      state.toolPacingComplete,
      finalAnswerComing,
      revealTrigger,
      shouldBypassPacing,
    ]
  );

  return {
    pacedTurnGroups,
    pacedDisplayGroups,
    pacedFinalAnswerComing,
  };
}
