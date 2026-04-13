"use client";

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useMemo,
  type ReactNode,
} from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ProposalReviewContextValue {
  /** Currently selected ruleset ID for the review run. */
  selectedRulesetId: string | null;
  setSelectedRulesetId: (id: string) => void;

  /** Whether an AI review is currently running. */
  isReviewRunning: boolean;
  setIsReviewRunning: (running: boolean) => void;

  /** ID of the current review run (set after triggering). */
  currentReviewRunId: string | null;
  setCurrentReviewRunId: (id: string | null) => void;

  /** Finding ID to scroll to and highlight in ChecklistPanel. */
  focusedFindingId: string | null;
  setFocusedFindingId: (id: string | null) => void;

  /** Reset review state (for starting a new review). */
  resetReviewState: () => void;
}

// ---------------------------------------------------------------------------
// Context
// ---------------------------------------------------------------------------

const ProposalReviewContext = createContext<ProposalReviewContextValue | null>(
  null
);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

interface ProposalReviewProviderProps {
  children: ReactNode;
}

export function ProposalReviewProvider({
  children,
}: ProposalReviewProviderProps) {
  const [selectedRulesetId, setSelectedRulesetId] = useState<string | null>(
    null
  );
  const [isReviewRunning, setIsReviewRunning] = useState(false);
  const [currentReviewRunId, setCurrentReviewRunId] = useState<string | null>(
    null
  );
  const [focusedFindingId, setFocusedFindingId] = useState<string | null>(null);

  const resetReviewState = useCallback(() => {
    setIsReviewRunning(false);
    setCurrentReviewRunId(null);
    setFocusedFindingId(null);
  }, []);

  const value = useMemo<ProposalReviewContextValue>(
    () => ({
      selectedRulesetId,
      setSelectedRulesetId,
      isReviewRunning,
      setIsReviewRunning,
      currentReviewRunId,
      setCurrentReviewRunId,
      focusedFindingId,
      setFocusedFindingId,
      resetReviewState,
    }),
    [
      selectedRulesetId,
      isReviewRunning,
      currentReviewRunId,
      focusedFindingId,
      resetReviewState,
    ]
  );

  return (
    <ProposalReviewContext.Provider value={value}>
      {children}
    </ProposalReviewContext.Provider>
  );
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useProposalReviewContext() {
  const context = useContext(ProposalReviewContext);
  if (!context) {
    throw new Error(
      "useProposalReviewContext must be used within a ProposalReviewProvider"
    );
  }
  return context;
}
