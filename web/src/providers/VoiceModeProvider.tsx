"use client";

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  useEffect,
} from "react";
import { detectSentences } from "@/lib/sentenceDetector";
import { useUser } from "@/providers/UserProvider";

interface VoiceModeContextType {
  /** Whether TTS audio is currently playing */
  isTTSPlaying: boolean;
  /** Whether TTS is loading/fetching audio */
  isTTSLoading: boolean;
  /** Text that has been spoken so far (for synced display) */
  spokenText: string;
  /** Start streaming TTS - call with updated text as it streams */
  streamTTS: (text: string, isComplete?: boolean) => void;
  /** Stop TTS playback and clear queue */
  stopTTS: () => void;
  /** Reset state for new message */
  resetTTS: () => void;
}

const VoiceModeContext = createContext<VoiceModeContextType | null>(null);

export function VoiceModeProvider({ children }: { children: React.ReactNode }) {
  const { user } = useUser();
  const autoPlayback = user?.preferences?.voice_auto_playback ?? false;
  const playbackSpeed = user?.preferences?.voice_playback_speed ?? 1.0;
  const preferredVoice = user?.preferences?.preferred_voice;

  const [isTTSPlaying, setIsTTSPlaying] = useState(false);
  const [isTTSLoading, setIsTTSLoading] = useState(false);
  const [spokenText, setSpokenText] = useState("");

  // Refs for managing audio queue
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const queueRef = useRef<string[]>([]);
  const processedTextRef = useRef("");
  const bufferRef = useRef("");
  const isProcessingRef = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  const playNext = useCallback(async () => {
    if (queueRef.current.length === 0) {
      setIsTTSPlaying(false);
      setIsTTSLoading(false);
      isProcessingRef.current = false;
      return;
    }

    if (isProcessingRef.current) return;
    isProcessingRef.current = true;

    const sentence = queueRef.current.shift()!;
    setIsTTSLoading(true);

    try {
      abortControllerRef.current = new AbortController();

      const response = await fetch("/api/voice/synthesize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: sentence,
          voice: preferredVoice,
          speed: playbackSpeed,
        }),
        signal: abortControllerRef.current.signal,
      });

      if (!response.ok) {
        throw new Error("TTS request failed");
      }

      const audioBlob = await response.blob();
      const audioUrl = URL.createObjectURL(audioBlob);
      const audio = new Audio(audioUrl);
      audioRef.current = audio;

      audio.onended = () => {
        // Update spoken text when sentence finishes
        setSpokenText((prev) => (prev ? prev + " " + sentence : sentence));
        URL.revokeObjectURL(audioUrl);
        isProcessingRef.current = false;
        playNext();
      };

      audio.onerror = () => {
        URL.revokeObjectURL(audioUrl);
        isProcessingRef.current = false;
        playNext();
      };

      setIsTTSLoading(false);
      setIsTTSPlaying(true);
      await audio.play();
    } catch (err) {
      if (err instanceof Error && err.name !== "AbortError") {
        console.error("TTS error:", err);
      }
      setIsTTSLoading(false);
      isProcessingRef.current = false;
    }
  }, [preferredVoice, playbackSpeed]);

  const streamTTS = useCallback(
    (text: string, isComplete: boolean = false) => {
      if (!autoPlayback) return;

      // Combine buffer with new text
      const fullText =
        bufferRef.current + text.slice(processedTextRef.current.length);
      processedTextRef.current = text;

      const { sentences, buffer } = detectSentences(fullText, isComplete);
      bufferRef.current = buffer;

      // Queue new sentences
      if (sentences.length > 0) {
        queueRef.current.push(...sentences);
      }

      // Start playback if not already playing
      if (
        !isProcessingRef.current &&
        !isTTSPlaying &&
        queueRef.current.length > 0
      ) {
        playNext();
      }
    },
    [autoPlayback, isTTSPlaying, playNext]
  );

  const stopTTS = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    queueRef.current = [];
    isProcessingRef.current = false;
    setIsTTSPlaying(false);
    setIsTTSLoading(false);
  }, []);

  const resetTTS = useCallback(() => {
    stopTTS();
    processedTextRef.current = "";
    bufferRef.current = "";
    setSpokenText("");
  }, [stopTTS]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopTTS();
    };
  }, [stopTTS]);

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
