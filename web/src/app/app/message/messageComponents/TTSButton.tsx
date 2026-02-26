"use client";

import { useCallback } from "react";
import { SvgPlayCircle, SvgPauseCircle, SvgStop } from "@opal/icons";
import { Button } from "@opal/components";
import { useVoicePlayback } from "@/hooks/useVoicePlayback";
import { toast } from "@/hooks/useToast";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";

interface TTSButtonProps {
  text: string;
  voice?: string;
  speed?: number;
}

function TTSButton({ text, voice, speed }: TTSButtonProps) {
  const { isPlaying, isLoading, error, play, pause, stop } = useVoicePlayback();

  const handleClick = useCallback(async () => {
    if (isPlaying) {
      pause();
    } else if (isLoading) {
      stop();
    } else {
      try {
        await play(text, voice, speed);
      } catch {
        toast.error("Could not play audio");
      }
    }
  }, [isPlaying, isLoading, text, voice, speed, play, pause, stop]);

  if (error) {
    toast.error(error);
  }

  const icon = isLoading ? SimpleLoader : isPlaying ? SvgStop : SvgPlayCircle;

  const tooltip = isPlaying
    ? "Stop playback"
    : isLoading
      ? "Loading..."
      : "Read aloud";

  return (
    <Button
      icon={icon}
      onClick={handleClick}
      tooltip={tooltip}
      data-testid="AgentMessage/tts-button"
    />
  );
}

export default TTSButton;
