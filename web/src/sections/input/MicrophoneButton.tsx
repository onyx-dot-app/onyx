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
  /** Called when mute state changes */
  onMuteChange?: (isMuted: boolean) => void;
  /** Ref to expose setMuted function to parent */
  setMutedRef?: React.MutableRefObject<((muted: boolean) => void) | null>;
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
  onMuteChange,
  setMutedRef,
}: MicrophoneButtonProps) {
  const { isTTSPlaying, isTTSLoading, manualStopCount } = useVoiceMode();

  // Refs for tracking state across renders
  const wasTTSPlayingRef = useRef(false);
  const manualStopRequestedRef = useRef(false);
  const lastHandledManualStopCountRef = useRef(manualStopCount);
  const autoListenCooldownTimerRef = useRef<NodeJS.Timeout | null>(null);

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
    isMuted,
    error,
    liveTranscript,
    startRecording,
    stopRecording,
    setMuted,
  } = useVoiceRecorder({ onFinalTranscript: handleFinalTranscript });

  // Expose stopRecording to parent
  useEffect(() => {
    if (stopRecordingRef) {
      stopRecordingRef.current = stopRecording;
    }
  }, [stopRecording, stopRecordingRef]);

  // Expose setMuted to parent
  useEffect(() => {
    if (setMutedRef) {
      setMutedRef.current = setMuted;
    }
  }, [setMuted, setMutedRef]);

  // Notify parent when mute state changes
  useEffect(() => {
    onMuteChange?.(isMuted);
  }, [isMuted, onMuteChange]);

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

  // Auto-start listening shortly after TTS finishes (only if autoListen is enabled).
  // Small cooldown reduces playback bleed being re-captured by the microphone.
  useEffect(() => {
    if (autoListenCooldownTimerRef.current) {
      clearTimeout(autoListenCooldownTimerRef.current);
      autoListenCooldownTimerRef.current = null;
    }

    const stoppedManually =
      manualStopCount !== lastHandledManualStopCountRef.current;

    if (
      wasTTSPlayingRef.current &&
      !isTTSPlaying &&
      !isTTSLoading &&
      autoListen &&
      !disabled &&
      !isRecording &&
      !stoppedManually
    ) {
      autoListenCooldownTimerRef.current = setTimeout(() => {
        autoListenCooldownTimerRef.current = null;
        if (
          !autoListen ||
          disabled ||
          isRecording ||
          isTTSPlaying ||
          isTTSLoading
        ) {
          return;
        }
        startRecording().catch(() => {
          // Silently ignore auto-start failures
        });
      }, 400);
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
    isRecording,
    startRecording,
    manualStopCount,
  ]);

  useEffect(() => {
    return () => {
      if (autoListenCooldownTimerRef.current) {
        clearTimeout(autoListenCooldownTimerRef.current);
        autoListenCooldownTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    if (error) {
      toast.error(error);
    }
  }, [error]);

  // Icon: show loader when processing, otherwise mic
  const icon = isProcessing ? SimpleLoader : SvgMicrophone;

  // Disable when processing or TTS is playing (don't want to pick up TTS audio)
  const isDisabled = disabled || isProcessing || isTTSPlaying || isTTSLoading;

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
