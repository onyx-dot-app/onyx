"use client";

import { useEffect, useState, useMemo } from "react";
import { cn } from "@/lib/utils";
import { formatElapsedTime } from "@/lib/dateUtils";
import { Button } from "@opal/components";
import { SvgMicrophone, SvgMicrophoneOff } from "@opal/icons";

interface RecordingWaveformProps {
  isRecording: boolean;
  isMuted?: boolean;
  onMuteToggle?: () => void;
}

function RecordingWaveform({
  isRecording,
  isMuted = false,
  onMuteToggle,
}: RecordingWaveformProps) {
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  // Reset and start timer when recording starts
  useEffect(() => {
    if (!isRecording) {
      setElapsedSeconds(0);
      return;
    }

    const interval = setInterval(() => {
      setElapsedSeconds((prev) => prev + 1);
    }, 1000);

    return () => clearInterval(interval);
  }, [isRecording]);

  const formattedTime = useMemo(
    () => formatElapsedTime(elapsedSeconds),
    [elapsedSeconds]
  );

  // Generate bar heights for waveform animation
  const bars = useMemo(() => {
    return Array.from({ length: 120 }, (_, i) => ({
      id: i,
      // Create a wave pattern with some randomness
      baseHeight: Math.sin(i * 0.15) * 6 + 8,
      delay: i * 0.008,
    }));
  }, []);

  if (!isRecording) {
    return null;
  }

  return (
    <div className="flex items-center gap-3 px-3 py-2 bg-background-tint-00 rounded-12 min-h-[32px]">
      {/* Waveform visualization */}
      <div className="flex-1 flex items-center justify-between h-4 overflow-hidden">
        {bars.map((bar) => (
          <div
            key={bar.id}
            className={cn(
              "w-[1.5px] bg-text-03 rounded-full shrink-0",
              !isMuted && "animate-waveform"
            )}
            style={{
              // When muted, show flat bars (2px height), otherwise animate with base height
              height: isMuted ? "2px" : `${bar.baseHeight}px`,
              animationDelay: isMuted ? undefined : `${bar.delay}s`,
            }}
          />
        ))}
      </div>

      {/* Timer */}
      <span className="font-mono text-xs text-text-03 tabular-nums shrink-0">
        {formattedTime}
      </span>

      {/* Mute button */}
      {onMuteToggle && (
        <Button
          icon={isMuted ? SvgMicrophoneOff : SvgMicrophone}
          onClick={onMuteToggle}
          prominence="tertiary"
          size="sm"
          aria-label={isMuted ? "Unmute microphone" : "Mute microphone"}
        />
      )}
    </div>
  );
}

export default RecordingWaveform;
