"use client";

import { useState, useCallback, useRef } from "react";
import {
  createSession,
  deleteSession,
  executeTask,
  BuildEvent,
  ArtifactInfo,
} from "@/lib/build/client";

export type BuildStatus =
  | "idle"
  | "creating"
  | "running"
  | "completed"
  | "failed";

export interface UseBuildReturn {
  status: BuildStatus;
  sessionId: string | null;
  output: string;
  artifacts: ArtifactInfo[];
  error: string | null;
  run: (task: string, context?: string) => Promise<void>;
  cleanup: () => Promise<void>;
}

export function useBuild(): UseBuildReturn {
  const [status, setStatus] = useState<BuildStatus>("idle");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [output, setOutput] = useState("");
  const [artifacts, setArtifacts] = useState<ArtifactInfo[]>([]);
  const [error, setError] = useState<string | null>(null);

  const abortControllerRef = useRef<AbortController | null>(null);

  const run = useCallback(async (task: string, context?: string) => {
    setStatus("creating");
    setOutput("");
    setArtifacts([]);
    setError(null);

    try {
      const { session_id } = await createSession({ task });
      setSessionId(session_id);
      setStatus("running");

      await executeTask(
        session_id,
        task,
        context,
        (event: BuildEvent) => {
          switch (event.type) {
            case "output":
              setOutput((prev) => prev + event.data.data);
              break;
            case "status":
              if (event.data.status === "completed") {
                setStatus("completed");
              } else if (event.data.status === "failed") {
                setStatus("failed");
                setError(event.data.message || "Task failed");
              }
              break;
            case "artifact":
              setArtifacts((prev) => [
                ...prev,
                {
                  artifact_type: event.data
                    .artifact_type as ArtifactInfo["artifact_type"],
                  path: event.data.path,
                  filename: event.data.filename,
                },
              ]);
              break;
            case "error":
              setStatus("failed");
              setError(event.data.message);
              break;
          }
        },
        (err) => {
          setStatus("failed");
          setError(err.message);
        },
        () => {
          // Stream complete - status should already be set by status event
        }
      );
    } catch (err) {
      setStatus("failed");
      setError(err instanceof Error ? err.message : "Unknown error");
    }
  }, []);

  const cleanup = useCallback(async () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    if (sessionId) {
      try {
        await deleteSession(sessionId);
      } catch {
        // Ignore cleanup errors
      }
      setSessionId(null);
    }
    setStatus("idle");
    setOutput("");
    setArtifacts([]);
    setError(null);
  }, [sessionId]);

  return {
    status,
    sessionId,
    output,
    artifacts,
    error,
    run,
    cleanup,
  };
}
