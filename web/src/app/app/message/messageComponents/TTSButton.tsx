"use client";

import { useCallback, useEffect } from "react";
import { SvgPlayCircle, SvgStop } from "@opal/icons";
import { Button } from "@opal/components";
import { useVoicePlayback } from "@/hooks/useVoicePlayback";
import { useVoiceMode } from "@/providers/VoiceModeProvider";
import { toast } from "@/hooks/useToast";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";

interface TTSButtonProps {
  text: string;
  voice?: string;
  speed?: number;
}

function TTSButton({ text, voice, speed }: TTSButtonProps) {
  const { isPlaying, isLoading, error, play, pause, stop } = useVoicePlayback();
  const { isTTSPlaying, isTTSLoading, isAwaitingAutoPlaybackStart, stopTTS } =
    useVoiceMode();

  const isGlobalTTSActive =
    isTTSPlaying || isTTSLoading || isAwaitingAutoPlaybackStart;
  const isButtonPlaying = isGlobalTTSActive || isPlaying;
  const isButtonLoading = !isGlobalTTSActive && isLoading;

  const handleClick = useCallback(async () => {
    if (isGlobalTTSActive) {
      // Stop auto-playback voice mode stream from the toolbar button.
      stopTTS({ manual: true });
      stop();
    } else if (isPlaying) {
      pause();
    } else if (isButtonLoading) {
      stop();
    } else {
      try {
        // Ensure no voice-mode stream is active before starting manual playback.
        stopTTS();
        await play(text, voice, speed);
      } catch (err) {
        console.error("TTS playback failed:", err);
        toast.error("Could not play audio");
      }
    }
  }, [
    isGlobalTTSActive,
    isPlaying,
    isButtonLoading,
    text,
    voice,
    speed,
    play,
    pause,
    stop,
    stopTTS,
  ]);

  // Surface streaming voice playback errors to the user via toast
  useEffect(() => {
    if (error) {
      toast.error(error);
    }
  }, [error]);

  const icon = isButtonLoading
    ? SimpleLoader
    : isButtonPlaying
      ? SvgStop
      : SvgPlayCircle;

  const tooltip = isButtonPlaying
    ? "Stop playback"
    : isButtonLoading
      ? "Loading..."
      : "Read aloud";

  return (
    <Button
      icon={icon}
      onClick={handleClick}
      prominence="tertiary"
      tooltip={tooltip}
      data-testid="AgentMessage/tts-button"
    />
  );
}

export default TTSButton;
