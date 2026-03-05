"use client";

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  useEffect,
} from "react";
import { useUser } from "@/providers/UserProvider";

interface VoiceModeContextType {
  /** Whether TTS audio is currently playing */
  isTTSPlaying: boolean;
  /** Whether TTS is loading/generating audio */
  isTTSLoading: boolean;
  /** Text that has been spoken so far (for synced display) */
  spokenText: string;
  /** Stream text for TTS - speaks sentences as they complete */
  streamTTS: (text: string, isComplete?: boolean) => void;
  /** Stop TTS playback */
  stopTTS: (options?: { manual?: boolean }) => void;
  /** Increments when TTS is manually stopped by the user */
  manualStopCount: number;
  /** Reset state for new message */
  resetTTS: () => void;
}

const VoiceModeContext = createContext<VoiceModeContextType | null>(null);

/**
 * Clean text for TTS - remove markdown formatting
 */
function cleanTextForTTS(text: string): string {
  return text
    .replace(/\*\*/g, "") // Remove bold markers
    .replace(/\*/g, "") // Remove italic markers
    .replace(/`{1,3}/g, "") // Remove code markers
    .replace(/#{1,6}\s*/g, "") // Remove headers
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1") // Convert links to just text
    .replace(/\n+/g, " ") // Replace newlines with spaces
    .replace(/\s+/g, " ") // Normalize whitespace
    .trim();
}

/**
 * Find the next natural chunk boundary in text.
 * Prefers sentence endings for natural speech rhythm.
 */
function findChunkBoundary(text: string): number {
  // Look for sentence endings (. ! ?) - these are natural speech breaks
  const sentenceRegex = /[.!?](?:\s|$)/g;
  let match;
  let lastSentenceEnd = -1;

  while ((match = sentenceRegex.exec(text)) !== null) {
    const endPos = match.index + 1;
    if (endPos >= 10) {
      lastSentenceEnd = endPos;
      if (endPos >= 30) return endPos;
    }
  }

  if (lastSentenceEnd > 0) return lastSentenceEnd;

  // Only break at clauses for very long text (150+ chars)
  if (text.length >= 150) {
    const clauseRegex = /[,;:]\s/g;
    while ((match = clauseRegex.exec(text)) !== null) {
      const endPos = match.index + 1;
      if (endPos >= 70) return endPos;
    }
  }

  // Break at word boundary for extremely long text (200+ chars)
  if (text.length >= 200) {
    const spaceIndex = text.lastIndexOf(" ", 120);
    if (spaceIndex > 80) return spaceIndex;
  }

  return -1;
}

export function VoiceModeProvider({ children }: { children: React.ReactNode }) {
  const { user } = useUser();
  const autoPlayback = user?.preferences?.voice_auto_playback ?? false;
  const playbackSpeed = user?.preferences?.voice_playback_speed ?? 1.0;
  const preferredVoice = user?.preferences?.preferred_voice;

  // Debug log preferences on mount and when they change
  useEffect(() => {
    console.log(
      `[VoiceMode] Preferences: autoPlayback=${autoPlayback}, ` +
        `playbackSpeed=${playbackSpeed}, preferredVoice=${preferredVoice}, ` +
        `userLoaded=${!!user}`
    );
  }, [autoPlayback, playbackSpeed, preferredVoice, user]);

  const [isTTSPlaying, setIsTTSPlaying] = useState(false);
  const [isTTSLoading, setIsTTSLoading] = useState(false);
  const [spokenText, setSpokenText] = useState("");
  const [manualStopCount, setManualStopCount] = useState(0);

  // Debug log state changes
  useEffect(() => {
    console.log(
      `[VoiceMode] State: isTTSPlaying=${isTTSPlaying}, isTTSLoading=${isTTSLoading}`
    );
  }, [isTTSPlaying, isTTSLoading]);

  // WebSocket and audio state
  const wsRef = useRef<WebSocket | null>(null);
  const mediaSourceRef = useRef<MediaSource | null>(null);
  const sourceBufferRef = useRef<SourceBuffer | null>(null);
  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  const pendingChunksRef = useRef<Uint8Array[]>([]);
  const isAppendingRef = useRef(false);
  const isPlayingRef = useRef(false);
  const hasStartedPlaybackRef = useRef(false);

  // Text tracking
  const committedPositionRef = useRef(0);
  const lastRawTextRef = useRef("");
  const pendingTextRef = useRef<string[]>([]);
  const isConnectingRef = useRef(false);

  // Timers
  const flushTimerRef = useRef<NodeJS.Timeout | null>(null);
  const fastStartTimerRef = useRef<NodeJS.Timeout | null>(null);
  const loadingTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const hasSpokenFirstChunkRef = useRef(false);
  const hasSignaledEndRef = useRef(false);

  // Process next chunk from the pending queue
  const processNextChunk = useCallback(() => {
    if (
      isAppendingRef.current ||
      pendingChunksRef.current.length === 0 ||
      !sourceBufferRef.current ||
      sourceBufferRef.current.updating
    ) {
      return;
    }

    const chunk = pendingChunksRef.current.shift();
    if (chunk) {
      isAppendingRef.current = true;
      try {
        const buffer = chunk.buffer.slice(
          chunk.byteOffset,
          chunk.byteOffset + chunk.byteLength
        ) as ArrayBuffer;
        sourceBufferRef.current.appendBuffer(buffer);
      } catch {
        isAppendingRef.current = false;
        processNextChunk();
      }
    }
  }, []);

  // Finalize the media stream when done
  const finalizeStream = useCallback(() => {
    if (pendingChunksRef.current.length > 0 || isAppendingRef.current) {
      setTimeout(() => finalizeStream(), 50);
      return;
    }

    if (
      mediaSourceRef.current &&
      mediaSourceRef.current.readyState === "open" &&
      sourceBufferRef.current &&
      !sourceBufferRef.current.updating
    ) {
      try {
        mediaSourceRef.current.endOfStream();
      } catch {
        // Ignore errors when ending stream
      }
    }

    // Fallback: if audio doesn't finish playing within 30s after stream ends,
    // reset the playing state to prevent mic button from being stuck disabled
    setTimeout(() => {
      if (isPlayingRef.current) {
        console.warn("VoiceMode: audio playback timeout, resetting state");
        isPlayingRef.current = false;
        setIsTTSPlaying(false);
      }
    }, 30000);
  }, []);

  // Initialize MediaSource for streaming audio
  const initMediaSource = useCallback(async () => {
    // Check if MediaSource is supported
    if (!window.MediaSource || !MediaSource.isTypeSupported("audio/mpeg")) {
      return false;
    }

    // Create MediaSource and audio element
    mediaSourceRef.current = new MediaSource();
    audioElementRef.current = new Audio();
    audioUrlRef.current = URL.createObjectURL(mediaSourceRef.current);
    audioElementRef.current.src = audioUrlRef.current;

    audioElementRef.current.onplay = () => {
      if (!isPlayingRef.current) {
        isPlayingRef.current = true;
        setIsTTSPlaying(true);
      }
    };

    audioElementRef.current.onended = () => {
      isPlayingRef.current = false;
      setIsTTSPlaying(false);
    };

    audioElementRef.current.onerror = () => {
      isPlayingRef.current = false;
      setIsTTSPlaying(false);
    };

    // Wait for MediaSource to be ready
    await new Promise<void>((resolve, reject) => {
      if (!mediaSourceRef.current) {
        reject(new Error("MediaSource not initialized"));
        return;
      }

      mediaSourceRef.current.onsourceopen = () => {
        try {
          sourceBufferRef.current =
            mediaSourceRef.current!.addSourceBuffer("audio/mpeg");
          sourceBufferRef.current.mode = "sequence";

          sourceBufferRef.current.onupdateend = () => {
            isAppendingRef.current = false;
            processNextChunk();
          };

          resolve();
        } catch (err) {
          reject(err);
        }
      };

      mediaSourceRef.current.onsourceclose = () => {
        if (mediaSourceRef.current?.readyState === "closed") {
          reject(new Error("MediaSource closed unexpectedly"));
        }
      };
    });

    return true;
  }, [processNextChunk]);

  // Handle incoming audio data from WebSocket
  const handleAudioData = useCallback(
    async (data: ArrayBuffer) => {
      pendingChunksRef.current.push(new Uint8Array(data));
      processNextChunk();

      // Start playback after first chunk
      if (!hasStartedPlaybackRef.current && audioElementRef.current) {
        // Small delay to buffer a bit before starting
        setTimeout(() => {
          const audioEl = audioElementRef.current;
          if (!audioEl || hasStartedPlaybackRef.current) {
            return;
          }

          audioEl
            .play()
            .then(() => {
              hasStartedPlaybackRef.current = true;
            })
            .catch(() => {
              // Keep hasStartedPlaybackRef as false so we retry on next audio chunk.
            });
        }, 100);
      }
    },
    [processNextChunk]
  );

  // Get WebSocket URL for TTS with authentication token
  const getWebSocketUrl = useCallback(async () => {
    // Fetch short-lived WS token
    const tokenResponse = await fetch("/api/voice/ws-token", {
      method: "POST",
      credentials: "include",
    });
    if (!tokenResponse.ok) {
      throw new Error("Failed to get WebSocket authentication token");
    }
    const { token } = await tokenResponse.json();

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const isDev = window.location.port === "3000";
    const host = isDev ? "localhost:8080" : window.location.host;
    const path = isDev
      ? "/voice/synthesize/stream"
      : "/api/voice/synthesize/stream";
    return `${protocol}//${host}${path}?token=${encodeURIComponent(token)}`;
  }, []);

  // Connect to WebSocket TTS
  const connectWebSocket = useCallback(async () => {
    // Skip if already connected, connecting, or in the process of connecting
    if (
      wsRef.current?.readyState === WebSocket.OPEN ||
      wsRef.current?.readyState === WebSocket.CONNECTING ||
      isConnectingRef.current
    ) {
      return;
    }

    // Set connecting flag to prevent concurrent connection attempts
    isConnectingRef.current = true;

    try {
      // Initialize MediaSource first
      const initialized = await initMediaSource();
      if (!initialized) {
        isConnectingRef.current = false;
        return;
      }

      // Get WebSocket URL with auth token
      const wsUrl = await getWebSocketUrl();

      const ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        isConnectingRef.current = false;
        // Send initial config
        ws.send(
          JSON.stringify({
            type: "config",
            voice: preferredVoice,
            speed: playbackSpeed,
          })
        );

        // Send any pending text
        for (const text of pendingTextRef.current) {
          ws.send(JSON.stringify({ type: "synthesize", text }));
        }
        pendingTextRef.current = [];
      };

      ws.onmessage = async (event) => {
        if (event.data instanceof Blob) {
          const arrayBuffer = await event.data.arrayBuffer();
          handleAudioData(arrayBuffer);
        } else if (typeof event.data === "string") {
          try {
            const msg = JSON.parse(event.data);
            if (msg.type === "audio_done") {
              console.log("[VoiceMode] Received audio_done");
              // Clear loading timeout since we got a proper completion
              if (loadingTimeoutRef.current) {
                clearTimeout(loadingTimeoutRef.current);
                loadingTimeoutRef.current = null;
              }
              setIsTTSLoading(false);
              finalizeStream();
            }
          } catch {
            // Ignore parse errors
          }
        }
      };

      ws.onerror = () => {
        console.log("[VoiceMode] WebSocket error");
        isConnectingRef.current = false;
        // Reset loading state on error to prevent stuck state
        setIsTTSLoading(false);
      };

      ws.onclose = () => {
        console.log("[VoiceMode] WebSocket closed");
        wsRef.current = null;
        isConnectingRef.current = false;
        // Reset loading state when WebSocket closes to prevent stuck state
        // If audio_done wasn't received, this ensures we don't stay stuck
        setIsTTSLoading(false);
        finalizeStream();
      };

      wsRef.current = ws;
    } catch {
      isConnectingRef.current = false;
    }
  }, [
    preferredVoice,
    playbackSpeed,
    handleAudioData,
    getWebSocketUrl,
    initMediaSource,
    finalizeStream,
  ]);

  // Send text to TTS via WebSocket
  const sendTextToTTS = useCallback(
    (text: string) => {
      if (!text.trim()) return;

      console.log(
        `[VoiceMode] sendTextToTTS: "${text.slice(0, 50)}...", ` +
          `wsState=${wsRef.current?.readyState ?? "null"}`
      );

      setIsTTSLoading(true);
      setSpokenText((prev) => (prev ? prev + " " + text : text));

      // Set a timeout to reset loading state if TTS doesn't complete
      // This prevents the mic from getting stuck disabled
      if (loadingTimeoutRef.current) {
        clearTimeout(loadingTimeoutRef.current);
      }
      loadingTimeoutRef.current = setTimeout(() => {
        console.log("[VoiceMode] Loading timeout - resetting stuck state");
        setIsTTSLoading(false);
        setIsTTSPlaying(false);
      }, 60000); // 60 second timeout

      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "synthesize", text }));
        console.log("[VoiceMode] sendTextToTTS: sent via WebSocket");
      } else {
        // Queue and connect
        pendingTextRef.current.push(text);
        console.log(
          `[VoiceMode] sendTextToTTS: queued, pending=${pendingTextRef.current.length}`
        );
        connectWebSocket();
      }
    },
    [connectWebSocket]
  );

  const streamTTS = useCallback(
    (text: string, isComplete: boolean = false) => {
      // Debug logging
      console.log(
        `[VoiceMode] streamTTS called: autoPlayback=${autoPlayback}, ` +
          `textLen=${text.length}, isComplete=${isComplete}`
      );

      if (!autoPlayback) {
        console.log("[VoiceMode] streamTTS: autoPlayback is false, skipping");
        return;
      }

      // Skip if text hasn't changed
      if (text === lastRawTextRef.current && !isComplete) return;
      lastRawTextRef.current = text;

      // Clear pending timers
      if (flushTimerRef.current) {
        clearTimeout(flushTimerRef.current);
        flushTimerRef.current = null;
      }
      if (fastStartTimerRef.current) {
        clearTimeout(fastStartTimerRef.current);
        fastStartTimerRef.current = null;
      }

      // Clean the full text
      const cleanedText = cleanTextForTTS(text);
      const uncommittedText = cleanedText.slice(committedPositionRef.current);

      // On completion, we must still signal "end" even if there's no new text.
      // Otherwise ElevenLabs waits for more input and eventually times out.
      if (uncommittedText.length === 0) {
        if (isComplete && !hasSignaledEndRef.current) {
          hasSignaledEndRef.current = true;
          console.log(
            `[VoiceMode] streamTTS: isComplete=true (no new text), wsState=${wsRef.current?.readyState}, ` +
              `pendingText=${pendingTextRef.current.length}`
          );

          if (wsRef.current?.readyState === WebSocket.OPEN) {
            console.log("[VoiceMode] streamTTS: sending 'end' signal");
            wsRef.current.send(JSON.stringify({ type: "end" }));
          } else {
            console.log(
              "[VoiceMode] streamTTS: WebSocket not open, will send 'end' after connect and pending text"
            );
            const sendEnd = () => {
              if (wsRef.current?.readyState === WebSocket.OPEN) {
                if (pendingTextRef.current.length === 0) {
                  console.log(
                    "[VoiceMode] streamTTS: sending delayed 'end' signal"
                  );
                  wsRef.current.send(JSON.stringify({ type: "end" }));
                } else {
                  setTimeout(sendEnd, 100);
                }
              } else if (wsRef.current?.readyState === WebSocket.CONNECTING) {
                setTimeout(sendEnd, 100);
              } else {
                console.log(
                  "[VoiceMode] streamTTS: WebSocket closed, cannot send 'end'"
                );
              }
            };
            setTimeout(sendEnd, 100);
          }
        }
        return;
      }

      // Find chunk boundaries and send immediately
      let remaining = uncommittedText;
      let offset = 0;

      while (remaining.length > 0) {
        const boundaryIndex = findChunkBoundary(remaining);

        if (boundaryIndex > 0) {
          const chunkText = remaining.slice(0, boundaryIndex).trim();
          if (chunkText.length > 0) {
            sendTextToTTS(chunkText);
            hasSpokenFirstChunkRef.current = true;
          }
          offset += boundaryIndex;
          remaining = remaining.slice(boundaryIndex).trim();
        } else {
          break;
        }
      }

      committedPositionRef.current += offset;

      // Handle remaining text when stream is complete
      if (isComplete && remaining.trim().length > 0) {
        sendTextToTTS(remaining.trim());
        committedPositionRef.current = cleanedText.length;
        hasSpokenFirstChunkRef.current = true;
      }

      // When streaming is complete, signal end to flush remaining audio
      if (isComplete && !hasSignaledEndRef.current) {
        hasSignaledEndRef.current = true;
        console.log(
          `[VoiceMode] streamTTS: isComplete=true, wsState=${wsRef.current?.readyState}, ` +
            `pendingText=${pendingTextRef.current.length}`
        );

        if (wsRef.current?.readyState === WebSocket.OPEN) {
          console.log("[VoiceMode] streamTTS: sending 'end' signal");
          wsRef.current.send(JSON.stringify({ type: "end" }));
        } else {
          // WebSocket not ready - wait for connection and pending text to be sent first
          console.log(
            "[VoiceMode] streamTTS: WebSocket not open, will send 'end' after connect and pending text"
          );
          const sendEnd = () => {
            // Wait for WebSocket to be open AND all pending text to be sent
            if (wsRef.current?.readyState === WebSocket.OPEN) {
              if (pendingTextRef.current.length === 0) {
                // All pending text has been sent, now safe to send "end"
                console.log(
                  "[VoiceMode] streamTTS: sending delayed 'end' signal"
                );
                wsRef.current.send(JSON.stringify({ type: "end" }));
              } else {
                // Still have pending text, wait longer
                console.log(
                  `[VoiceMode] streamTTS: waiting for ${pendingTextRef.current.length} pending texts`
                );
                setTimeout(sendEnd, 100);
              }
            } else if (wsRef.current?.readyState === WebSocket.CONNECTING) {
              setTimeout(sendEnd, 100);
            } else {
              console.log(
                "[VoiceMode] streamTTS: WebSocket closed, cannot send 'end'"
              );
            }
          };
          setTimeout(sendEnd, 100);
        }
      }

      const currentUncommitted = cleanedText
        .slice(committedPositionRef.current)
        .trim();

      // Fast start: if we haven't spoken yet and have 20+ chars, send after 200ms
      if (
        !hasSpokenFirstChunkRef.current &&
        currentUncommitted.length >= 20 &&
        !isComplete
      ) {
        fastStartTimerRef.current = setTimeout(() => {
          if (hasSpokenFirstChunkRef.current) return;

          const nowCleaned = cleanTextForTTS(lastRawTextRef.current);
          const nowUncommitted = nowCleaned
            .slice(committedPositionRef.current)
            .trim();

          if (nowUncommitted.length >= 20) {
            // Find a reasonable break point
            let breakPoint = nowUncommitted.length;
            const spaceIdx = nowUncommitted.lastIndexOf(" ", 50);
            if (spaceIdx >= 15) breakPoint = spaceIdx;

            const chunk = nowUncommitted.slice(0, breakPoint).trim();
            if (chunk.length > 0) {
              sendTextToTTS(chunk);
              committedPositionRef.current += breakPoint;
              hasSpokenFirstChunkRef.current = true;
            }
          }
        }, 200);
      }

      // Flush timer for text ending with punctuation
      if (
        currentUncommitted.length > 0 &&
        !isComplete &&
        /[.!?]$/.test(currentUncommitted)
      ) {
        flushTimerRef.current = setTimeout(() => {
          const nowCleaned = cleanTextForTTS(lastRawTextRef.current);
          const nowUncommitted = nowCleaned
            .slice(committedPositionRef.current)
            .trim();

          if (nowUncommitted.length > 0) {
            sendTextToTTS(nowUncommitted);
            committedPositionRef.current = nowCleaned.length;
            hasSpokenFirstChunkRef.current = true;
          }
        }, 250);
      }
    },
    [autoPlayback, sendTextToTTS]
  );

  const stopTTS = useCallback((options?: { manual?: boolean }) => {
    // Clear timers
    if (flushTimerRef.current) {
      clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
    }
    if (fastStartTimerRef.current) {
      clearTimeout(fastStartTimerRef.current);
      fastStartTimerRef.current = null;
    }
    if (loadingTimeoutRef.current) {
      clearTimeout(loadingTimeoutRef.current);
      loadingTimeoutRef.current = null;
    }

    // Revoke blob URL to prevent memory leak
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }

    // Stop audio element
    if (audioElementRef.current) {
      audioElementRef.current.pause();
      audioElementRef.current.src = "";
      audioElementRef.current = null;
    }

    // Cleanup MediaSource
    if (
      mediaSourceRef.current &&
      mediaSourceRef.current.readyState === "open"
    ) {
      try {
        if (sourceBufferRef.current) {
          mediaSourceRef.current.removeSourceBuffer(sourceBufferRef.current);
        }
        mediaSourceRef.current.endOfStream();
      } catch {
        // Ignore cleanup errors
      }
    }

    mediaSourceRef.current = null;
    sourceBufferRef.current = null;
    pendingChunksRef.current = [];
    isAppendingRef.current = false;
    hasStartedPlaybackRef.current = false;
    pendingTextRef.current = [];
    isPlayingRef.current = false;
    hasSignaledEndRef.current = false;
    isConnectingRef.current = false;

    // Close WebSocket
    if (wsRef.current) {
      try {
        wsRef.current.send(JSON.stringify({ type: "end" }));
        wsRef.current.close();
      } catch {
        // Ignore
      }
      wsRef.current = null;
    }

    setIsTTSPlaying(false);
    setIsTTSLoading(false);
    if (options?.manual) {
      setManualStopCount((count) => count + 1);
    }
  }, []);

  const resetTTS = useCallback(() => {
    stopTTS();
    committedPositionRef.current = 0;
    lastRawTextRef.current = "";
    hasSpokenFirstChunkRef.current = false;
    hasSignaledEndRef.current = false;
    setSpokenText("");
  }, [stopTTS]);

  // Reset TTS state when voice auto-playback is disabled
  // This prevents the mic button from being stuck disabled
  const prevAutoPlaybackRef = useRef(autoPlayback);
  useEffect(() => {
    if (prevAutoPlaybackRef.current && !autoPlayback) {
      // Auto-playback was just disabled, clean up TTS state
      resetTTS();
    }
    prevAutoPlaybackRef.current = autoPlayback;
  }, [autoPlayback, resetTTS]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (flushTimerRef.current) clearTimeout(flushTimerRef.current);
      if (fastStartTimerRef.current) clearTimeout(fastStartTimerRef.current);
      if (loadingTimeoutRef.current) clearTimeout(loadingTimeoutRef.current);
      if (audioUrlRef.current) {
        URL.revokeObjectURL(audioUrlRef.current);
      }
      if (wsRef.current) {
        try {
          wsRef.current.close();
        } catch {
          // Ignore
        }
      }
      if (audioElementRef.current) {
        try {
          audioElementRef.current.pause();
          audioElementRef.current.src = "";
        } catch {
          // Ignore
        }
      }
      if (
        mediaSourceRef.current &&
        mediaSourceRef.current.readyState === "open"
      ) {
        try {
          mediaSourceRef.current.endOfStream();
        } catch {
          // Ignore
        }
      }
    };
  }, []);

  return (
    <VoiceModeContext.Provider
      value={{
        isTTSPlaying,
        isTTSLoading,
        spokenText,
        streamTTS,
        stopTTS,
        manualStopCount,
        resetTTS,
      }}
    >
      {children}
    </VoiceModeContext.Provider>
  );
}

export function useVoiceMode(): VoiceModeContextType {
  const context = useContext(VoiceModeContext);
  if (!context) {
    throw new Error("useVoiceMode must be used within VoiceModeProvider");
  }
  return context;
}
