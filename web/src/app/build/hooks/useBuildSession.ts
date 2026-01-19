"use client";

import { useState, useCallback } from "react";

// =============================================================================
// Types - Define these now so components know what to expect
// =============================================================================

export interface Artifact {
  id: string;
  session_id: string;
  type:
    | "nextjs_app"
    | "pptx"
    | "xlsx"
    | "docx"
    | "markdown"
    | "chart"
    | "csv"
    | "image";
  name: string;
  path: string;
  created_at: Date;
  updated_at: Date;
}

export interface BuildMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: Date;
  // TODO: Add tool calls, artifacts references, etc.
}

export type SessionStatus =
  | "idle"
  | "creating"
  | "running"
  | "completed"
  | "failed";

export interface Session {
  id: string | null;
  status: SessionStatus;
  artifacts: Artifact[];
  messages: BuildMessage[];
  error: string | null;
  webappUrl: string | null;
}

export interface UseBuildSessionReturn {
  // Session state
  session: Session;
  hasSession: boolean;
  isRunning: boolean;

  // Actions
  startSession: (prompt: string) => Promise<void>;
  sendMessage: (message: string) => Promise<void>;
  resetSession: () => void;

  // History (for sidebar)
  sessionHistory: { id: string; title: string; createdAt: Date }[];
  loadSession: (sessionId: string) => Promise<void>;
}

// =============================================================================
// Initial/Mock State
// =============================================================================

const initialSession: Session = {
  id: "1",
  status: "idle",
  artifacts: [],
  messages: [],
  error: null,
  webappUrl: null,
};

// =============================================================================
// Hook Implementation
// =============================================================================

/**
 * useBuildSession - Hook for managing build session state and actions
 *
 * Currently returns mock/placeholder data.
 * When APIs are ready, update this hook's internals - components stay unchanged.
 */
export function useBuildSession(): UseBuildSessionReturn {
  const [session, setSession] = useState<Session>(initialSession);

  // Derived state
  const hasSession = session.id !== null;
  const isRunning =
    session.status === "running" || session.status === "creating";

  // =============================================================================
  // Actions - Implement these when APIs are ready
  // =============================================================================

  const startSession = useCallback(async (prompt: string) => {
    // TODO: Call API to create new session
    console.log("Starting session with prompt:", prompt);

    // Mock: Just set a session ID for now
    setSession((prev) => ({
      ...prev,
      id: `session-${Date.now()}`,
      status: "running",
      messages: [
        {
          id: `msg-${Date.now()}`,
          role: "user",
          content: prompt,
          timestamp: new Date(),
        },
      ],
    }));
  }, []);

  const sendMessage = useCallback(async (message: string) => {
    // TODO: Call API to send message to existing session
    console.log("Sending message:", message);

    setSession((prev) => ({
      ...prev,
      messages: [
        ...prev.messages,
        {
          id: `msg-${Date.now()}`,
          role: "user",
          content: message,
          timestamp: new Date(),
        },
      ],
    }));
  }, []);

  const resetSession = useCallback(() => {
    setSession(initialSession);
  }, []);

  const loadSession = useCallback(async (sessionId: string) => {
    // TODO: Call API to load session by ID
    console.log("Loading session:", sessionId);
  }, []);

  // =============================================================================
  // Session History - Mock data for now
  // =============================================================================

  const sessionHistory: UseBuildSessionReturn["sessionHistory"] = [
    // TODO: Fetch from API
  ];

  return {
    session,
    hasSession,
    isRunning,
    startSession,
    sendMessage,
    resetSession,
    sessionHistory,
    loadSession,
  };
}
