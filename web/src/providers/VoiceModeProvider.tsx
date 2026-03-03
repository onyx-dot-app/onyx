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
  stopTTS: () => void;
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

  const [isTTSPlaying, setIsTTSPlaying] = useState(false);
  const [isTTSLoading, setIsTTSLoading] = useState(false);
  const [spokenText, setSpokenText] = useState("");

  // WebSocket and audio state
  const wsRef = useRef<WebSocket | null>(null);
  const mediaSourceRef = useRef<MediaSource | null>(null);
  const sourceBufferRef = useRef<SourceBuffer | null>(null);
  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const pendingChunksRef = useRef<Uint8Array[]>([]);
  const isAppendingRef = useRef(false);
  const isPlayingRef = useRef(false);
  const hasStartedPlaybackRef = useRef(false);

  // Text tracking
  const committedPositionRef = useRef(0);
  const lastRawTextRef = useRef("");
  const pendingTextRef = useRef<string[]>([]);

  // Timers
  const flushTimerRef = useRef<NodeJS.Timeout | null>(null);
  const fastStartTimerRef = useRef<NodeJS.Timeout | null>(null);
  const hasSpokenFirstChunkRef = useRef(false);

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
      } catch (err) {
        console.error("[TTS] Error appending buffer:", err);
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
  }, []);

  // Initialize MediaSource for streaming audio
  const initMediaSource = useCallback(async () => {
    // Check if MediaSource is supported
    if (!window.MediaSource || !MediaSource.isTypeSupported("audio/mpeg")) {
      console.error("[TTS] MediaSource not supported");
      return false;
    }

    // Create MediaSource and audio element
    mediaSourceRef.current = new MediaSource();
    audioElementRef.current = new Audio();
    audioElementRef.current.src = URL.createObjectURL(mediaSourceRef.current);

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
      console.error("[TTS] Audio playback error");
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
        hasStartedPlaybackRef.current = true;
        // Small delay to buffer a bit before starting
        setTimeout(() => {
          audioElementRef.current?.play().catch((err) => {
            console.error("[TTS] Playback start error:", err);
          });
        }, 100);
      }
    },
    [processNextChunk]
  );

  // Get WebSocket URL for TTS
  const getWebSocketUrl = useCallback(() => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const isDev = window.location.port === "3000";
    const host = isDev ? "localhost:8080" : window.location.host;
    const path = isDev
      ? "/voice/synthesize/stream"
      : "/api/voice/synthesize/stream";
    return `${protocol}//${host}${path}`;
  }, []);

  // Connect to WebSocket TTS
  const connectWebSocket = useCallback(async () => {
    // Skip if already connected or connecting
    if (
      wsRef.current?.readyState === WebSocket.OPEN ||
      wsRef.current?.readyState === WebSocket.CONNECTING
    ) {
      return;
    }

    // Initialize MediaSource first
    const initialized = await initMediaSource();
    if (!initialized) {
      console.error("[TTS] Failed to initialize MediaSource");
      return;
    }

    const wsUrl = getWebSocketUrl();

    console.log("[TTS] Connecting to WebSocket:", wsUrl);
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      console.log("[TTS] WebSocket connected");
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
            console.log("[TTS] Audio generation complete");
            setIsTTSLoading(false);
            finalizeStream();
          } else if (msg.type === "error") {
            console.error("[TTS] WebSocket error:", msg.message);
          }
        } catch {
          // Ignore parse errors
        }
      }
    };

    ws.onerror = (err) => {
      console.error("[TTS] WebSocket error:", err);
    };

    ws.onclose = () => {
      console.log("[TTS] WebSocket closed");
      wsRef.current = null;
      finalizeStream();
    };

    wsRef.current = ws;
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
        "[TTS] Sending:",
        text.substring(0, 50) + (text.length > 50 ? "..." : "")
      );
      setIsTTSLoading(true);
      setSpokenText((prev) => (prev ? prev + " " + text : text));

      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "synthesize", text }));
      } else {
        // Queue and connect
        pendingTextRef.current.push(text);
        connectWebSocket();
      }
    },
    [connectWebSocket]
  );

  const streamTTS = useCallback(
    (text: string, isComplete: boolean = false) => {
      if (!autoPlayback) return;

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

      if (uncommittedText.length === 0) return;

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
              console.log("[TTS] Fast start:", chunk.substring(0, 40));
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

  const stopTTS = useCallback(() => {
    // Clear timers
    if (flushTimerRef.current) {
      clearTimeout(flushTimerRef.current);
      flushTimerRef.current = null;
    }
    if (fastStartTimerRef.current) {
      clearTimeout(fastStartTimerRef.current);
      fastStartTimerRef.current = null;
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
  }, []);

  const resetTTS = useCallback(() => {
    stopTTS();
    committedPositionRef.current = 0;
    lastRawTextRef.current = "";
    hasSpokenFirstChunkRef.current = false;
    setSpokenText("");
  }, [stopTTS]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (flushTimerRef.current) clearTimeout(flushTimerRef.current);
      if (fastStartTimerRef.current) clearTimeout(fastStartTimerRef.current);
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
