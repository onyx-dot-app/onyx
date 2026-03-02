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
      console.log(
        "MicrophoneButton: VAD triggered final transcript:",
        text,
        "chatState:",
        chatState
      );
      onTranscription(text);
      // Only auto-send if chat is ready for input (not streaming)
      if (autoSend && onAutoSend && chatState === "input") {
        console.log("MicrophoneButton: VAD auto-sending");
        onAutoSend(text);
      } else if (chatState !== "input") {
        console.log(
          "MicrophoneButton: skipping auto-send, chat is not ready (state:",
          chatState,
          ")"
        );
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
    console.log(
      "MicrophoneButton: liveTranscript effect - isRecording:",
      isRecording,
      "liveTranscript:",
      liveTranscript
    );
    if (isRecording && liveTranscript) {
      console.log(
        "MicrophoneButton: calling onTranscription with:",
        liveTranscript
      );
      onTranscription(liveTranscript);
    }
  }, [isRecording, liveTranscript, onTranscription]);

  const handleClick = useCallback(async () => {
    console.log("MicrophoneButton handleClick: isRecording =", isRecording);
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
    console.log(
      "MicrophoneButton: autoListen effect - wasTTSPlaying:",
      wasTTSPlayingRef.current,
      "isTTSPlaying:",
      isTTSPlaying,
      "isTTSLoading:",
      isTTSLoading,
      "autoListen:",
      autoListen,
      "disabled:",
      disabled
    );
    if (
      wasTTSPlayingRef.current &&
      !isTTSPlaying &&
      !isTTSLoading &&
      autoListen &&
      !disabled
    ) {
      console.log("MicrophoneButton: TTS finished, auto-starting recording");
      startRecording()
        .then(() =>
          console.log("MicrophoneButton: auto-start recording succeeded")
        )
        .catch((e) =>
          console.error("MicrophoneButton: auto-start recording failed:", e)
        );
    }
    wasTTSPlayingRef.current = isTTSPlaying || isTTSLoading;
  }, [isTTSPlaying, isTTSLoading, autoListen, disabled, startRecording]);

  // Auto-start listening when chat response finishes (streaming -> input)
  // Only if autoListen is enabled - otherwise it's single-turn (user must click mic again)
  useEffect(() => {
    const wasStreaming = prevChatStateRef.current === "streaming";
    const nowInput = chatState === "input";

    console.log(
      "MicrophoneButton: chatState effect - prev:",
      prevChatStateRef.current,
      "current:",
      chatState,
      "autoListen:",
      autoListen,
      "disabled:",
      disabled,
      "isTTSPlaying:",
      isTTSPlaying,
      "isTTSLoading:",
      isTTSLoading
    );

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
      console.log(
        "MicrophoneButton: chat response finished, auto-starting recording"
      );
      startRecording()
        .then(() =>
          console.log("MicrophoneButton: auto-start after response succeeded")
        )
        .catch((e) =>
          console.error(
            "MicrophoneButton: auto-start after response failed:",
            e
          )
        );
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

  console.log(
    "MicrophoneButton render: isRecording:",
    isRecording,
    "isProcessing:",
    isProcessing,
    "isDisabled:",
    isDisabled
  );

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
