"use client";

import { useCallback, useEffect, useRef } from "react";
import { Button } from "@opal/components";
import { SvgMicrophone } from "@opal/icons";
import { useVoiceRecorder } from "@/hooks/useVoiceRecorder";
import { useVoiceMode } from "@/providers/VoiceModeProvider";
import { toast } from "@/hooks/useToast";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { ChatState } from "@/app/app/interfaces";

interface MicrophoneButtonProps {
  onTranscription: (text: string) => void;
  disabled?: boolean;
  autoSend?: boolean;
  /** Called with transcribed text when autoSend is enabled */
  onAutoSend?: (text: string) => void;
  /**
   * Internal prop: auto-start listening when TTS finishes or chat response completes.
   * Tied to voice_auto_playback user preference.
   * Enables conversation flow: speak → AI responds → auto-listen again.
   * Note: autoSend is separate - it controls whether message auto-submits after recording.
   */
  autoListen?: boolean;
  /** Current chat state - used to detect when response streaming finishes */
  chatState?: ChatState;
  /** Called when recording state changes */
  onRecordingChange?: (isRecording: boolean) => void;
  /** Ref to expose stop recording function to parent */
  stopRecordingRef?: React.MutableRefObject<
    (() => Promise<string | null>) | null
  >;
  /** Called when recording starts to clear input */
  onRecordingStart?: () => void;
}

function MicrophoneButton({
  onTranscription,
  disabled = false,
  autoSend = false,
  onAutoSend,
  autoListen = false,
  chatState,
  onRecordingChange,
  stopRecordingRef,
  onRecordingStart,
}: MicrophoneButtonProps) {
  const { isTTSPlaying, isTTSLoading, manualStopCount } = useVoiceMode();

  // Refs for tracking state across renders
  const wasTTSPlayingRef = useRef(false);
  const manualStopRequestedRef = useRef(false);
  const lastHandledManualStopCountRef = useRef(manualStopCount);

  // Handler for VAD-triggered auto-send (when server detects silence)
  const handleFinalTranscript = useCallback(
    (text: string) => {
      onTranscription(text);
      const isManualStop = manualStopRequestedRef.current;
      // Only auto-send if chat is ready for input (not streaming)
      if (!isManualStop && autoSend && onAutoSend && chatState === "input") {
        onAutoSend(text);
      }
    },
    [onTranscription, autoSend, onAutoSend, chatState]
  );

  const {
    isRecording,
    isProcessing,
    error,
    liveTranscript,
    startRecording,
    stopRecording,
  } = useVoiceRecorder({ onFinalTranscript: handleFinalTranscript });

  // Expose stopRecording to parent
  useEffect(() => {
    if (stopRecordingRef) {
      stopRecordingRef.current = stopRecording;
    }
  }, [stopRecording, stopRecordingRef]);

  // Notify parent when recording state changes
  useEffect(() => {
    onRecordingChange?.(isRecording);
  }, [isRecording, onRecordingChange]);

  // Update input with live transcript as user speaks
  useEffect(() => {
    if (isRecording && liveTranscript) {
      onTranscription(liveTranscript);
    }
  }, [isRecording, liveTranscript, onTranscription]);

  const handleClick = useCallback(async () => {
    if (isRecording) {
      // When recording, clicking the mic button stops recording
      manualStopRequestedRef.current = true;
      try {
        await stopRecording();
      } finally {
        manualStopRequestedRef.current = false;
      }
    } else {
      try {
        // Clear input before starting recording
        onRecordingStart?.();
        await startRecording();
      } catch {
        toast.error("Could not access microphone");
      }
    }
  }, [isRecording, startRecording, stopRecording, onRecordingStart]);

  // Auto-start listening when TTS finishes (only if autoListen is enabled)
  useEffect(() => {
    const stoppedManually =
      manualStopCount !== lastHandledManualStopCountRef.current;

    if (
      wasTTSPlayingRef.current &&
      !isTTSPlaying &&
      !isTTSLoading &&
      autoListen &&
      !disabled &&
      !stoppedManually
    ) {
      startRecording().catch(() => {
        // Silently ignore auto-start failures
      });
    }

    if (stoppedManually) {
      lastHandledManualStopCountRef.current = manualStopCount;
    }

    wasTTSPlayingRef.current = isTTSPlaying || isTTSLoading;
  }, [
    isTTSPlaying,
    isTTSLoading,
    autoListen,
    disabled,
    startRecording,
    manualStopCount,
  ]);

  useEffect(() => {
    if (error) {
      toast.error(error);
    }
  }, [error]);

  // Icon: show loader when processing, otherwise mic
  const icon = isProcessing ? SimpleLoader : SvgMicrophone;

  // Disable when processing or TTS is playing (don't want to pick up TTS audio)
  const isDisabled = disabled || isProcessing || isTTSPlaying || isTTSLoading;

  // Debug logging for disabled state
  useEffect(() => {
    console.log(
      `[MicrophoneButton] isDisabled=${isDisabled}: ` +
        `disabled=${disabled}, isProcessing=${isProcessing}, ` +
        `isTTSPlaying=${isTTSPlaying}, isTTSLoading=${isTTSLoading}, ` +
        `isRecording=${isRecording}`
    );
  }, [
    disabled,
    isProcessing,
    isTTSPlaying,
    isTTSLoading,
    isRecording,
    isDisabled,
  ]);

  // Recording = darkened (primary), not recording = light (tertiary)
  const prominence = isRecording ? "primary" : "tertiary";

  return (
    <Button
      icon={icon}
      disabled={isDisabled}
      onClick={handleClick}
      aria-label={isRecording ? "Stop recording" : "Start recording"}
      prominence={prominence}
    />
  );
}

export default MicrophoneButton;
