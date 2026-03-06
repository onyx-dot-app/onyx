import { useState, useRef, useCallback } from "react";

export interface UseVoicePlaybackReturn {
  isPlaying: boolean;
  isLoading: boolean;
  error: string | null;
  play: (text: string, voice?: string, speed?: number) => Promise<void>;
  pause: () => void;
  stop: () => void;
}

export function useVoicePlayback(): UseVoicePlaybackReturn {
  const [isPlaying, setIsPlaying] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioUrlRef = useRef<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const stop = useCallback(() => {
    // Revoke object URL to prevent memory leak
    if (audioUrlRef.current) {
      URL.revokeObjectURL(audioUrlRef.current);
      audioUrlRef.current = null;
    }
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.src = "";
      audioRef.current = null;
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setIsPlaying(false);
    setIsLoading(false);
  }, []);

  const pause = useCallback(() => {
    if (audioRef.current && isPlaying) {
      audioRef.current.pause();
      setIsPlaying(false);
    }
  }, [isPlaying]);

  const play = useCallback(
    async (text: string, voice?: string, speed?: number) => {
      // Stop any existing playback
      stop();
      setError(null);
      setIsLoading(true);

      try {
        abortControllerRef.current = new AbortController();

        const params = new URLSearchParams();
        params.set("text", text);
        if (voice) params.set("voice", voice);
        if (speed !== undefined) params.set("speed", speed.toString());

        const response = await fetch(`/api/voice/synthesize?${params}`, {
          method: "POST",
          signal: abortControllerRef.current.signal,
          credentials: "include",
        });

        if (!response.ok) {
          const errorData = await response.json();
          throw new Error(errorData.detail || "Speech synthesis failed");
        }

        const audioBlob = await response.blob();
        const audioUrl = URL.createObjectURL(audioBlob);
        audioUrlRef.current = audioUrl;

        const audio = new Audio(audioUrl);
        audioRef.current = audio;

        // Capture audioUrl in closure to avoid race condition where an old
        // audio callback revokes a newer audio's object URL
        audio.onended = () => {
          setIsPlaying(false);
          // Only revoke if this is still the current audio URL
          if (audioUrlRef.current === audioUrl) {
            URL.revokeObjectURL(audioUrl);
            audioUrlRef.current = null;
          }
        };

        audio.onerror = () => {
          setError("Audio playback failed");
          setIsPlaying(false);
          // Only revoke if this is still the current audio URL
          if (audioUrlRef.current === audioUrl) {
            URL.revokeObjectURL(audioUrl);
            audioUrlRef.current = null;
          }
        };

        setIsLoading(false);
        setIsPlaying(true);
        await audio.play();
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") {
          // Request was cancelled, not an error
          return;
        }
        const message =
          err instanceof Error ? err.message : "Speech synthesis failed";
        setError(message);
        setIsLoading(false);
      }
    },
    [stop]
  );

  return {
    isPlaying,
    isLoading,
    error,
    play,
    pause,
    stop,
  };
}
