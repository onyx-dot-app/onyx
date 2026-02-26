"use client";

import { useCallback } from "react";
import { Button } from "@opal/components";
import { SvgMicrophone, SvgStop } from "@opal/icons";
import { useVoiceRecorder } from "@/hooks/useVoiceRecorder";
import { toast } from "@/hooks/useToast";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";

interface MicrophoneButtonProps {
  onTranscription: (text: string) => void;
  disabled?: boolean;
  autoSend?: boolean;
  onAutoSend?: () => void;
}

function MicrophoneButton({
  onTranscription,
  disabled = false,
  autoSend = false,
  onAutoSend,
}: MicrophoneButtonProps) {
  const { isRecording, isProcessing, error, startRecording, stopRecording } =
    useVoiceRecorder();

  const handleClick = useCallback(async () => {
    if (isRecording) {
      const text = await stopRecording();
      if (text) {
        onTranscription(text);
        if (autoSend && onAutoSend) {
          onAutoSend();
        }
      }
    } else {
      try {
        await startRecording();
      } catch {
        toast.error("Could not access microphone");
      }
    }
  }, [
    isRecording,
    startRecording,
    stopRecording,
    onTranscription,
    autoSend,
    onAutoSend,
  ]);

  if (error) {
    toast.error(error);
  }

  const icon = isProcessing
    ? SimpleLoader
    : isRecording
      ? SvgStop
      : SvgMicrophone;

  return (
    <Button
      icon={icon}
      disabled={disabled || isProcessing}
      onClick={handleClick}
      aria-label={isRecording ? "Stop recording" : "Start recording"}
    />
  );
}

export default MicrophoneButton;
