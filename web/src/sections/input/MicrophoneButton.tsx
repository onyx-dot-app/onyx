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
  const { isTTSPlaying, isTTSLoading } = useVoiceMode();

  // Refs for tracking state across renders
  const wasTTSPlayingRef = useRef(false);
  const prevChatStateRef = useRef<ChatState | undefined>(chatState);

  // Handler for VAD-triggered auto-send (when server detects silence)
  const handleFinalTranscript = useCallback(
    (text: string) => {
      onTranscription(text);
      // Only auto-send if chat is ready for input (not streaming)
      if (autoSend && onAutoSend && chatState === "input") {
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
      await stopRecording();
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
    if (
      wasTTSPlayingRef.current &&
      !isTTSPlaying &&
      !isTTSLoading &&
      autoListen &&
      !disabled
    ) {
      startRecording().catch(() => {
        // Silently ignore auto-start failures
      });
    }
    wasTTSPlayingRef.current = isTTSPlaying || isTTSLoading;
  }, [isTTSPlaying, isTTSLoading, autoListen, disabled, startRecording]);

  // Auto-start listening when chat response finishes (streaming -> input)
  // Only if autoListen is enabled - otherwise it's single-turn (user must click mic again)
  useEffect(() => {
    const wasStreaming = prevChatStateRef.current === "streaming";
    const nowInput = chatState === "input";

    // Only auto-start if:
    // 1. Chat just finished streaming (was streaming, now input)
    // 2. autoListen is enabled (user wants continuous conversation)
    // 3. Not disabled
    // 4. TTS is not playing (will be handled by TTS effect if it plays)
    if (
      wasStreaming &&
      nowInput &&
      autoListen &&
      !disabled &&
      !isTTSPlaying &&
      !isTTSLoading
    ) {
      startRecording().catch(() => {
        // Silently ignore auto-start failures
      });
    }

    prevChatStateRef.current = chatState;
  }, [
    chatState,
    autoListen,
    disabled,
    isTTSPlaying,
    isTTSLoading,
    startRecording,
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
