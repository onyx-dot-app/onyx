import { useState, useRef, useCallback, useEffect } from "react";
import { StreamingTTSPlayer } from "@/lib/streamingTTS";
import { useVoiceMode } from "@/providers/VoiceModeProvider";

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

  const playerRef = useRef<StreamingTTSPlayer | null>(null);
  const suppressPlayerErrorsRef = useRef(false);
  const { setManualTTSPlaying, isTTSMuted, registerManualTTSMuteHandler } =
    useVoiceMode();

  useEffect(() => {
    registerManualTTSMuteHandler((muted) => {
      playerRef.current?.setMuted(muted);
    });
    return () => {
      registerManualTTSMuteHandler(null);
    };
  }, [registerManualTTSMuteHandler]);

  const stop = useCallback(() => {
    suppressPlayerErrorsRef.current = true;
    if (playerRef.current) {
      playerRef.current.stop();
      playerRef.current = null;
    }
    setManualTTSPlaying(false);
    setError(null);
    setIsPlaying(false);
    setIsLoading(false);
  }, [setManualTTSPlaying]);

  const pause = useCallback(() => {
    // Streaming player currently supports stop/resume via restart, not true pause.
    stop();
  }, [stop]);

  const play = useCallback(
    async (text: string, voice?: string, speed?: number) => {
      // Stop any existing playback
      stop();
      suppressPlayerErrorsRef.current = false;
      setError(null);
      setIsLoading(true);

      try {
        const player = new StreamingTTSPlayer({
          onPlayingChange: (playing) => {
            setIsPlaying(playing);
            setManualTTSPlaying(playing);
            if (playing) {
              setIsLoading(false);
            }
          },
          onError: (playbackError) => {
            if (suppressPlayerErrorsRef.current) {
              return;
            }
            console.error("Voice playback error:", playbackError);
            setManualTTSPlaying(false);
            setError(playbackError);
            setIsLoading(false);
            setIsPlaying(false);
          },
        });
        playerRef.current = player;
        player.setMuted(isTTSMuted);

        await player.speak(text, voice, speed);
        setIsLoading(false);
      } catch (err) {
        if (err instanceof Error && err.name === "AbortError") {
          // Request was cancelled, not an error
          return;
        }
        const message =
          err instanceof Error ? err.message : "Speech synthesis failed";
        setError(message);
        setIsLoading(false);
        setIsPlaying(false);
        setManualTTSPlaying(false);
      }
    },
    [isTTSMuted, setManualTTSPlaying, stop]
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
