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
  /** Called when recording starts */
  onRecordingStart?: () => void;
  /** Existing message text to prepend to transcription (append mode) */
  currentMessage?: string;
  /** Called when mute state changes */
  onMuteChange?: (isMuted: boolean) => void;
  /** Ref to expose setMuted function to parent */
  setMutedRef?: React.MutableRefObject<((muted: boolean) => void) | null>;
  /** Called with current microphone audio level (0-1) for waveform visualization */
  onAudioLevel?: (level: number) => void;
  /** Whether current chat is a new session (used to reset auto-listen arming) */
  isNewSession?: boolean;
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
  currentMessage = "",
  onMuteChange,
  setMutedRef,
  onAudioLevel,
  isNewSession = false,
}: MicrophoneButtonProps) {
  const {
    isTTSPlaying,
    isTTSLoading,
    isAwaitingAutoPlaybackStart,
    manualStopCount,
  } = useVoiceMode();

  // Refs for tracking state across renders
  // Track whether TTS was actually playing audio (not just loading)
  const wasTTSActuallyPlayingRef = useRef(false);
  const manualStopRequestedRef = useRef(false);
  const lastHandledManualStopCountRef = useRef(manualStopCount);
  const autoListenCooldownTimerRef = useRef<NodeJS.Timeout | null>(null);
  const hasManualRecordStartRef = useRef(false);
  // Prevent late transcript events from repopulating input after auto-send.
  const suppressTranscriptUpdatesRef = useRef(false);
  // Snapshot of existing message text when recording starts (for append mode)
  const messagePrefixRef = useRef("");
  const currentMessageRef = useRef(currentMessage);

  useEffect(() => {
    currentMessageRef.current = currentMessage;
  }, [currentMessage]);

  // Helper to combine prefix with new transcript
  const withPrefix = useCallback((text: string) => {
    const prefix = messagePrefixRef.current;
    if (!prefix) return text;
    return prefix + (prefix.endsWith(" ") ? "" : " ") + text;
  }, []);

  // Handler for VAD (Voice Activity Detection) triggered auto-send.
  // VAD runs server-side in the STT provider and detects when the user stops speaking.
  const handleFinalTranscript = useCallback(
    (text: string) => {
      const combined = withPrefix(text);
      if (!suppressTranscriptUpdatesRef.current) {
        onTranscription(combined);
      }
      const isManualStop = manualStopRequestedRef.current;
      // Only auto-send if chat is ready for input (not streaming)
      if (!isManualStop && autoSend && onAutoSend && chatState === "input") {
        suppressTranscriptUpdatesRef.current = true;
        onAutoSend(combined);
        // Clear prefix after send to prevent stale text in next auto-listen cycle
        messagePrefixRef.current = "";
      }
    },
    [onTranscription, autoSend, onAutoSend, chatState, withPrefix]
  );

  const {
    isRecording,
    isProcessing,
    isMuted,
    error,
    liveTranscript,
    audioLevel,
    startRecording,
    stopRecording,
    setMuted,
  } = useVoiceRecorder({
    onFinalTranscript: handleFinalTranscript,
    autoStopOnSilence: autoSend,
  });

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

  // Forward audio level to parent for waveform visualization
  useEffect(() => {
    onAudioLevel?.(audioLevel);
  }, [audioLevel, onAudioLevel]);

  // Notify parent when recording state changes
  useEffect(() => {
    onRecordingChange?.(isRecording);
  }, [isRecording, onRecordingChange]);

  // Update input with live transcript as user speaks (appending to existing text)
  useEffect(() => {
    if (
      isRecording &&
      liveTranscript &&
      !suppressTranscriptUpdatesRef.current
    ) {
      onTranscription(withPrefix(liveTranscript));
    }
  }, [isRecording, liveTranscript, onTranscription, withPrefix]);

  const handleClick = useCallback(async () => {
    if (isRecording) {
      // When recording, clicking the mic button stops recording
      manualStopRequestedRef.current = true;
      try {
        const finalTranscript = await stopRecording();
        if (finalTranscript) {
          const combined = withPrefix(finalTranscript);
          onTranscription(combined);
          if (
            autoSend &&
            onAutoSend &&
            chatState === "input" &&
            combined.trim()
          ) {
            onAutoSend(combined);
          }
        }
        messagePrefixRef.current = "";
      } finally {
        manualStopRequestedRef.current = false;
      }
    } else {
      try {
        // Snapshot existing text so transcription can append to it
        suppressTranscriptUpdatesRef.current = false;
        messagePrefixRef.current = currentMessage;
        onRecordingStart?.();
        await startRecording();
        // Arm auto-listen only after first manual mic start in this session.
        hasManualRecordStartRef.current = true;
      } catch (err) {
        console.error("Microphone access failed:", err);
        toast.error("Could not access microphone");
      }
    }
  }, [
    isRecording,
    startRecording,
    stopRecording,
    onRecordingStart,
    onTranscription,
    autoSend,
    onAutoSend,
    chatState,
    currentMessage,
    withPrefix,
  ]);

  // Auto-start listening shortly after TTS finishes (only if autoListen is enabled).
  // Small cooldown reduces playback bleed being re-captured by the microphone.
  // IMPORTANT: Only trigger auto-listen if TTS was actually playing audio,
  // not just loading. This prevents auto-listen from triggering when TTS fails.
  useEffect(() => {
    if (autoListenCooldownTimerRef.current) {
      clearTimeout(autoListenCooldownTimerRef.current);
      autoListenCooldownTimerRef.current = null;
    }

    const stoppedManually =
      manualStopCount !== lastHandledManualStopCountRef.current;

    // Only trigger auto-listen if TTS was actually playing (not just loading)
    if (
      wasTTSActuallyPlayingRef.current &&
      !isTTSPlaying &&
      !isTTSLoading &&
      !isAwaitingAutoPlaybackStart &&
      autoListen &&
      hasManualRecordStartRef.current &&
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
          isTTSLoading ||
          isAwaitingAutoPlaybackStart
        ) {
          return;
        }
        messagePrefixRef.current = currentMessageRef.current;
        startRecording().catch((err) => {
          console.error("Auto-start microphone failed:", err);
          toast.error("Could not auto-start microphone");
        });
      }, 400);
    }

    if (stoppedManually) {
      lastHandledManualStopCountRef.current = manualStopCount;
    }

    // Only track actual playback - not loading states
    // This ensures auto-listen only triggers after audio actually played
    if (isTTSPlaying) {
      wasTTSActuallyPlayingRef.current = true;
    } else if (!isTTSPlaying && !isTTSLoading && !isAwaitingAutoPlaybackStart) {
      // Reset when TTS is completely done
      wasTTSActuallyPlayingRef.current = false;
    }
  }, [
    isTTSPlaying,
    isTTSLoading,
    isAwaitingAutoPlaybackStart,
    autoListen,
    disabled,
    isRecording,
    startRecording,
    manualStopCount,
  ]);

  // New sessions must start with an explicit manual mic press.
  useEffect(() => {
    if (isNewSession) {
      hasManualRecordStartRef.current = false;
      suppressTranscriptUpdatesRef.current = false;
    }
  }, [isNewSession]);

  useEffect(() => {
    if (!isRecording) {
      suppressTranscriptUpdatesRef.current = false;
    }
  }, [isRecording]);

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
      console.error("Voice recorder error:", error);
      toast.error(error);
    }
  }, [error]);

  // Icon: show loader when processing, otherwise mic
  const icon = isProcessing ? SimpleLoader : SvgMicrophone;

  // Disable when processing or TTS is playing (don't want to pick up TTS audio)
  const isDisabled =
    disabled ||
    isProcessing ||
    isTTSPlaying ||
    isTTSLoading ||
    isAwaitingAutoPlaybackStart;

  // Recording = darkened (primary), not recording = light (tertiary)
  const prominence = isRecording ? "primary" : "tertiary";

  return (
    <Button
      disabled={isDisabled}
      icon={icon}
      onClick={handleClick}
      aria-label={isRecording ? "Stop recording" : "Start recording"}
      prominence={prominence}
    />
  );
}

export default MicrophoneButton;
